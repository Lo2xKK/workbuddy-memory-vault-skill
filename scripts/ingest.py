#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest.py —— 把 WorkBuddy 的记忆与历史对话，编译成 Obsidian 图谱记忆库。

在 sync.py 的基础上扩展了三块能力，把「对话归档器」升级成「图谱记忆库生成器」：

1. `.manifest.json` 增量机制  —— 只处理新增 / 变更的会话，重复运行不重跑全量
2. `40-时间线/` 月节点        —— 时间维度：按月聚合会话，会话 ↔ 月节点双向链接
3. `30-人物/` 人物节点        —— 人物维度：从身份文件提炼「我」的图谱锚点

主题维度沿用 topics.json 的规则分类，并自动生成主题聚合页（主题 ↔ 会话成网）。

用法：
    python ingest.py                    # 增量同步（只处理变更）
    python ingest.py --full             # 强制全量重建
    python ingest.py --list             # 只列出会处理哪些会话，不写任何文件
    python ingest.py --vault <目录>     # 指定输出 vault（默认用本脚本所在位置自定位）
    python ingest.py --only <ID前缀>    # 只同步匹配的会话
    python ingest.py --no-tools         # 不输出工具调用轨迹
    python ingest.py --no-raw           # 不备份 jsonl 到 90-原始数据/
    python ingest.py --no-memory        # 不同步 30-我的记忆/
    python ingest.py --no-timeline      # 不生成 40-时间线/
    python ingest.py --no-person        # 不生成 30-人物/

数据源（只读，不修改 ~/.workbuddy 下任何文件）：
    ~/.workbuddy/workbuddy.db                      会话标题 / 工作目录 / 状态 / 模型
    ~/.workbuddy/projects/<slug>/<session>.jsonl   完整对话记录
    ~/.workbuddy/{SOUL,IDENTITY,USER,MEMORY}.md    身份与长期记忆
    ~/.workbuddy/memory/<uid>_memory.md            服务端用户画像

部署：把 scripts/ 与 config/ 的内容一并复制到 <vault>/_tools/，脚本用 __file__ 自定位
vault 根，无需改路径。config/topics.json 会先找 <vault>/_tools/topics.json，找不到再
回退到 scripts/../config/topics.json（开发形态）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 路径配置

HOME = Path(os.path.expanduser("~"))
WB = HOME / ".workbuddy"

# 脚本自定位 vault 根：部署形态是 <vault>/_tools/ingest.py，开发形态是 <repo>/scripts/ingest.py
# 两者都满足「脚本所在目录的上一级 = 输出根」。--vault 参数可覆盖。
DEFAULT_VAULT = Path(__file__).resolve().parent.parent

ARCHIVE_DIR = "20-对话归档"
MEMORY_DIR = "30-我的记忆"
PERSON_DIR = "30-人物"
TIMELINE_DIR = "40-时间线"
RAW_DIR = "90-原始数据"

# 默认扫描「项目记忆」的根目录（空表；由 topics.json 的 memory_roots 显式配置）
MEMORY_ROOTS: list[str] = []

# ---------------------------------------------------------------- 文本清洗

# 这些标签块是每次对话自动注入的样板，不是人要读的内容
STRIP_TAGS = [
    "system-reminder", "product_identity", "memory_and_skills_reminder",
    "user_custom_instructions", "identity_context", "project_context",
    "project_layout", "additional_data", "connector-status", "workspace_identity",
    "current_time", "user_info", "user_memory", "memory", "agent_loop",
    "automations", "instructions_for_visualizer", "visualizer_examples",
    "task_management", "asking_questions", "tool_usage_policy", "agent_skills",
    "plugin_recommendation", "expert_management", "mcp_configuration",
    "response_language", "binary_context", "result_presentation", "sharing_files",
    "final_answer_instructions", "content_policy", "personal_files_safety",
    "regional_conventions", "working_modes", "tool_use",
]

_TAG_RE = re.compile(
    r"<(" + "|".join(re.escape(t) for t in STRIP_TAGS) + r")\b[^>]*>.*?</\1\s*>",
    re.S | re.I,
)
_ORPHAN_RE = re.compile(r"</?[a-zA-Z_-]+\b[^>]*>")
_BLANK_RE = re.compile(r"\n{3,}")
_ILLEGAL = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')


def clean_text(text: str) -> str:
    """剥掉自动注入的样板块，留下人真正写 / 真正读的内容。"""
    if not text:
        return ""
    prev = None
    for _ in range(4):  # 反复剥离，处理嵌套
        if prev == text:
            break
        prev = text
        text = _TAG_RE.sub("\n", text)
    text = _ORPHAN_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _BLANK_RE.sub("\n\n", text)
    return text.strip()


_FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
_HEAD_RE = re.compile(r"^(#{1,6})\s")


def demote_headings(text: str) -> str:
    """把正文里的标题整体降一级，避免污染大纲面板（代码块内的 # 不动）。"""
    out: list[str] = []
    fence: str | None = None
    for ln in text.split("\n"):
        m = _FENCE_RE.match(ln)
        if m:
            tok = m.group(1)
            if fence is None:
                fence = tok
            elif fence == tok:
                fence = None
            out.append(ln)
            continue
        if fence is None:
            hm = _HEAD_RE.match(ln)
            if hm and len(hm.group(1)) < 6:
                ln = "#" + ln
        out.append(ln)
    return "\n".join(out)


def slugify(title: str, limit: int = 42) -> str:
    s = _ILLEGAL.sub("", title or "")
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ", "-")
    if len(s) > limit:
        s = s[:limit].rstrip("-")
    return s or "未命名会话"


def yq(s: str) -> str:
    """YAML 字符串安全化。"""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------- 配置读取


