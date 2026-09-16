#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check.py —— 仓库体检：双链有效性 + 图谱结构 + 孤岛检测。

用法：
    python _tools/check.py

它回答三个问题：
    1. 有没有断链？（双链指向不存在的文件）
    2. 图谱长什么样？（每一层的节点数、边数、边在层与层之间怎么连）
    3. 有没有孤岛？（零入链的笔记——在 Obsidian 里这些点会飘在外面）

不修改任何文件，只读。可反复跑。

层映射（相对 ingest.py 的目录设计）：
    00-总览     索引层
    10-主题     知识层（主题）
    20-对话归档 会话
    30-我的记忆 / 30-人物  记忆 / 人物
    40-时间线   时间
    90-原始数据 原始数据（默认跳过）
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".obsidian", "_tools", ".workbuddy", "90-原始数据"}
BACKSLASH = chr(92)

LAYERS = {
    "00": "索引层",
    "10": "知识层",
    "20": "会话",
    "30": "记忆/人物",
    "40": "时间线",
    "90": "原始数据",
}


def layer_of(key: str) -> str:
    return LAYERS.get(key[:2], "其他")


def main() -> int:
    ap = argparse.ArgumentParser(description="仓库体检：断链 / 图谱结构 / 孤岛")
    ap.add_argument("--vault", default=None, help="vault 根目录（默认自定位）")
    args = ap.parse_args()

    root = Path(args.vault).resolve() if args.vault else VAULT
    files = [
        p
        for p in root.rglob("*.md")
        if not any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1])
        and not any(part in SKIP_DIRS for part in p.relative_to(root).parts)
    ]
    if not files:
        print("仓库里没有找到 md 文件。")
        return 1

    key_of = {p: p.relative_to(root).as_posix()[:-3] for p in files}
    by_stem: dict[str, list[Path]] = collections.defaultdict(list)
    by_path: dict[str, Path] = {}
    for p in files:
        by_stem[p.stem].append(p)
        by_path[key_of[p]] = p

    other_linkable = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*.base")
        if not any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1])
    }
    other_names = {Path(x).name for x in other_linkable}

    link_re = re.compile(r"\[\[(.*?)\]\]")
    bad: list[tuple[str, str]] = []
    inc: collections.Counter[str] = collections.Counter()
    edges: set[tuple[str, str]] = set()
    n_links = 0
    n_ambiguous = 0

    for p in files:
        txt = p.read_text(encoding="utf-8", errors="replace")
        txt = re.sub(r"```.*?```", "", txt, flags=re.S)
        targets: set[str] = set()
        for m in link_re.finditer(txt):
            n_links += 1
            raw = m.group(1)
            t = re.split(r"\|", raw)[0]
            t = t.split("#")[0].split("^")[0].strip().rstrip(BACKSLASH).strip()
            if not t:
                continue
            if t.endswith(".md"):
                t = t[:-3]

            if t in by_path:
                targets.add(t)
                continue
            if t in other_linkable or t in other_names:
                targets.add(t)
                continue

            base = t.split("/")[-1]
            if base in by_stem:
                hits = by_stem[base]
                if len(hits) > 1:
                    n_ambiguous += 1
                targets.add(key_of[hits[0]])
                continue

            bad.append((key_of[p], t))

        for t in targets:
            inc[t] += 1
            edges.add((key_of[p], t))

    print("=" * 58)
    print(f"节点 {len(files)}　边 {len(edges)}　双链 {n_links} 处")
    print("=" * 58)

    uniq_bad = sorted(set(bad))
    print(f"\n【断链】{len(uniq_bad)} 条唯一目标")
    if uniq_bad:
        for f, t in uniq_bad:
            print(f"  x {f}  ->  [[{t}]]")
        print("  （若出现在正文代码/示例里，可忽略）")
    else:
        print("  无")

    print("\n【边的分层分布】")
    c = collections.Counter((layer_of(a), layer_of(b)) for a, b in edges)
    for (a, b), n in c.most_common():
        print(f"  {a:6s} -> {b:6s}  {n:4d}")

    print("\n【入链 top10（最大的枢纽）】")
    for k, v in inc.most_common(10):
        print(f"  {v:4d}  {k}")

    iso = [p for p in files if inc.get(key_of[p], 0) == 0]
    print(f"\n【零入链（孤岛）】{len(iso)} 个")
    for p in iso:
        print(f"  - {key_of[p]}")

    if n_ambiguous:
        print(
            f"\n提示：有 {n_ambiguous} 处链接指向同名文件，"
            "本脚本按 Obsidian 的匹配规则取第一个；建议改用完整路径。"
        )

    print("\n体检完成。不修改任何文件。")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
