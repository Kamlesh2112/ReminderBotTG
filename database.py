"""
database.py - SQLite storage engine for Telegram followup reminders.
Guarantees persistence across bot restarts and zero lost reminders.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Generator
from zoneinfo import ZoneInfo

logger = logging.getLogger("ReminderDatabase")

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEFAULT_DB_PATH = os.path.abspath(
    os.getenv("REMINDER_DB_PATH", "").strip() or os.path.join(DEFAULT_DB_DIR, "followups.db")
)


@contextlib.contextmanager
def db_session(db_path: str = DEFAULT_DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
    finally:
        conn.close()


def _backup_before_migration(conn: sqlite3.Connection, db_path: str) -> str:
    """Creates a consistent SQLite backup before changing an existing schema."""
    timestamp = datetime.now(IST).strftime("%Y%m%d-%H%M%S-%f")
    backup_path = f"{db_path}.bak-{timestamp}"
    backup_conn = sqlite3.connect(backup_path)
    try:
        conn.backup(backup_conn)
    finally:
        backup_conn.close()
    logger.info(f"Database backup created before migration: {backup_path}")
    return backup_path


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initializes the database schema and indexes without deleting existing reminders."""
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
                sent_at_iso TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_ts REAL NOT NULL DEFAULT 0,
                last_error TEXT,
                claimed_at_ts REAL,
                is_failed INTEGER NOT NULL DEFAULT 0
            );
        """)

        # Migrate databases created by older versions of the bot.
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(reminders)").fetchall()
        }
        migrations = {
            "attempts": "ALTER TABLE reminders ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
            "next_attempt_ts": "ALTER TABLE reminders ADD COLUMN next_attempt_ts REAL NOT NULL DEFAULT 0",
            "last_error": "ALTER TABLE reminders ADD COLUMN last_error TEXT",
            "claimed_at_ts": "ALTER TABLE reminders ADD COLUMN claimed_at_ts REAL",
            "is_failed": "ALTER TABLE reminders ADD COLUMN is_failed INTEGER NOT NULL DEFAULT 0",
        }
        missing_columns = [column for column in migrations if column not in existing_columns]
        if missing_columns:
            _backup_before_migration(conn, db_path)
            for column in missing_columns:
                conn.execute(migrations[column])

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_reminders 
            ON reminders (is_sent, is_deleted, trigger_timestamp);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_pending 
            ON reminders (chat_id, is_sent, is_deleted, id DESC);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_due_reminders
            ON reminders (is_sent, is_deleted, is_failed, next_attempt_ts, trigger_timestamp);
        """)
        conn.commit()
        logger.info(f"Database ready at {os.path.abspath(db_path)}")


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
            WHERE chat_id = ? AND is_sent = 0 AND is_deleted = 0 AND is_failed = 0
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
            WHERE chat_id = ? AND is_sent = 0 AND is_deleted = 0 AND is_failed = 0
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
            WHERE id = ? AND chat_id = ? AND is_sent = 0 AND is_deleted = 0 AND is_failed = 0
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
            WHERE chat_id = ? AND is_sent = 0 AND is_deleted = 0 AND is_failed = 0
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
            WHERE is_sent = 0 AND is_deleted = 0 AND is_failed = 0
              AND trigger_timestamp <= ? AND next_attempt_ts <= ?
            ORDER BY trigger_timestamp ASC
        """, (now_ts, now_ts))
        return [dict(r) for r in cur.fetchall()]


def claim_due_reminders(
    now_ts: float | None = None,
    limit: int = 50,
    claim_ttl_seconds: float = 120.0,
    db_path: str = DEFAULT_DB_PATH
) -> list[dict[str, Any]]:
    """
    Atomically claims due reminders so the same reminder is never delivered twice.
    Stale claims are automatically reclaimable after claim_ttl_seconds.
    """
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()

    with db_session(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute("""
            SELECT * FROM reminders
            WHERE is_sent = 0 AND is_deleted = 0 AND is_failed = 0
              AND trigger_timestamp <= ?
              AND next_attempt_ts <= ?
              AND (claimed_at_ts IS NULL OR claimed_at_ts < ?)
            ORDER BY trigger_timestamp ASC
            LIMIT ?
        """, (now_ts, now_ts, now_ts - claim_ttl_seconds, limit))
        rows = [dict(r) for r in cur.fetchall()]

        if rows:
            conn.executemany(
                "UPDATE reminders SET claimed_at_ts = ? WHERE id = ?",
                [(now_ts, row["id"]) for row in rows]
            )
        conn.commit()
        return rows


def mark_reminder_sent(reminder_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    """Marks a reminder as sent and clears any claim/retry state."""
    now_ist = datetime.now(IST).isoformat()
    with db_session(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE reminders
            SET is_sent = 1, sent_at_iso = ?, claimed_at_ts = NULL, last_error = NULL
            WHERE id = ?
        """, (now_ist, reminder_id))
        conn.commit()


def mark_reminder_failed(
    reminder_id: int,
    error: str,
    retry_delay_seconds: float | None = None,
    permanent: bool = False,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Records a delivery failure. Transient errors are retried with a delay;
    permanent errors are removed from the pending queue.
    """
    now_utc_ts = datetime.now(timezone.utc).timestamp()
    safe_error = (error or "")[:500]

    with db_session(db_path) as conn:
        if permanent:
            conn.execute("""
                UPDATE reminders
                SET is_failed = 1, claimed_at_ts = NULL,
                    attempts = attempts + 1, last_error = ?
                WHERE id = ?
            """, (safe_error, reminder_id))
        else:
            delay = max(1.0, float(retry_delay_seconds if retry_delay_seconds is not None else 5))
            conn.execute("""
                UPDATE reminders
                SET claimed_at_ts = NULL, attempts = attempts + 1,
                    next_attempt_ts = ?, last_error = ?
                WHERE id = ?
            """, (now_utc_ts + delay, safe_error, reminder_id))
        conn.commit()


def reschedule_reminder(
    reminder_id: int,
    chat_id: int,
    new_trigger_time: datetime,
    db_path: str = DEFAULT_DB_PATH
) -> dict[str, Any] | None:
    """Reschedules a pending reminder and resets its retry state (used by /snooze)."""
    trigger_ist = new_trigger_time.astimezone(IST)
    trigger_ts = new_trigger_time.astimezone(timezone.utc).timestamp()

    with db_session(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE reminders
            SET trigger_time_iso = ?, trigger_timestamp = ?,
                attempts = 0, next_attempt_ts = 0, claimed_at_ts = NULL,
                last_error = NULL, is_failed = 0
            WHERE id = ? AND chat_id = ? AND is_sent = 0 AND is_deleted = 0
        """, (trigger_ist.isoformat(), trigger_ts, reminder_id, chat_id))
        if cur.rowcount == 0:
            conn.commit()
            return None

        row = cur.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        conn.commit()
        return dict(row) if row else None
