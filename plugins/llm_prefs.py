# -*- coding: utf-8 -*-
"""本地 SQLite 偏好库：收集每个会话（群/私聊）的聊天偏好。

- set_style / get_styles：显式偏好（用户说「少说token」「多动作描写」等时写入）；
- record_chat_stats / get_stats：隐式统计（用户自己是否提 token/干饭主题）；
- style_directive：生成注入给 AI 的偏好指令，让 AI 不再三句不离 token、不乱写动作描写。
"""
import re
import sqlite3
import threading
import time
from pathlib import Path

DB_FILE = Path(__file__).resolve().parent / "llm_user_prefs.db"
_LOCK = threading.Lock()

TOKEN_THEME_PATTERN = re.compile(r"token|投喂|干饭|吃饭|零食|小鱼零食", re.IGNORECASE)


def _connect():
    conn = sqlite3.connect(str(DB_FILE))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chat_prefs ("
        "key TEXT PRIMARY KEY, token_style TEXT, action_style TEXT, updated_at REAL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chat_stats ("
        "key TEXT PRIMARY KEY, user_msgs INTEGER DEFAULT 0, "
        "user_token_mentions INTEGER DEFAULT 0, ai_token_mentions INTEGER DEFAULT 0, "
        "updated_at REAL)"
    )
    conn.commit()
    return conn


def set_style(key, field, value):
    column = "token_style" if field == "token" else "action_style"
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO chat_prefs (key, token_style, action_style, updated_at) "
                "VALUES (?, NULL, NULL, ?) "
                "ON CONFLICT(key) DO UPDATE SET updated_at = excluded.updated_at",
                (key, time.time()),
            )
            conn.execute(
                f"UPDATE chat_prefs SET {column} = ?, updated_at = ? WHERE key = ?",
                (value, time.time(), key),
            )
            conn.commit()
        finally:
            conn.close()


def get_styles(key):
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT token_style, action_style FROM chat_prefs WHERE key = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None, None
    return row[0], row[1]


