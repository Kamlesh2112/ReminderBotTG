"""
database.py - SQLite storage engine for Telegram followup reminders.
Guarantees persistence across bot restarts and zero lost reminders.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Generator
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEFAULT_DB_PATH = os.path.join(DEFAULT_DB_DIR, "followups.db")


@contextlib.contextmanager
def db_session(db_path: str = DEFAULT_DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initializes the database schema and indexes."""
    with db_session(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                message_id INTEGER,
                original_text TEXT NOT NULL,
                trigger_time_iso TEXT NOT NULL,
                trigger_timestamp REAL NOT NULL,
                created_at_iso TEXT NOT NULL,
                is_sent INTEGER NOT NULL DEFAULT 0,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                sent_at_iso TEXT
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_reminders 
            ON reminders (is_sent, is_deleted, trigger_timestamp);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_pending 
            ON reminders (chat_id, is_sent, is_deleted, id DESC);
        """)
        conn.commit()


def add_reminder(
    chat_id: int,
    user_id: int,
    username: str | None,
    original_text: str,
    trigger_time: datetime,
    message_id: int | None = None,
    db_path: str = DEFAULT_DB_PATH
) -> int:
    """
    Inserts a new followup reminder into the database.
    Returns the generated reminder ID.
    """
    now_ist = datetime.now(IST)
    trigger_ist = trigger_time.astimezone(IST)
    trigger_ts = trigger_time.astimezone(timezone.utc).timestamp()

    with db_session(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO reminders (
                chat_id, user_id, username, message_id,
                original_text, trigger_time_iso, trigger_timestamp,
                created_at_iso, is_sent, is_deleted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """, (
            chat_id,
            user_id,
            username,
            message_id,
            original_text,
            trigger_ist.isoformat(),
            trigger_ts,
            now_ist.isoformat()
        ))
        conn.commit()
        return cur.lastrowid


def get_last_pending_reminder(chat_id: int, db_path: str = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    """Returns the most recent active reminder for the specified chat."""
    with db_session(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM reminders
            WHERE chat_id = ? AND is_sent = 0 AND is_deleted = 0
            ORDER BY id DESC
            LIMIT 1
        """, (chat_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        return None


def delete_last_pending_reminder(chat_id: int, db_path: str = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    """
    Deletes (marks is_deleted=1) the most recent active reminder for the chat.
    Returns the deleted reminder details or None if no active reminder was found.
    """
    with db_session(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM reminders
            WHERE chat_id = ? AND is_sent = 0 AND is_deleted = 0
            ORDER BY id DESC
            LIMIT 1
        """, (chat_id,))
        row = cur.fetchone()
        if not row:
            return None

        reminder = dict(row)
        cur.execute("""
            UPDATE reminders
            SET is_deleted = 1
            WHERE id = ?
        """, (reminder["id"],))
        conn.commit()
        return reminder


def delete_reminder_by_id(reminder_id: int, chat_id: int, db_path: str = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    """
    Deletes a specific active reminder by its ID and chat_id.
    """
    with db_session(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM reminders
            WHERE id = ? AND chat_id = ? AND is_sent = 0 AND is_deleted = 0
        """, (reminder_id, chat_id))
        row = cur.fetchone()
        if not row:
            return None

        reminder = dict(row)
        cur.execute("UPDATE reminders SET is_deleted = 1 WHERE id = ?", (reminder_id,))
        conn.commit()
        return reminder


def get_pending_reminders_for_chat(chat_id: int, db_path: str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Returns all pending active reminders for this chat, ordered by due time."""
    with db_session(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM reminders
            WHERE chat_id = ? AND is_sent = 0 AND is_deleted = 0
            ORDER BY trigger_timestamp ASC
        """, (chat_id,))
        return [dict(r) for r in cur.fetchall()]


def get_due_reminders(now_ts: float | None = None, db_path: str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Returns all reminders that are due and haven't been sent or deleted yet."""
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()

    with db_session(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM reminders
            WHERE is_sent = 0 AND is_deleted = 0 AND trigger_timestamp <= ?
            ORDER BY trigger_timestamp ASC
        """, (now_ts,))
        return [dict(r) for r in cur.fetchall()]


def mark_reminder_sent(reminder_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    """Marks a reminder as sent with timestamp."""
    now_ist = datetime.now(IST).isoformat()
    with db_session(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE reminders
            SET is_sent = 1, sent_at_iso = ?
            WHERE id = ?
        """, (now_ist, reminder_id))
        conn.commit()
