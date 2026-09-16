#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config.py —— 配置读取、主题分类、项目映射与 manifest 增量台账。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from common import DEFAULT_VAULT

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
    """按 rules 顺序匹配标题 + 工作目录，先中者胜；空关键字跳过，都不中落 default。"""
    hay = f"{title}\n{cwd}".lower()
    for rule in cfg.get("rules", []):
        if not isinstance(rule, dict):
            continue
        topic = rule.get("topic")
        for kw in rule.get("match", []):
            if not kw:
                continue
            if kw.lower() in hay:
                return topic
    return cfg.get("default", "日常与运维")


def project_name(cwd: str, cfg: dict) -> str:
    """把工作目录映射到项目名（projects 表前缀最长匹配，未登记落 project_default）。"""
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
    # title_prefix_rules：对象数组 [{"prefix": ..., "title": ...}]。
    # 标题以 prefix 开头时，整体替换为固定 title（用于归一化「现在是每天早上…」等自动化标题）。
    for rule in cfg.get("title_prefix_rules", []):
        if isinstance(rule, dict):
            prefix = rule.get("prefix", "")
            if prefix and t.startswith(prefix):
                t = rule.get("title", "") or t
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