def resolve_config() -> Path:
    """配置文件位置：优先用户本地 topics.json，缺失则回退到随仓库分发的 topics.example.json 模板。

    部署形态 <vault>/_tools/，开发形态 <repo>/config/；example 只作为零配置兜底。
    """
    candidates = [
        DEFAULT_VAULT / "_tools" / "topics.json",
        Path(__file__).resolve().parent.parent / "config" / "topics.json",
        DEFAULT_VAULT / "_tools" / "topics.example.json",
        Path(__file__).resolve().parent.parent / "config" / "topics.example.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


CONFIG_FILE = resolve_config()


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"rules": [], "default": "日常与运维", "topics": {}, "projects": {}}


def classify(title: str, cwd: str, cfg: dict) -> str:
    hay = f"{title}\n{cwd}".lower()
    for rule in cfg.get("rules", []):
        for kw in rule.get("match", []):
            if kw.lower() in hay:
                return rule["topic"]
    return cfg.get("default", "日常与运维")


def project_name(cwd: str, cfg: dict) -> str:
    key = (cwd or "").lower().rstrip("\\/")
    projects = cfg.get("projects", {})
    if key in projects:
        return projects[key]
    best = None
    for k, v in projects.items():
        kk = k.lower().rstrip("\\/")
        if key.startswith(kk) and (best is None or len(kk) > len(best[0])):
            best = (kk, v)
    if best:
        return best[1]
    return cfg.get("project_default", "临时工作区")


def resolve_title(sid: str, raw: str, cfg: dict, limit: int = 56) -> str:
    t = re.sub(r"\s+", " ", raw or "").strip()
    for prefix, new in cfg.get("title_prefix_rules", []):
        if t.startswith(prefix):
            t = new
            break
    for key, new in cfg.get("title_overrides", {}).items():
        if sid.startswith(key):
            t = new
            break
    if len(t) > limit:
        t = t[:limit].rstrip("，,。.、 ") + "…"
    return t or "未命名会话"


# ---------------------------------------------------------------- manifest 增量


def manifest_path(vault: Path) -> Path:
    return vault / ".manifest.json"


def load_manifest(vault: Path) -> dict:
    p = manifest_path(vault)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_manifest(vault: Path, manifest: dict) -> None:
    manifest_path(vault).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def is_changed(sid: str, mtime_ms: int, manifest: dict) -> bool:
    """会话是否新增或变更过。mtime 用毫秒整数，和 jsonl 文件 stat 对齐。"""
    rec = manifest.get(sid)
    if rec is None:
        return True
    return rec.get("mtime") != mtime_ms


# ---------------------------------------------------------------- 读会话表


def load_sessions() -> dict:
    """从 workbuddy.db 读会话元数据（只读打开，不影响正在运行的 App）。"""
    db = WB / "workbuddy.db"
    if not db.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    out: dict[str, dict] = {}
    try:
        cur = con.execute(
            "select id, cwd, title, custom_title, status, created_at, updated_at, "
            "model, is_background_automation from sessions"
        )
        for row in cur:
            (sid, cwd, title, custom, status, ca, ua, model, bg) = row
            out[sid] = {
                "id": sid,
                "cwd": cwd or "",
                "title": (custom or title or "").strip(),
                "status": status or "",
                "created_at": ca,
                "updated_at": ua,
                "model": model or "",
                "background": bool(bg),
            }
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


# ---------------------------------------------------------------- 解析 jsonl