def record_chat_stats(key, user_text, ai_text):
    with _LOCK:
        conn = _connect()
        try:
            user_mention = 1 if TOKEN_THEME_PATTERN.search(user_text or "") else 0
            ai_mention = 1 if TOKEN_THEME_PATTERN.search(ai_text or "") else 0
            conn.execute(
                "INSERT INTO chat_stats (key, user_msgs, user_token_mentions, ai_token_mentions, updated_at) "
                "VALUES (?, 1, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "user_msgs = user_msgs + 1, "
                "user_token_mentions = user_token_mentions + excluded.user_token_mentions, "
                "ai_token_mentions = ai_token_mentions + excluded.ai_token_mentions, "
                "updated_at = excluded.updated_at",
                (key, user_mention, ai_mention, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def get_stats(key):
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT user_msgs, user_token_mentions, ai_token_mentions "
                "FROM chat_stats WHERE key = ?",
                (key,),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return {"user_msgs": 0, "user_token_mentions": 0, "ai_token_mentions": 0}
    return {"user_msgs": row[0], "user_token_mentions": row[1], "ai_token_mentions": row[2]}


def style_directive(key):
    """生成注入给 AI 的偏好指令；两个维度都有默认档，保证不跑偏。"""
    token_style, action_style = get_styles(key)
    stats = get_stats(key)

    # 自动档：用户自己从没提过 token 主题、且已经聊了不少 → 自动调低 token 梗
    if token_style is None and stats["user_token_mentions"] == 0 and stats["user_msgs"] >= 5:
        token_style = "low"

    token_part = {
        "low": "少提 token/干饭梗（除非用户自己先提）",
        "high": "用户喜欢，可以适当多提 token/干饭梗",
    }.get(token_style, "偶尔提一下 token/干饭梗就好，不要句句都提")

    action_part = {
        "low": "不要写动作描写，直接说话",
        "high": "可以适度加动作描写/小剧场",
    }.get(action_style, "几乎不要写动作描写（如 *晃了晃尾巴*、凑近看这类），直接说话")

    return f"token/干饭梗：{token_part}；动作描写：{action_part}。"


def style_summary(key):
    token_style, action_style = get_styles(key)
    stats = get_stats(key)
    token_label = {"low": "少提", "high": "多提"}.get(token_style, "默认（偶尔）")
    action_label = {"low": "不用", "high": "可以用"}.get(action_style, "默认（几乎不用）")
    return token_label, action_label, stats


def checkin(key):
    """签到：返回 (连续天数, 是否今天首次签到)。"""
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    today = _date.today().isoformat()
    yesterday = (_date.today() - _timedelta(days=1)).isoformat()
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS checkins ("
                "key TEXT PRIMARY KEY, last_date TEXT, streak INTEGER DEFAULT 0)"
            )
            row = conn.execute(
                "SELECT last_date, streak FROM checkins WHERE key = ?", (key,)
            ).fetchone()
            if row and row[0] == today:
                return row[1] or 0, False
            new_streak = (row[1] or 0) + 1 if (row and row[0] == yesterday) else 1
            conn.execute(
                "INSERT INTO checkins (key, last_date, streak) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "last_date = excluded.last_date, streak = excluded.streak",
                (key, today, new_streak),
            )
            conn.commit()
            return new_streak, True
        finally:
            conn.close()


def _group_state(key):
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS group_state ("
                "key TEXT PRIMARY KEY, silenced_until REAL DEFAULT 0, greeted_at REAL DEFAULT 0)"
            )
            row = conn.execute(
                "SELECT silenced_until, greeted_at FROM group_state WHERE key = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return {"silenced_until": 0.0, "greeted_at": 0.0}
    return {"silenced_until": row[0] or 0.0, "greeted_at": row[1] or 0.0}


def _set_group_state(key, silenced_until=None, greeted_at=None):
    state = _group_state(key)
    silenced_until = state["silenced_until"] if silenced_until is None else silenced_until
    greeted_at = state["greeted_at"] if greeted_at is None else greeted_at
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO group_state (key, silenced_until, greeted_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "silenced_until = excluded.silenced_until, greeted_at = excluded.greeted_at",
                (key, silenced_until, greeted_at),
            )
            conn.commit()
        finally:
            conn.close()


def silence_group(key, seconds):
    """让群里的机器人闭嘴 seconds 秒。"""
    _set_group_state(key, silenced_until=time.time() + max(1.0, float(seconds)))


def unsilence_group(key):
    _set_group_state(key, silenced_until=0.0)


def is_group_silenced(key):
    state = _group_state(key)
    return state["silenced_until"] > time.time()


def mark_group_greeted(key):
    _set_group_state(key, greeted_at=time.time())


def group_greet_due(key, cooldown_seconds=7 * 86400):
    """首次进群，或距上次打招呼超过 cooldown 秒，需要再打招呼。"""
    state = _group_state(key)
    if state["greeted_at"] <= 0:
        return True
    return time.time() - state["greeted_at"] > cooldown_seconds


def group_state_keys():
    """返回本地库记录过的群 key（进群问候过的群）。"""
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS group_state ("
                "key TEXT PRIMARY KEY, silenced_until REAL DEFAULT 0, greeted_at REAL DEFAULT 0)"
            )
            rows = conn.execute("SELECT key FROM group_state").fetchall()
        finally:
            conn.close()
    return [row[0] for row in rows]


def announce_due(key, cooldown_seconds):
    """距上次对该会话发公告是否已超过 cooldown 秒（首次必然 True）。"""
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS announce_log (key TEXT PRIMARY KEY, ts REAL)")
            row = conn.execute("SELECT ts FROM announce_log WHERE key = ?", (key,)).fetchone()
        finally:
            conn.close()
    if not row:
        return True
    return time.time() - (row[0] or 0) > cooldown_seconds


def mark_announced(key):
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS announce_log (key TEXT PRIMARY KEY, ts REAL)")
            conn.execute(
                "INSERT INTO announce_log (key, ts) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET ts = excluded.ts",
                (key, time.time()),
            )
            conn.commit()
        finally:
            conn.close()
