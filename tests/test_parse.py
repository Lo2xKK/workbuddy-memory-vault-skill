#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_parse.py —— 覆盖 parse.py 的 parse_transcript：轮次分组 / 噪音剔除 / 工具轨迹。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from parse import parse_transcript


def _write(tmp_path: Path, records: list[dict]) -> Path:
    p = tmp_path / "session.jsonl"
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return p


def test_parse_groups_user_then_assistant(tmp_path):
    p = _write(
        tmp_path,
        [
            {"type": "message", "role": "user", "content": [{"text": "问题一"}], "timestamp": 1000},
            {"type": "message", "role": "assistant", "content": [{"text": "回答 A"}], "timestamp": 1100},
            {"type": "message", "role": "assistant", "content": [{"text": "回答 B"}], "timestamp": 1200},
        ],
    )
    data = parse_transcript(p)
    assert len(data["turns"]) == 1
    turn = data["turns"][0]
    assert turn["user"] == "问题一"
    assert "回答 A" in turn["assistant"]
    assert "回答 B" in turn["assistant"]


def test_parse_strips_system_reminder_from_user(tmp_path):
    p = _write(
        tmp_path,
        [
            {
                "type": "message",
                "role": "user",
                "content": [{"text": "正文\n<system-reminder>x</system-reminder>"}],
                "timestamp": 1000,
            }
        ],
    )
    data = parse_transcript(p)
    assert data["turns"][0]["user"] == "正文"


def test_parse_records_tool_calls(tmp_path):
    p = _write(
        tmp_path,
        [
            {"type": "message", "role": "user", "content": [{"text": "hi"}], "timestamp": 1000},
            {"type": "function_call", "name": "Read", "arguments": {"a": 1}, "timestamp": 1100},
        ],
    )
    data = parse_transcript(p)
    assert data["tools"] == [("Read", '{"a": 1}')]


def test_parse_counts_bad_lines(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("{not json}\n", encoding="utf-8")
    data = parse_transcript(p)
    assert data["n_bad"] == 1


def test_parse_captures_ai_title_and_cwd(tmp_path):
    p = _write(
        tmp_path,
        [
            {"type": "ai-title", "aiTitle": "自动标题", "timestamp": 500},
            {"type": "message", "role": "user", "content": [{"text": "hi"}], "timestamp": 1000, "cwd": "D:/proj"},
        ],
    )
    data = parse_transcript(p)
    assert data["ai_title"] == "自动标题"
    assert data["cwd"] == "D:/proj"