def parse_transcript(path: Path) -> dict:
    """把一份 jsonl 记录解析成「轮次」结构：一轮 = 一条用户消息 + 其后的所有助手文本。"""
    turns: list[dict] = []
    tool_trace: list[tuple[str, str]] = []
    ai_title = ""
    cwd = ""
    t_min = t_max = None
    n_user_lines = 0
    n_asst_lines = 0
    n_bad = 0

    cur: dict | None = None

    for line in path.open(encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            n_bad += 1
            continue

        t = o.get("type")
        ts = o.get("timestamp")
        if isinstance(ts, (int, float)) and ts > 0:
            t_min = ts if t_min is None else min(t_min, ts)
            t_max = ts if t_max is None else max(t_max, ts)
        if o.get("cwd"):
            cwd = o["cwd"]

        if t == "ai-title":
            ai_title = o.get("aiTitle") or ai_title

        elif t == "message" and o.get("role") == "user":
            n_user_lines += 1
            raw = "".join(
                p.get("text", "") for p in (o.get("content") or []) if isinstance(p, dict)
            )
            text = clean_text(raw)
            if not text:
                continue
            cur = {"time": ts, "user": text, "assistant": []}
            turns.append(cur)

        elif t == "message" and o.get("role") == "assistant":
            n_asst_lines += 1
            raw = "".join(
                p.get("text", "") for p in (o.get("content") or []) if isinstance(p, dict)
            )
            text = clean_text(raw)
            if not text:
                continue
            if cur is None:
                cur = {"time": ts, "user": "", "assistant": []}
                turns.append(cur)
            cur["assistant"].append(text)

        elif t == "function_call":
            name = o.get("name") or "?"
            args = o.get("arguments")
            if isinstance(args, (dict, list)):
                args = json.dumps(args, ensure_ascii=False)
            args = re.sub(r"\s+", " ", str(args or "")).strip()
            tool_trace.append((name, args[:160]))

    for tn in turns:  # 合并同一轮里碎片化的助手文本
        tn["assistant"] = "\n\n".join(tn["assistant"]).strip()

    return {
        "turns": turns,
        "tools": tool_trace,
        "ai_title": ai_title,
        "cwd": cwd,
        "t_min": t_min,
        "t_max": t_max,
        "n_user_lines": n_user_lines,
        "n_asst_lines": n_asst_lines,
        "n_bad": n_bad,
    }


def fmt_ts(ms, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not ms:
        return "—"
    return datetime.fromtimestamp(ms / 1000).strftime(fmt)


# ---------------------------------------------------------------- 人物提取


def extract_person_fields(cfg: dict) -> dict:
    """从身份文件里提取「我」的关键字段（轻量正则，不引依赖）。"""
    person = cfg.get("person", {})
    name = person.get("name", "我")
    out = {"name": name, "label": person.get("label", f"我（{name}）")}

    user = WB / "USER.md"
    if user.exists():
        txt = user.read_text(encoding="utf-8", errors="replace")
        for key, field in [("Name", "name"), ("City", "city"), ("Notes", "notes")]:
            m = re.search(rf"\*\*{key}:\*\*\s*(.+)", txt)
            if m:
                out[field] = m.group(1).strip()

    ident = WB / "IDENTITY.md"
    if ident.exists():
        txt = ident.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"\*\*Vibe:\*\*\s*(.+)", txt)
        if m:
            out["vibe"] = m.group(1).strip()
    return out


# ---------------------------------------------------------------- 渲染会话归档


def render_conversation(meta: dict, data: dict, cfg: dict) -> str:
    title = meta["title"] or data["ai_title"] or "未命名会话"
    topic = classify(title, meta["cwd"], cfg)
    tinfo = cfg.get("topics", {}).get(topic, {})
    topic_label = tinfo.get("label", topic)
    topic_note = tinfo.get("note", "")
    proj = project_name(meta["cwd"], cfg)
    person_name = cfg.get("person", {}).get("name", "我")

    started = meta["created_at"]
    day = datetime.fromtimestamp(started / 1000)
    month = day.strftime("%Y-%m")
    turns = [t for t in data["turns"] if t["user"] or t["assistant"]]

    L: list[str] = []
    L.append("---")
    L.append(f"title: {yq(title)}")
    L.append("type: conversation")
    L.append(f"topic: {yq(topic)}")
    L.append(f"session_id: {meta['id']}")
    L.append(f"date: {day.strftime('%Y-%m-%d')}")
    L.append(f"timeline: {yq(month)}")          # 时间维度
    L.append(f"person: {yq(person_name)}")      # 人物维度
    L.append(f"started: {yq(fmt_ts(meta['created_at']))}")
    L.append(f"ended: {yq(fmt_ts(meta['updated_at']))}")
    L.append(f"project: {yq(proj)}")
    L.append(f"workspace: {yq(meta['cwd'])}")
    L.append(f"status: {yq(meta['status'])}")
    if meta["model"]:
        L.append(f"model: {yq(meta['model'])}")
    L.append(f"turns: {len(turns)}")
    L.append(f"tool_calls: {len(data['tools'])}")
    if meta["background"]:
        L.append("automation: true")
    L.append("tags:")
    L.append("  - 对话归档")
    L.append(f"  - {topic}")
    L.append("generated_by: ingest.py")
    L.append(f"generated_at: {yq(datetime.now().strftime('%Y-%m-%d %H:%M'))}")
    L.append("---")
    L.append("")
    L.append(f"# {title}")
    L.append("")

    span = ""
    if data["t_min"] and data["t_max"]:
        mins = int((data["t_max"] - data["t_min"]) / 60000)
        span = f"（{mins} 分钟）" if mins >= 1 else "（不到 1 分钟）"

    L.append("> [!info] 会话档案")
    L.append(f"> **时间**　{fmt_ts(meta['created_at'])} → {fmt_ts(meta['updated_at'])}{span}")
    L.append(f"> **项目**　{proj}　`{meta['cwd']}`")
    L.append(
        f"> **规模**　{len(turns)} 轮对话 · {len(data['tools'])} 次工具调用"
        f" · 状态 `{meta['status']}`"
    )
    if topic_note:
        L.append(f"> **主题**　[[{topic_note}|{topic_label}]]")
    if meta["background"]:
        L.append("> **备注**　这是后台自动化任务产生的会话")
    L.append("")
    # 面包屑克制：首页 + 时间线月节点，各一条语义出口（不堆 3 条索引链接）
    L.append(f"[[Home|← 首页]]　·　[[{TIMELINE_DIR}/{month}|← {month} 时间线]]")
    L.append("")
    L.append("---")

    for i, tn in enumerate(turns, 1):
        L.append("")
        head = f"## 第 {i} 轮"
        if tn["time"]:
            head += f"　`{fmt_ts(tn['time'], '%H:%M')}`"
        L.append(head)
        L.append("")
        if tn["user"]:
            L.append("**我**")
            L.append("")
            u = demote_headings(tn["user"])
            L.extend("> " + ln if ln.strip() else ">" for ln in u.split("\n"))
            L.append("")
        if tn["assistant"]:
            L.append("**小迪**")
            L.append("")
            L.append(demote_headings(tn["assistant"]))
            L.append("")

    if data["tools"]:
        L.append("---")
        L.append("")
        L.append(f"> [!example]- 工具调用轨迹（{len(data['tools'])} 次）")
        for name, args in data["tools"]:
            a = args.replace("`", "'")
            L.append(f"> - `{name}` — {a}" if a else f"> - `{name}`")
        L.append("")

    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 渲染人物节点


def render_person(cfg: dict, topics_touched: set[str]) -> str:
    """生成「我」的人物节点：身份摘要 + 关联主题 + 身份快照链接。"""
    p = extract_person_fields(cfg)
    name = p.get("name", "我")
    label = p.get("label", f"我（{name}）")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    L: list[str] = []
    L.append("---")
    L.append(f"title: {yq(label)}")
    L.append("type: person")
    L.append(f"name: {yq(name)}")
    L.append("generated_by: ingest.py")
    L.append(f"generated_at: {yq(now)}")
    L.append("tags:")
    L.append("  - 人物")
    L.append("---")
    L.append("")
    L.append(f"# {label}")
    L.append("")
    L.append("> [!info] 人物节点")
    L.append("> 这是「我」在图谱里的锚点。所有对话的 user 端都归属于这里。")
    L.append("")

    # 身份摘要
    L.append("## 身份")
    L.append("")
    for field, k in [("name", "名字"), ("city", "城市"), ("notes", "备注"), ("vibe", "气场")]:
        if p.get(field):
            L.append(f"- **{k}**：{p[field]}")
    L.append("")

    # 关联主题（知识层 → 知识层，让图成网）
    if topics_touched:
        L.append("## 关注的主题")
        L.append("")
        for topic in sorted(topics_touched):
            tinfo = cfg.get("topics", {}).get(topic, {})
            note = tinfo.get("note", "")
            lbl = tinfo.get("label", topic)
            if note:
                L.append(f"- [[{note}|{lbl}]]")
            else:
                L.append(f"- {lbl}")
        L.append("")

    # 身份快照（原料层，供追溯）
    L.append("## 关联")
    L.append("")
    L.append("- 身份快照：[[30-我的记忆/身份文件/USER 用户档案|USER · 关于你]] · [[30-我的记忆/身份文件/SOUL 灵魂档案|SOUL · 灵魂档案]] · [[30-我的记忆/身份文件/IDENTITY 身份记录|IDENTITY · 身份]]")
    L.append("- 长期记忆：[[30-我的记忆/身份文件/跨项目长期记忆|跨项目长期记忆]]")
    L.append("- 用户画像：[[30-我的记忆/用户画像/用户画像|服务端画像]]")
    L.append("- 项目记忆：[[30-我的记忆/项目记忆/项目记忆索引|项目记忆索引]]")
    L.append("")
    L.append("---")
    L.append("")
    L.append("> 对话清单见 [[20-对话归档/对话索引|对话索引]]（按 `person` 字段筛选）。")
    L.append("")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 渲染时间线


def render_timeline_month(month: str, rows: list[dict], cfg: dict) -> str:
    """生成时间线月节点：显式列当月会话（时间维度），并链向当月涉及的主题。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    topics = sorted({r["topic"] for r in rows})

    L: list[str] = []
    L.append("---")
    L.append(f"title: {yq(month + ' 时间线')}")
    L.append("type: timeline")
    L.append(f"month: {yq(month)}")
    L.append("generated_by: ingest.py")
    L.append(f"generated_at: {yq(now)}")
    L.append("tags:")
    L.append("  - 时间线")
    L.append("---")
    L.append("")
    L.append(f"# {month} 时间线")
    L.append("")
    L.append(f"> [!info] 本月共 {len(rows)} 个会话")
    L.append("")

    L.append("## 会话")
    L.append("")
    for r in rows:
        L.append(f"- [[20-对话归档/{r['rel']}|{r['title']}]]　`{r['day']}`")
    L.append("")

    L.append("## 涉及的主题")
    L.append("")
    for topic in topics:
        tinfo = cfg.get("topics", {}).get(topic, {})
        note = tinfo.get("note", "")
        lbl = tinfo.get("label", topic)
        if note:
            L.append(f"- [[{note}|{lbl}]]")
        else:
            L.append(f"- {lbl}")
    L.append("")

    L.append("")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 渲染主题聚合页


def render_topic_aggregate(topic: str, rows: list[dict], cfg: dict) -> str:
    """自动生成主题聚合页：主题下所有会话的索引（主题 ↔ 会话成网）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    tinfo = cfg.get("topics", {}).get(topic, {})
    label = tinfo.get("label", topic)
    emoji = tinfo.get("emoji", "")

    L: list[str] = []
    L.append("---")
    L.append(f"title: {yq(label + ' · 会话索引')}")
    L.append("type: topic")
    L.append(f"topic: {yq(topic)}")
    L.append("generated_by: ingest.py")
    L.append(f"generated_at: {yq(now)}")
    L.append("tags:")
    L.append(f"  - {topic}")
    L.append("---")
    L.append("")
    L.append(f"# {emoji} {label} · 会话索引")
    L.append("")
    L.append(f"> 本主题下共 **{len(rows)}** 个会话（由 ingest.py 自动聚合）。")
    L.append("")
    L.append("| 日期 | 会话 | 项目 |")
    L.append("| --- | --- | --- |")
    for r in rows:
        L.append(f"| {r['day']} | [[20-对话归档/{r['rel']}\\|{r['title']}]] | {r['project']} |")
    L.append("")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 骨架文件


def ensure_scaffold(vault: Path, cfg: dict) -> int:
    """自动生成索引层 / 知识层的骨架文件，让「断链 0 / 孤岛 0」不依赖手工维护。

    骨架只做导航与入口，绝不写会话细节（会话清单交给 Bases / 聚合页）。
    用户可以在其上手工补充，脚本用 generated_by 标记、不覆盖手工改动。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    made = 0

    # ---- 00-总览 / Home
    ov = vault / "00-总览"
    ov.mkdir(parents=True, exist_ok=True)
    person_name = cfg.get("person", {}).get("name", "我")
    person_label = cfg.get("person", {}).get("label", f"我（{person_name}）")

    home = ov / "Home.md"
    if not home.exists():
        L = [
            "---",
            "type: index",
            "generated_by: ingest.py",
            "---",
            "",
            "# Home",
            "",
            "> 这是记忆库总入口。按维度跳转：",
            "",
            f"- [[主题地图]] —— 按主题浏览",
            f"- [[时间线]] —— 按时间浏览",
            f"- [[{PERSON_DIR}/{person_name}|{person_label}]] —— 关于我",
            f"- [[{ARCHIVE_DIR}/对话索引|对话索引]] —— 全部会话",
            "",
        ]
        home.write_text("\n".join(L), encoding="utf-8", newline="\n")
        made += 1

    # ---- 00-总览 / 主题地图
    tmap = ov / "主题地图.md"
    if not tmap.exists():
        L = ["---", "type: index", "generated_by: ingest.py", "---", "", "# 主题地图", ""]
        for topic in sorted(cfg.get("topics", {})):
            tinfo = cfg["topics"][topic]
            note = tinfo.get("note", "")
            lbl = tinfo.get("label", topic)
            emoji = tinfo.get("emoji", "")
            if note:
                L.append(f"- {emoji} [[{note}|{lbl}]]")
            else:
                L.append(f"- {emoji} {lbl}")
        L.append("")
        tmap.write_text("\n".join(L), encoding="utf-8", newline="\n")
        made += 1

    # ---- 00-总览 / 时间线（扫描 40-时间线/ 目录，自动跟上月份）
    tline = ov / "时间线.md"
    if not tline.exists():
        tl_dir = vault / TIMELINE_DIR
        months = sorted((p.stem for p in tl_dir.glob("*.md")), reverse=True) if tl_dir.exists() else []
        L = [
            "---",
            "type: index",
            "generated_by: ingest.py",
            "---",
            "",
            "# 时间线",
            "",
            "> 按月份浏览会话：",
            "",
        ]
        for month in months:
            L.append(f"- [[{TIMELINE_DIR}/{month}|{month}]]")
        L.append("")
        tline.write_text("\n".join(L), encoding="utf-8", newline="\n")
        made += 1

    # ---- 10-主题 / <note> 总览
    topic_dir = vault / "10-主题"
    topic_dir.mkdir(parents=True, exist_ok=True)
    for topic, tinfo in cfg.get("topics", {}).items():
        note = tinfo.get("note", "")
        if not note:
            continue
        label = tinfo.get("label", topic)
        emoji = tinfo.get("emoji", "")
        p = topic_dir / f"{note}.md"
        if p.exists():
            continue
        agg = f"{label} 会话索引"
        agg_link = f"[[{agg}]]" if (topic_dir / f"{agg}.md").exists() else agg
        L = [
            "---",
            f"title: {yq(note)}",
            "type: topic-overview",
            f"topic: {yq(topic)}",
            "generated_by: ingest.py",
            f"generated_at: {yq(now)}",
            "---",
            "",
            f"# {emoji} {note}",
            "",
            f"> 本主题的会话索引见 {agg_link}。",
            "",
            "## 子话题卡片",
            "",
            "（手工维护：在这里列本主题的子话题卡片，每张卡片承载结论 / 决策 / 待办。）",
            "",
            "## 跨主题关联",
            "",
            "（手工维护：链向相关的其他主题。）",
            "",
            "## 悬而未决",
            "",
            "（手工维护：本主题下待解决的问题。）",
            "",
        ]
        p.write_text("\n".join(L), encoding="utf-8", newline="\n")
        made += 1

    return made


# ---------------------------------------------------------------- 记忆归档


def write_memory_files(vault: Path, cfg: dict) -> list[str]:
    """把身份文件、用户画像、项目记忆归档进 30-我的记忆/。"""
    made: list[str] = []
    mem_dir = vault / MEMORY_DIR
    ident = mem_dir / "身份文件"
    ident.mkdir(parents=True, exist_ok=True)

    head = (
        "---\n"
        "type: memory-source\n"
        "generated_by: ingest.py\n"
        f"generated_at: {yq(datetime.now().strftime('%Y-%m-%d %H:%M'))}\n"
        "---\n\n"
        "> [!warning] 这是自动同步的只读副本\n"
        "> 原始文件在 `~/.workbuddy/`。**不要改这里**——改了会在下次同步时被覆盖。\n"
        "> 要改，改原件，然后重跑 `ingest.py`。\n\n"
    )

    for fname, out, title in [
        ("SOUL.md", "SOUL 灵魂档案.md", "SOUL · 我的灵魂档案"),
        ("IDENTITY.md", "IDENTITY 身份记录.md", "IDENTITY · 身份记录"),
        ("USER.md", "USER 用户档案.md", "USER · 关于你"),
    ]:
        src = WB / fname
        if not src.exists():
            continue
        body = src.read_text(encoding="utf-8", errors="replace")
        body = re.sub(r"^---\n.*?\n---\n", "", body, flags=re.S)
        p = ident / out
        p.write_text(head + f"# {title}\n\n{body.strip()}\n", encoding="utf-8", newline="\n")
        made.append(str(p))

    src = WB / "MEMORY.md"
    if src.exists():
        body = src.read_text(encoding="utf-8", errors="replace")
        body = re.sub(r"^# 用户级长期记忆\n*", "", body)
        p = ident / "跨项目长期记忆.md"
        p.write_text(
            head + "# 跨项目长期记忆\n\n> 原件：`~/.workbuddy/MEMORY.md`\n\n" + body.strip() + "\n",
            encoding="utf-8",
            newline="\n",
        )
        made.append(str(p))

    prof = mem_dir / "用户画像"
    prof.mkdir(parents=True, exist_ok=True)
    cand = list((WB / "memory").glob("*_memory.md")) if (WB / "memory").exists() else []
    for src in cand:
        raw = src.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"## Memory Block\n(.*?)\n---\n", raw, re.S)
        block = (m.group(1) if m else raw).strip()
        m2 = re.search(r"> Last updated: (\S+)", raw)
        updated = m2.group(1) if m2 else "未知"
        m3 = re.search(r"> Version: (\d+)", raw)
        ver = m3.group(1) if m3 else "?"
        p = prof / "用户画像.md"
        p.write_text(
            head
            + "# 用户画像（服务端记忆）\n\n"
            + f"> 由 WorkBuddy 服务端自动维护 · 快照版本 v{ver} · 最后更新 {updated}\n"
            + "> 原件：`~/.workbuddy/memory/<uid>_memory.md`\n\n"
            + "---\n\n"
            + block
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        made.append(str(p))

    # 各项目的 .workbuddy/memory
    proj_root = mem_dir / "项目记忆"
    if proj_root.exists():
        shutil.rmtree(proj_root)
    proj_root.mkdir(parents=True, exist_ok=True)

    def mem_head(project: str, source: str) -> str:
        return (
            "---\n"
            "type: memory-source\n"
            f"project: {yq(project)}\n"
            f"source: {yq(source)}\n"
            "generated_by: ingest.py\n"
            f"generated_at: {yq(datetime.now().strftime('%Y-%m-%d %H:%M'))}\n"
            "---\n\n"
            "> [!warning] 这是自动同步的只读副本\n"
            "> 原始文件在项目目录下的 `.workbuddy/memory/`。**不要改这里**——"
            "改了会在下次同步时被覆盖。\n"
            "> 要改，改原件，然后重跑 `ingest.py`。\n\n"
        )

    roots = [Path(r) for r in cfg.get("memory_roots", MEMORY_ROOTS)]
    index_rows: list[tuple[str, str, str, str]] = []
    default_proj = cfg.get("project_default", "临时工作区")

    for root in roots:
        if not root.exists():
            continue
        cands: list[Path] = []
        own = root / ".workbuddy" / "memory"
        if own.is_dir():
            cands.append(own)
        try:
            cands += list(root.glob("*/.workbuddy/memory"))
            cands += list(root.glob("*/*/.workbuddy/memory"))
        except OSError:
            pass
        for d in sorted(set(cands)):
            files = sorted(f for f in d.iterdir() if f.is_file() and f.suffix == ".md")
            if not files:
                continue
            proj_path = d.parent.parent
            mapped = project_name(str(proj_path), cfg)
            unlisted = mapped == default_proj
            folder = _ILLEGAL.sub("-", mapped).strip("-") or "未分类"
            outdir = proj_root / folder
            outdir.mkdir(parents=True, exist_ok=True)
            tag = _ILLEGAL.sub("-", proj_path.name).strip("-") if unlisted else ""
            multi = len(files) > 1
            for f in files:
                stem = _ILLEGAL.sub("-", f.stem).strip("-") or "未命名"
                if tag:
                    name = f"{tag}--{stem}" if multi else tag
                else:
                    name = stem
                body = f.read_text(encoding="utf-8", errors="replace")
                body = re.sub(r"^---\n.*?\n---\n", "", body, flags=re.S)
                hm = re.search(r"^#{1,4}\s+(.+)$", body, re.M)
                summary = hm.group(1).strip() if hm else ""
                summary = re.sub(r"[\|\r\n]", " ", summary)[:48]
                label = f"{tag or folder} · {f.stem}"
                p = outdir / f"{name}.md"
                p.write_text(
                    mem_head(folder, str(f))
                    + f"# {label}\n\n> 原件：`{f}`\n\n---\n\n{body.strip()}\n",
                    encoding="utf-8",
                    newline="\n",
                )
                made.append(str(p))
                index_rows.append((folder, name, str(f), summary))

    if index_rows:
        idx = proj_root / "项目记忆索引.md"
        L = [
            "---",
            "type: index",
            "generated_by: ingest.py",
            "---",
            "",
            "# 项目记忆索引",
            "",
            "> 各项目 `.workbuddy/memory/` 的只读快照，按项目分组。",
            "> 这些是「小迪」在各项目里留下的工作日志与长期约定，不是对话记录。",
            "",
            f"共 **{len(index_rows)}** 份 · 来自 **{len({r[0] for r in index_rows})}** 个项目",
            "",
            "---",
            "",
            "| 项目 | 快照 | 内容 | 原件 |",
            "| --- | --- | --- | --- |",
        ]
        for folder, name, src, summary in sorted(index_rows):
            L.append(
                f"| {folder} | [[30-我的记忆/项目记忆/{folder}/{name}\\|{name}]] "
                f"| {summary} | `{src}` |"
            )
        L.append("")
        idx.write_text("\n".join(L), encoding="utf-8", newline="\n")
        made.append(str(idx))

    return made


# ---------------------------------------------------------------- 原始数据备份


def copy_raw_files(vault: Path, entries: list[tuple[Path, str]]) -> int:
    raw_dir = vault / RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "_关于这个目录.md").write_text(
        "---\ntype: readme\ngenerated_by: ingest.py\n---\n\n"
        "# 关于 90-原始数据/\n\n"
        "这里存放 WorkBuddy 原始对话记录（`.jsonl`）的只读副本，**不要手工编辑**。\n\n"
        "- 用途：当 `20-对话归档/` 的 Markdown 渲染出错、或你想用别的工具重新解析时，原始数据还在。\n"
        "- **如果要把这个仓库上传到公开平台，请把整个 `90-原始数据/` 排除掉。**\n"
        "  里面可能含有本机路径、临时文件名等个人信息。建议在 `.gitignore` 里加一行 `90-原始数据/`。\n\n"
        "重新生成：`python ingest.py --full`\n",
        encoding="utf-8",
        newline="\n",
    )
    n = 0
    for src, sid in entries:
        dst = raw_dir / f"{sid}.jsonl"
        try:
            shutil.copy2(src, dst)
            n += 1
        except OSError:
            pass
    return n


# ---------------------------------------------------------------- 索引渲染


def render_index_page(rows: list[dict], cfg: dict) -> str:
    return "\n".join(
        [
            "---",
            "type: index",
            "generated_by: ingest.py",
            "---",
            "",
            "# 对话索引",
            "",
            "> 会话总表由 **Bases 视图**动态生成 —— 不在这里硬写链接，",
            "> 所以索引层不会在图谱里制造重复的连线。",
            "> 想按主题看 → [[主题地图]]；想按时间轴看 → [[时间线]]。",
            "",
            f"共 **{len(rows)}** 个会话 · "
            f"**{sum(r['turns'] for r in rows)}** 轮对话 · "
            f"**{sum(r['tools'] for r in rows)}** 次工具调用",
            "",
            "---",
            "",
            "![[对话索引.base]]",
            "",
        ]
    ) + "\n"


def render_bases() -> str:
    return "\n".join(
        [
            "filters:",
            "  and:",
            '    - \'file.inFolder("20-对话归档")\'',
            '    - \'type == "conversation"\'',
            "properties:",
            "  note.date:",
            "    displayName: 日期",
            "  note.topic:",
            "    displayName: 主题",
            "  note.project:",
            "    displayName: 项目",
            "  note.person:",
            "    displayName: 人物",
            "  note.turns:",
            "    displayName: 轮次",
            "  note.status:",
            "    displayName: 状态",
            "views:",
            "  - type: table",
            "    name: 全部会话",
            "    order:",
            "      - file.name",
            "      - note.date",
            "      - note.topic",
            "      - note.project",
            "      - note.person",
            "      - note.turns",
            "    groupBy:",
            "      property: note.date",
            "      direction: DESC",
            "",
        ]
    )


# ---------------------------------------------------------------- 主流程


def main() -> int:
    ap = argparse.ArgumentParser(description="把 WorkBuddy 记忆与对话编译成 Obsidian 图谱记忆库")
    ap.add_argument("--vault", default=None, help="输出 vault 根目录（默认自定位）")
    ap.add_argument("--list", action="store_true", help="只列出会话，不写文件")
    ap.add_argument("--full", action="store_true", help="忽略 manifest，强制全量重建")
    ap.add_argument("--only", default=None, help="只同步 id 以该前缀开头的会话")
    ap.add_argument("--no-tools", action="store_true", help="不输出工具调用轨迹")
    ap.add_argument("--no-raw", action="store_true", help="不备份 jsonl 到 90-原始数据/")
    ap.add_argument("--no-memory", action="store_true", help="不同步 30-我的记忆/")
    ap.add_argument("--no-timeline", action="store_true", help="不生成 40-时间线/")
    ap.add_argument("--no-person", action="store_true", help="不生成 30-人物/")
    args = ap.parse_args()

    vault = Path(args.vault).resolve() if args.vault else DEFAULT_VAULT

    cfg = load_config()
    sessions = load_sessions()
    manifest = load_manifest(vault)

    proj_root = WB / "projects"
    if not proj_root.exists():
        print(f"找不到对话目录：{proj_root}")
        return 1

    files = sorted(p for p in proj_root.glob("*/*.jsonl") if p.is_file())
    entries: list[tuple[Path, dict, int]] = []
    for f in files:
        sid = f.stem
        if args.only and not sid.startswith(args.only):
            continue
        meta = sessions.get(sid)
        if meta is None:
            meta = {
                "id": sid,
                "cwd": "",
                "title": "",
                "status": "unknown",
                "created_at": int(f.stat().st_mtime * 1000),
                "updated_at": int(f.stat().st_mtime * 1000),
                "model": "",
                "background": False,
            }
        mtime = int(f.stat().st_mtime * 1000)
        entries.append((f, meta, mtime))

    if not entries:
        print("没有匹配的会话。")
        return 0

    # 增量过滤
    to_process: list[tuple[Path, dict, int]] = []
    skipped = 0
    for f, meta, mtime in entries:
        if is_changed(meta["id"], mtime, manifest):
            to_process.append((f, meta, mtime))
        else:
            skipped += 1

    print(f"找到 {len(entries)} 个会话记录（{len(to_process)} 个待处理，{skipped} 个未变更跳过）\n")

    if args.list:
        for f, meta, _mtime in entries:
            d = datetime.fromtimestamp(meta["created_at"] / 1000).strftime("%m-%d %H:%M")
            t = resolve_title(meta["id"], meta["title"], cfg)
            topic = classify(t, meta["cwd"], cfg)
            mark = "  " if (f, meta, _mtime) in to_process else "~ "
            print(f"{mark}{d}  {meta['status']:<10} {topic:<12} {t}")
        return 0

    if not to_process:
        print("没有需要处理的会话，全部未变更。")
        return 0

    archive_dir = vault / ARCHIVE_DIR
    archive_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    written = 0
    for f, meta, mtime in to_process:
        data = parse_transcript(f)
        if not data["turns"] and not data["ai_title"]:
            skipped += 1
            continue
        title = resolve_title(meta["id"], meta["title"] or data["ai_title"], cfg)
        meta["title"] = title
        if not meta["cwd"]:
            meta["cwd"] = data["cwd"]

        topic = classify(title, meta["cwd"], cfg)
        day = datetime.fromtimestamp(meta["created_at"] / 1000)
        outdir = archive_dir / day.strftime("%Y-%m")
        outdir.mkdir(parents=True, exist_ok=True)
        stem = f"{day.strftime('%Y-%m-%d-%H%M')}-{slugify(title)}"
        out = outdir / f"{stem}.md"

        md = render_conversation(meta, data, cfg)
        if args.no_tools:
            md = re.sub(r"\n---\n\n> \[!example\]- 工具调用轨迹.*$", "\n", md, flags=re.S)
        out.write_text(md, encoding="utf-8", newline="\n")
        written += 1

        rel = out.relative_to(archive_dir).with_suffix("").as_posix()
        rows.append(
            {
                "stem": out.stem,
                "rel": rel,
                "title": title,
                "topic": topic,
                "project": project_name(meta["cwd"], cfg),
                "turns": len([t for t in data["turns"] if t["user"] or t["assistant"]]),
                "tools": len(data["tools"]),
                "ts": meta["created_at"],
                "month": day.strftime("%Y-%m"),
                "day": day.strftime("%Y-%m-%d %H:%M"),
            }
        )
        manifest[meta["id"]] = {"mtime": mtime, "stem": stem}
        print(f"  ✓ {stem}")

    # 清理旧的「年/月」两层结构（已改为「年-月」一层）
    for d in archive_dir.iterdir():
        if d.is_dir() and re.fullmatch(r"\d{4}", d.name):
            shutil.rmtree(d, ignore_errors=True)

    (archive_dir / "对话索引.md").write_text(
        render_index_page(rows, cfg), encoding="utf-8", newline="\n"
    )
    (archive_dir / "对话索引.base").write_text(render_bases(), encoding="utf-8", newline="\n")

    # 时间线月节点（聚合「本次新生成 + 历史」的全部会话，保证时间线完整）
    n_timeline = 0
    if not args.no_timeline:
        timeline_dir = vault / TIMELINE_DIR
        timeline_dir.mkdir(parents=True, exist_ok=True)
        # 收集 vault 里所有会话的 frontmatter（含历史会话），按月分组
        by_month: dict[str, list[dict]] = {}
        for p in archive_dir.rglob("*.md"):
            if p.name == "对话索引.md":
                continue
            txt = p.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^month:\s*(.+)$", txt, re.M)  # 用 timeline 字段回填
            if not m:
                m = re.search(r"^timeline:\s*[\"']?([\d-]+)", txt, re.M)
            if not m:
                continue
            month = m.group(1).strip().strip('"')
            rel = p.relative_to(archive_dir).with_suffix("").as_posix()
            title = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", txt, re.M)
            date = re.search(r"^date:\s*[\"']?([\d-]+)", txt, re.M)
            topic = re.search(r"^topic:\s*[\"']?(.+?)[\"']?\s*$", txt, re.M)
            by_month.setdefault(month, []).append(
                {
                    "rel": rel,
                    "title": title.group(1).strip().strip('"') if title else p.stem,
                    "day": date.group(1) if date else "",
                    "topic": topic.group(1).strip().strip('"') if topic else "",
                }
            )
        for month, mrows in sorted(by_month.items()):
            out = timeline_dir / f"{month}.md"
            out.write_text(render_timeline_month(month, mrows, cfg), encoding="utf-8", newline="\n")
            n_timeline += 1

    # 人物节点
    n_person = 0
    if not args.no_person:
        person_dir = vault / PERSON_DIR
        person_dir.mkdir(parents=True, exist_ok=True)
        # 从全部已归档会话收集「关注的主题」，保证增量模式下也完整
        topics_touched: set[str] = set()
        for p in archive_dir.rglob("*.md"):
            if p.name == "对话索引.md":
                continue
            txt = p.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^topic:\s*[\"']?(.+?)[\"']?\s*$", txt, re.M)
            if m:
                topics_touched.add(m.group(1).strip().strip('"'))
        person_name = cfg.get("person", {}).get("name", "我")
        out = person_dir / f"{person_name}.md"
        out.write_text(render_person(cfg, topics_touched), encoding="utf-8", newline="\n")
        n_person = 1

    # 主题聚合页
    topic_dir = vault / "10-主题"
    topic_dir.mkdir(parents=True, exist_ok=True)
    by_topic: dict[str, list[dict]] = {}
    for r in rows:
        by_topic.setdefault(r["topic"], []).append(r)
    for topic, trows in by_topic.items():
        tinfo = cfg.get("topics", {}).get(topic, {})
        label = tinfo.get("label", topic)
        out = topic_dir / f"{label} 会话索引.md"
        out.write_text(render_topic_aggregate(topic, trows, cfg), encoding="utf-8", newline="\n")

    # 骨架文件（Home / 主题地图 / 时间线总览 / 主题总览）
    n_scaffold = ensure_scaffold(vault, cfg)

    # 记忆归档 + 原始备份
    made_mem: list[str] = []
    if not args.no_memory:
        made_mem = write_memory_files(vault, cfg)

    n_raw = 0
    if not args.no_raw:
        n_raw = copy_raw_files(vault, [(f, m["id"]) for f, m, _ in to_process])

    save_manifest(vault, manifest)

    print()
    print(f"对话归档：{written} 个（跳过空会话/未变更共 {skipped} 个）")
    print(f"时间线节点：{n_timeline} 个月")
    print(f"人物节点：{n_person} 个")
    print(f"主题聚合页：{len(by_topic)} 个")
    print(f"骨架文件：{n_scaffold} 个")
    print(f"记忆副本：{len(made_mem)} 个文件")
    if n_raw:
        print(f"原始备份：{n_raw} 个 jsonl -> 90-原始数据/")
    print(f"索引已更新：20-对话归档/对话索引.md + 对话索引.base")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
