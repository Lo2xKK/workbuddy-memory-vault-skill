#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_common.py —— 覆盖 common.py 的纯函数：清洗 / 标题降级 / 文件名 / YAML 引用 / 时间。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from common import clean_text, demote_headings, fmt_ts, slugify, yaml_quote


def test_clean_text_strips_system_reminder():
    raw = "正文前\n<system-reminder data-role=\"x\">\n内部注入\n</system-reminder>\n正文后"
    out = clean_text(raw)
    assert "内部注入" not in out
    assert "正文前" in out
    assert "正文后" in out


def test_clean_text_handles_empty_and_none():
    assert clean_text("") == ""
    assert clean_text("   \n  ") == ""


def test_clean_text_normalizes_newlines():
    out = clean_text("a\r\nb\rc")
    assert "\r" not in out


def test_demote_headings_downgrades_one_level():
    text = "## 二级标题\n正文"
    out = demote_headings(text)
    assert "### 二级标题" in out


def test_demote_headings_keeps_h6_unchanged():
    text = "###### 六级标题"
    out = demote_headings(text)
    assert out.startswith("###### ")


def test_demote_headings_skips_code_fence():
    text = "```\n# 不是标题\n```\n# 真标题"
    out = demote_headings(text)
    assert "```\n# 不是标题\n```" in out
    assert "## 真标题" in out


def test_slugify_removes_illegal_chars_and_spaces():
    assert slugify("云台 调参: PID") == "云台-调参-PID"


def test_slugify_truncates_to_limit():
    out = slugify("这是一个非常非常非常长的标题需要被截断处理测试", limit=10)
    assert len(out) <= 10


def test_slugify_empty_falls_back():
    assert slugify("") == "未命名会话"
    assert slugify("###") == "未命名会话"


def test_slugify_windows_reserved_name():
    assert slugify("CON") == "_CON"


def test_yaml_quote_escapes_quotes_and_backslash():
    assert yaml_quote('a"b') == '"a\\"b"'
    assert yaml_quote("a\\b") == '"a\\\\b"'


def test_fmt_ts_empty_returns_dash():
    assert fmt_ts(None) == "—"
    assert fmt_ts(0) == "—"


def test_fmt_ts_formats_milliseconds():
    out = fmt_ts(1700000000000, "%Y-%m-%d")
    import datetime
    assert datetime.datetime.strptime(out, "%Y-%m-%d")
