#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_config.py —— 覆盖 config.py 的纯函数：分类 / 项目映射 / 标题解析 / manifest 增量。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from config import classify, is_changed, project_name, resolve_title


CFG = {
    "rules": [
        {"topic": "RoboMaster", "match": ["robomaster", "rm-rules"]},
        {"topic": "学业", "match": ["matlab", "考研"]},
    ],
    "default": "日常与运维",
    "projects": {
        "d:/projects/alpha": "Alpha 项目",
        "d:/projects": "工作区",
    },
    "project_default": "临时工作区",
    "title_overrides": {"abc123": "人工标题"},
    "title_prefix_rules": [{"prefix": "【学习】", "title": "学习笔记"}],
}


def test_classify_matches_by_title():
    assert classify("RoboMaster 云台调参", "", CFG) == "RoboMaster"


def test_classify_matches_by_cwd():
    assert classify("随便聊聊", "d:/project/rm-rules-tool", CFG) == "RoboMaster"


def test_classify_skips_empty_keyword():
    cfg = {"rules": [{"topic": "X", "match": ["", "命中词"]}], "default": "兜底"}
    assert classify("命中词", "", cfg) == "X"
    assert classify("无关", "", cfg) == "兜底"


def test_classify_falls_back_to_default():
    assert classify("无关标题", "", CFG) == "日常与运维"


def test_classify_first_match_wins():
    assert classify("matlab 作业", "", CFG) == "学业"


def test_project_name_exact_match():
    assert project_name("D:/projects/alpha", CFG) == "Alpha 项目"


def test_project_name_longest_prefix_wins():
    assert project_name("D:/projects/alpha/sub", CFG) == "Alpha 项目"
    assert project_name("D:/projects/other", CFG) == "工作区"


def test_project_name_unlisted_falls_back():
    assert project_name("Z:/unknown", CFG) == "临时工作区"


def test_resolve_title_collapses_whitespace():
    assert resolve_title("s1", " 多  空格  标题 ", CFG) == "多 空格 标题"


def test_resolve_title_applies_prefix_rule():
    assert resolve_title("s1", "【学习】高数", CFG) == "学习笔记"


def test_resolve_title_prefix_rule_normalizes_automation_title():
    cfg = {
        "title_prefix_rules": [{"prefix": "现在是每天早上", "title": "每日晨报（定时任务执行）"}],
        "title_overrides": {},
    }
    assert resolve_title("s", "现在是每天早上8点发送晨报", cfg) == "每日晨报（定时任务执行）"


def test_resolve_title_applies_override():
    assert resolve_title("abc123", "原始标题", CFG) == "人工标题"


def test_resolve_title_truncates_long():
    out = resolve_title("s1", "超长标题" * 20, CFG, limit=10)
    assert len(out) <= 11  # 10 + 省略号


def test_resolve_title_empty_falls_back():
    assert resolve_title("s1", "", CFG) == "未命名会话"


def test_is_changed_new_sid():
    assert is_changed("new-sid", 100, {}) is True


def test_is_changed_same_mtime():
    manifest = {"sid": {"mtime": 100}}
    assert is_changed("sid", 100, manifest) is False


def test_is_changed_different_mtime():
    manifest = {"sid": {"mtime": 100}}
    assert is_changed("sid", 200, manifest) is True
