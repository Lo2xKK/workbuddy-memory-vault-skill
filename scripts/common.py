#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.py —— 路径常量、文本清洗与通用工具函数。

被 ingest.py / config.py / parse.py / render.py 共用。零依赖，仅标准库。
"""

from __future__ import annotations

import os
import re
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
# 文件名里不允许的字符（Windows 保留 + POSIX 分隔符 + 控制字符）
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')

_FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
_HEAD_RE = re.compile(r"^(#{1,6})\s")

# Windows 保留设备名（大小写不敏感），用作文件名会导致写盘失败
_WINDOWS_RESERVED = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


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
    """把标题转成安全的文件名片段（去非法字符 + 空格转连字符 + 截断）。"""
    s = ILLEGAL_CHARS.sub("", title or "")
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ", "-")
    if len(s) > limit:
        s = s[:limit].rstrip("-")
    if not s:
        return "未命名会话"
    if s.upper() in _WINDOWS_RESERVED:
        s = "_" + s
    return s


def yaml_quote(s: str) -> str:
    """把任意字符串安全地装进 YAML 双引号字符串（转义反斜杠与引号）。"""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def fmt_ts(ms, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """毫秒时间戳 → 可读时间；空值返回占位符。"""
    if not ms:
        return "—"
    return datetime.fromtimestamp(ms / 1000).strftime(fmt)
