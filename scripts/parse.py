#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse.py —— 读会话元数据、解析 jsonl 对话、提取人物字段。"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from common import WB, clean_text

# ---------------------------------------------------------------- 读会话表


def load_sessions() -> dict:
    """从 workbuddy.db 读会话元数据（只读打开，不影响正在运行的 App）。

    created_at / updated_at 兜底为 0，由调用方（ingest.main）在为空时用文件 mtime 补。
    """
    db = WB / "workbuddy.db"
    if not db.exists():
        return {}
    # as_posix() 把 Windows 反斜杠转正斜杠，避免 URI 里被当转义符
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
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
                "created_at": ca or 0,
                "updated_at": ua or 0,
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


# ---------------------------------------------------------------- 人物提取


def extract_person_fields(cfg: dict) -> dict:
    """从身份文件里提取「我」的关键字段（轻量正则，不引依赖）。

    name 以 cfg.person.name 为准（用于文件名与节点主标题）；USER.md 的 Name 存 full_name，
    不覆盖 name，避免「文件名叫 A、内容标题却叫 B」的不一致。
    """
    person = cfg.get("person", {})
    name = person.get("name", "我")
    out = {"name": name, "label": person.get("label", f"我（{name}）")}

    user = WB / "USER.md"
    if user.exists():
        txt = user.read_text(encoding="utf-8", errors="replace")
        for key, field in [("Name", "full_name"), ("City", "city"), ("Notes", "notes")]:
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
