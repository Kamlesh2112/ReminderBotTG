"""
Automated unit tests for SQLite database operations
"""

import os
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


if __name__ == "__main__":
    unittest.main()
