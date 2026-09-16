#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render.py —— 把解析结果渲染成 Obsidian markdown（frontmatter + 正文）。"""

from __future__ import annotations

from datetime import datetime

from common import (
    ARCHIVE_DIR,
    MEMORY_DIR,
    PERSON_DIR,
    TIMELINE_DIR,
    demote_headings,
    fmt_ts,
    yaml_quote,
)
from config import classify, project_name
from parse import extract_person_fields

# ---------------------------------------------------------------- 渲染会话归档


def render_conversation(meta: dict, data: dict, cfg: dict) -> str:
    title = meta["title"] or data["ai_title"] or "未命名会话"
    topic = classify(title, meta["cwd"], cfg)
    tinfo = cfg.get("topics", {}).get(topic, {})
    topic_label = tinfo.get("label", topic)
    topic_note = tinfo.get("note", "")
    proj = project_name(meta["cwd"], cfg)
    person_name = cfg.get("person", {}).get("name", "我")

    started = meta["created_at"] or meta["updated_at"] or 0
    if not started:
        started = int(__import__("time").time() * 1000)
    day = datetime.fromtimestamp(started / 1000)
    month = day.strftime("%Y-%m")
    turns = [t for t in data["turns"] if t["user"] or t["assistant"]]

    L: list[str] = []
    L.append("---")
    L.append(f"title: {yaml_quote(title)}")
    L.append("type: conversation")
    L.append(f"topic: {yaml_quote(topic)}")
    L.append(f"session_id: {meta['id']}")
    L.append(f"date: {day.strftime('%Y-%m-%d')}")
    L.append(f"timeline: {yaml_quote(month)}")          # 时间维度（时间线扫描只认这个字段）
    L.append(f"person: {yaml_quote(person_name)}")      # 人物维度
    L.append(f"started: {yaml_quote(fmt_ts(started))}")
    L.append(f"ended: {yaml_quote(fmt_ts(meta['updated_at']))}")
    L.append(f"project: {yaml_quote(proj)}")
    L.append(f"workspace: {yaml_quote(meta['cwd'])}")
    L.append(f"status: {yaml_quote(meta['status'])}")
    if meta["model"]:
        L.append(f"model: {yaml_quote(meta['model'])}")
    L.append(f"turns: {len(turns)}")
    L.append(f"tool_calls: {len(data['tools'])}")
    if meta["background"]:
        L.append("automation: true")
    L.append("tags:")
    L.append("  - 对话归档")
    L.append(f"  - {topic}")
    L.append("generated_by: ingest.py")
    L.append(f"generated_at: {yaml_quote(datetime.now().strftime('%Y-%m-%d %H:%M'))}")
    L.append("---")
    L.append("")
    L.append(f"# {title}")
    L.append("")

    span = ""
    if data["t_min"] and data["t_max"]:
        mins = int((data["t_max"] - data["t_min"]) / 60000)
        span = f"（{mins} 分钟）" if mins >= 1 else "（不到 1 分钟）"

    L.append("> [!info] 会话档案")
    L.append(f"> **时间**　{fmt_ts(started)} → {fmt_ts(meta['updated_at'])}{span}")
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
    L.append(f"title: {yaml_quote(label)}")
    L.append("type: person")
    L.append(f"name: {yaml_quote(name)}")
    L.append("generated_by: ingest.py")
    L.append(f"generated_at: {yaml_quote(now)}")
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
    for field, k in [("name", "名字"), ("full_name", "实名"), ("city", "城市"),
                     ("notes", "备注"), ("vibe", "气场")]:
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
    L.append(f"title: {yaml_quote(month + ' 时间线')}")
    L.append("type: timeline")
    L.append(f"month: {yaml_quote(month)}")
    L.append("generated_by: ingest.py")
    L.append(f"generated_at: {yaml_quote(now)}")
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
    L.append(f"title: {yaml_quote(label + ' · 会话索引')}")
    L.append("type: topic")
    L.append(f"topic: {yaml_quote(topic)}")
    L.append("generated_by: ingest.py")
    L.append(f"generated_at: {yaml_quote(now)}")
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


def ensure_scaffold(vault, cfg: dict) -> int:
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
            f"title: {yaml_quote(note)}",
            "type: topic-overview",
            f"topic: {yaml_quote(topic)}",
            "generated_by: ingest.py",
            f"generated_at: {yaml_quote(now)}",
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
