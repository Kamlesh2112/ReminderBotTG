"""
Automated unit tests for SQLite database operations
"""

import glob
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import database
from parser import IST

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_followups.db")
        database.init_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_and_get_last_reminder(self):
        now = datetime.now(IST)
        trigger = now + timedelta(hours=2)

        rem_id = database.add_reminder(
            chat_id=12345,
            user_id=999,
            username="rutik",
            original_text="rutik 254 cb tuesday 430",
            trigger_time=trigger,
            db_path=self.db_path
        )
        self.assertGreater(rem_id, 0)

        last = database.get_last_pending_reminder(12345, db_path=self.db_path)
        self.assertIsNotNone(last)
        self.assertEqual(last["id"], rem_id)
        self.assertEqual(last["original_text"], "rutik 254 cb tuesday 430")

    def test_delete_last_pending_reminder_dell(self):
        now = datetime.now(IST)
        r1 = database.add_reminder(123, 1, "u", "first cb 10m", now + timedelta(minutes=10), db_path=self.db_path)
        r2 = database.add_reminder(123, 1, "u", "second cb 2h", now + timedelta(hours=2), db_path=self.db_path)

        # 'dell' should delete r2
        deleted = database.delete_last_pending_reminder(123, db_path=self.db_path)
        self.assertIsNotNone(deleted)
        self.assertEqual(deleted["id"], r2)

        # Now get_last_pending_reminder should be r1
        last = database.get_last_pending_reminder(123, db_path=self.db_path)
        self.assertIsNotNone(last)
        self.assertEqual(last["id"], r1)

        # 'dell' again deletes r1
        deleted2 = database.delete_last_pending_reminder(123, db_path=self.db_path)
        self.assertEqual(deleted2["id"], r1)

        # No more reminders to delete
        deleted3 = database.delete_last_pending_reminder(123, db_path=self.db_path)
        self.assertIsNone(deleted3)

    def test_get_due_reminders_and_mark_sent(self):
        now = datetime.now(timezone.utc)
        past_time = now - timedelta(seconds=10)
        future_time = now + timedelta(hours=1)

        r_past = database.add_reminder(123, 1, "u", "due cb", past_time, db_path=self.db_path)
        r_future = database.add_reminder(123, 1, "u", "future cb", future_time, db_path=self.db_path)

        due = database.get_due_reminders(now.timestamp(), db_path=self.db_path)
        due_ids = [d["id"] for d in due]
        self.assertIn(r_past, due_ids)
        self.assertNotIn(r_future, due_ids)

        database.mark_reminder_sent(r_past, db_path=self.db_path)
        due_after = database.get_due_reminders(now.timestamp(), db_path=self.db_path)
        self.assertEqual(len(due_after), 0)

    def test_migrates_old_database_schema(self):
        old_db = os.path.join(self.temp_dir.name, "old_followups.db")
        now = datetime.now(IST)

        conn = sqlite3.connect(old_db)
        try:
            conn.execute("""
                CREATE TABLE reminders (
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
                )
            """)
            conn.execute("""
                INSERT INTO reminders (
                    chat_id, user_id, username, message_id, original_text,
                    trigger_time_iso, trigger_timestamp, created_at_iso
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                123, 1, "u", None, "old cb",
                (now + timedelta(hours=1)).isoformat(),
                (now + timedelta(hours=1)).astimezone(timezone.utc).timestamp(),
                now.isoformat(),
            ))
            conn.commit()
        finally:
            conn.close()

        database.init_db(old_db)

        conn = sqlite3.connect(old_db)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(reminders)")}
        finally:
            conn.close()

        for column in ["attempts", "next_attempt_ts", "last_error", "claimed_at_ts", "is_failed"]:
            self.assertIn(column, columns)

        pending = database.get_pending_reminders_for_chat(123, db_path=old_db)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["attempts"], 0)
        self.assertEqual(pending[0]["is_failed"], 0)
        self.assertEqual(pending[0]["original_text"], "old cb")

        backups = glob.glob(old_db + ".bak-*")
        self.assertEqual(len(backups), 1)

        backup_conn = sqlite3.connect(backups[0])
        try:
            backup_row = backup_conn.execute(
                "SELECT original_text FROM reminders"
            ).fetchone()
        finally:
            backup_conn.close()
        self.assertEqual(backup_row[0], "old cb")

    def test_claim_due_reminders_prevents_duplicate_delivery(self):
        now = datetime.now(timezone.utc)
        rem_id = database.add_reminder(
            123, 1, "u", "due cb", now - timedelta(seconds=5), db_path=self.db_path
        )

        first_claim = database.claim_due_reminders(now.timestamp(), db_path=self.db_path)
        self.assertEqual([r["id"] for r in first_claim], [rem_id])

        second_claim = database.claim_due_reminders(now.timestamp(), db_path=self.db_path)
        self.assertEqual(second_claim, [])

        reclaimed = database.claim_due_reminders(
            now.timestamp() + 121, claim_ttl_seconds=120, db_path=self.db_path
        )
        self.assertEqual([r["id"] for r in reclaimed], [rem_id])

    def test_failed_reminder_retries_then_is_dropped(self):
        now = datetime.now(timezone.utc)
        rem_id = database.add_reminder(
            123, 1, "u", "due cb", now - timedelta(seconds=5), db_path=self.db_path
        )

        database.claim_due_reminders(now.timestamp(), db_path=self.db_path)
        database.mark_reminder_failed(
            rem_id, "network down", retry_delay_seconds=10, db_path=self.db_path
        )

        self.assertEqual(database.get_due_reminders(now.timestamp(), db_path=self.db_path), [])
        self.assertEqual(
            [r["id"] for r in database.get_due_reminders(now.timestamp() + 11, db_path=self.db_path)],
            [rem_id],
        )

        database.mark_reminder_failed(rem_id, "bot blocked", permanent=True, db_path=self.db_path)
        self.assertEqual(
            database.get_due_reminders(now.timestamp() + 999, db_path=self.db_path), []
        )
        self.assertEqual(database.get_pending_reminders_for_chat(123, db_path=self.db_path), [])

    def test_reschedule_reminder(self):
        now = datetime.now(IST)
        rem_id = database.add_reminder(
            123, 1, "u", "due cb", now + timedelta(minutes=5), db_path=self.db_path
        )
        new_time = now + timedelta(hours=2)

        updated = database.reschedule_reminder(
            rem_id, 123, new_time, db_path=self.db_path
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated["attempts"], 0)
        self.assertEqual(
            updated["trigger_time_iso"], new_time.astimezone(IST).isoformat()
        )

        self.assertIsNone(
            database.reschedule_reminder(rem_id, 999, new_time, db_path=self.db_path)
        )


if __name__ == "__main__":
    unittest.main()
