#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ingest.py —— 把 WorkBuddy 的记忆与历史对话，编译成 Obsidian 图谱记忆库。

主入口：负责编排（读配置 → 读会话 → 增量过滤 → 解析 → 渲染 → 写记忆副本 → 备份原始数据）。
解析在 parse.py，渲染在 render.py，配置与分类在 config.py，通用工具在 common.py。

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

数据源（只读，不修改 ~/.workbuddy 下任何文件）。
部署：把 scripts/ 与 config/ 的内容一并复制到 <vault>/_tools/，脚本用 __file__ 自定位 vault 根。
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from common import (
    ARCHIVE_DIR,
    DEFAULT_VAULT,
    ILLEGAL_CHARS,
    MEMORY_DIR,
    MEMORY_ROOTS,
    PERSON_DIR,
    RAW_DIR,
    TIMELINE_DIR,
    WB,
    slugify,
    yaml_quote,
)
from config import (
    classify,
    is_changed,
    load_config,
    load_manifest,
    project_name,
    resolve_title,
    save_manifest,
)
from parse import load_sessions, parse_transcript
from render import (
    ensure_scaffold,
    render_bases,
    render_conversation,
    render_index_page,
    render_person,
    render_timeline_month,
    render_topic_aggregate,
)


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
        f"generated_at: {yaml_quote(datetime.now().strftime('%Y-%m-%d %H:%M'))}\n"
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
            f"project: {yaml_quote(project)}\n"
            f"source: {yaml_quote(source)}\n"
            "generated_by: ingest.py\n"
            f"generated_at: {yaml_quote(datetime.now().strftime('%Y-%m-%d %H:%M'))}\n"
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
            folder = ILLEGAL_CHARS.sub("-", mapped).strip("-") or "未分类"
            outdir = proj_root / folder
            outdir.mkdir(parents=True, exist_ok=True)
            tag = ILLEGAL_CHARS.sub("-", proj_path.name).strip("-") if unlisted else ""
            multi = len(files) > 1
            for f in files:
                stem = ILLEGAL_CHARS.sub("-", f.stem).strip("-") or "未命名"
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


def copy_raw_files(vault: Path, entries: list[tuple[Path, str]]) -> tuple[int, int]:
    """把原始 jsonl 备份到 90-原始数据/，返回 (成功数, 失败数)。"""
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
    failed = 0
    for src, sid in entries:
        dst = raw_dir / f"{sid}.jsonl"
        try:
            shutil.copy2(src, dst)
            n += 1
        except OSError as e:
            failed += 1
            print(f"  ⚠ 备份失败 {src.name}: {e}")
    return n, failed


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
        # 会话表里时间戳缺失时，用文件 mtime 兜底，避免 datetime.fromtimestamp 抛异常
        if not meta.get("created_at"):
            meta["created_at"] = int(f.stat().st_mtime * 1000)
        if not meta.get("updated_at"):
            meta["updated_at"] = meta["created_at"]
        mtime = int(f.stat().st_mtime * 1000)
        entries.append((f, meta, mtime))

    if not entries:
        print("没有匹配的会话。")
        return 0

    # 增量过滤
    to_process: list[tuple[Path, dict, int]] = []
    skipped = 0
    for f, meta, mtime in entries:
        if args.full or is_changed(meta["id"], mtime, manifest):
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
            # render_conversation 只写 timeline 字段，这里也只认它
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
    n_raw_fail = 0
    if not args.no_raw:
        n_raw, n_raw_fail = copy_raw_files(vault, [(f, m["id"]) for f, m, _ in to_process])

    save_manifest(vault, manifest)

    print()
    print(f"对话归档：{written} 个（跳过空会话/未变更共 {skipped} 个）")
    print(f"时间线节点：{n_timeline} 个月")
    print(f"人物节点：{n_person} 个")
    print(f"主题聚合页：{len(by_topic)} 个")
    print(f"骨架文件：{n_scaffold} 个")
    print(f"记忆副本：{len(made_mem)} 个文件")
    if n_raw or n_raw_fail:
        print(f"原始备份：{n_raw} 个 jsonl -> 90-原始数据/" + (f"（{n_raw_fail} 个失败）" if n_raw_fail else ""))
    print(f"索引已更新：20-对话归档/对话索引.md + 对话索引.base")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
