"""
Automated unit tests for parser, daytime logic, typo tolerance, and date parsing
"""

import base64
import json
import unittest
import zlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from parser import (
    IST,
    decode_restore_payload,
    format_relative_delta,
    parse_duration,
    parse_followup_command,
    parse_time_component,
    resolve_hour,
)

class TestReminderParser(unittest.TestCase):
    def setUp(self):
        # Saturday, Oct 17, 2026, 2:00 PM IST (14:00)
        self.test_now = datetime(2026, 10, 17, 14, 0, 0, tzinfo=IST)

    def test_daytime_hours_rule(self):
        """
        Verify that daytime window 9 AM to 8 PM works for single and double digits:
        1..8 -> 13..20 (1 PM to 8 PM)
        9..11 -> 9..11 (9 AM to 11 AM)
        12 -> 12 (12 PM noon)
        """
        self.assertEqual(resolve_hour(1), (13, 0)) # 1 PM
        self.assertEqual(resolve_hour(4), (16, 0)) # 4 PM
        self.assertEqual(resolve_hour(8), (20, 0)) # 8 PM
        self.assertEqual(resolve_hour(9), (9, 0))   # 9 AM
        self.assertEqual(resolve_hour(10), (10, 0)) # 10 AM
        self.assertEqual(resolve_hour(11), (11, 0)) # 11 AM
        self.assertEqual(resolve_hour(12), (12, 0)) # 12 PM noon

    def test_compact_times(self):
        """
        Verify compact times like 430 -> 16:30, 1130 -> 11:30, 4.30 -> 16:30
        """
        self.assertEqual(parse_time_component("430"), (16, 30))
        self.assertEqual(parse_time_component("1130"), (11, 30))
        self.assertEqual(parse_time_component("4.30"), (16, 30))
        self.assertEqual(parse_time_component("4:30"), (16, 30))
        self.assertEqual(parse_time_component("1015"), (10, 15))
        self.assertEqual(parse_time_component("815"), (20, 15))

    def test_prompt_examples(self):
        """Test the original core examples from the user prompt."""
        # 'xx cb 2 days' -> sends whole text after 2 days at same time
        res = parse_followup_command("xx cb 2 days", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-19 14:00")

        # 'rajesh 937 cb monday' -> monday 11 am
        res = parse_followup_command("rajesh 937 cb monday", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-19 11:00")

        # 'rutik 254 cb tuesday 430' -> tuesday at 4:30 PM (16:30)
        res = parse_followup_command("rutik 254 cb tuesday 430", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-20 16:30")

        # 'cb 10m' -> 10 minutes later
        res = parse_followup_command("cb 10m", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-17 14:10")

        # 'cb 2hr' and 'cb 2h' -> 2 hours later
        res1 = parse_followup_command("cb 2hr", self.test_now)
        res2 = parse_followup_command("cb 2h", self.test_now)
        self.assertEqual(res1["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-17 16:00")
        self.assertEqual(res2["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-17 16:00")

    def test_date_parsing(self):
        """Test calendar date parsing such as 'cb 9 nov' and 'cb 9 nov 430'."""
        # 'cb 9 nov' -> 9 November 2026 at 11:00 AM (default)
        res = parse_followup_command("cb 9 nov", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-11-09 11:00")

        # 'cb 9th nov 430' -> 9 November 2026 at 4:30 PM (16:30)
        res = parse_followup_command("cb 9th nov 430", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-11-09 16:30")

        # 'deal close cb nov 9 5' -> 9 November 2026 at 5:00 PM (17:00)
        res = parse_followup_command("deal close cb nov 9 5", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-11-09 17:00")

    def test_spelling_mistakes_and_typos(self):
        """Test typo tolerance in weekdays, months, units, and relative words."""
        # Weekday typos
        res = parse_followup_command("cb mondy", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-19 11:00")

        res = parse_followup_command("cb tuseday 430", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-20 16:30")

        res = parse_followup_command("cb wensday 11", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-21 11:00")

        res = parse_followup_command("cb thrusday 4", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-22 16:00")

        # Month typos
        res = parse_followup_command("cb 9 novmber", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-11-09 11:00")

        # Relative word typos
        res = parse_followup_command("cb tomorow 5", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-18 17:00")

        # Unit typos
        res = parse_followup_command("cb 2 dys", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-19 14:00")

        res = parse_followup_command("cb 10 minuts", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-17 14:10")

        res = parse_followup_command("cb 2 hourse", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-17 16:00")

    def test_seconds_support(self):
        """Test relative seconds support like 'cb 10 sec' and 'cb 30s'."""
        res = parse_followup_command("cb 10 sec", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M:%S"), "2026-10-17 14:00:10")

        res_s = parse_followup_command("cb 30s", self.test_now)
        self.assertIsNotNone(res_s)
        self.assertEqual(res_s["trigger_time"].strftime("%Y-%m-%d %H:%M:%S"), "2026-10-17 14:00:30")

    def test_same_time_support(self):
        """Test 'same time' support like 'cb tmr same time'."""
        res = parse_followup_command("cb tmr same time", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-18 14:00")

    def test_new_timer_options(self):
        """Test alternate keywords, day periods, next week, and combined timers."""
        cases = [
            ("remind me in 10m", "2026-10-17 14:10"),
            ("timer 1h30m", "2026-10-17 15:30"),
            ("alert 2 hours", "2026-10-17 16:00"),
            ("cb half an hour", "2026-10-17 14:30"),
            ("cb a couple of hours", "2026-10-17 16:00"),
            ("cb in 2 days at 5pm", "2026-10-19 17:00"),
            ("cb 2 days 9am", "2026-10-19 09:00"),
            ("cb next week", "2026-10-24 14:00"),
            ("cb in 1 week evening", "2026-10-24 18:00"),
            ("cb tomorrow evening", "2026-10-18 18:00"),
            ("cb monday morning", "2026-10-19 10:00"),
            ("cb tonight", "2026-10-17 20:00"),
            ("cb eod", "2026-10-17 18:00"),
            ("cb friday same time", "2026-10-23 14:00"),
            ("cb 9 nov same time", "2026-11-09 14:00"),
            ("set a timer for 15m", "2026-10-17 14:15"),
            ("set an alarm for 30m", "2026-10-17 14:30"),
            ("set a reminder for 45m", "2026-10-17 14:45"),
        ]

        for text, expected in cases:
            with self.subTest(text=text):
                res = parse_followup_command(text, self.test_now)
                self.assertIsNotNone(res, text)
                self.assertEqual(
                    res["trigger_time"].strftime("%Y-%m-%d %H:%M"), expected
                )

    def test_weekday_with_time_is_not_month_date(self):
        """'monday 11' means Monday at 11 AM, not 11 May."""
        now = datetime(2026, 10, 24, 0, 41, tzinfo=IST)
        text = "Puneet Manon  AGILE RAYS LLP  7483007175  cb monday 11"
        res = parse_followup_command(text, now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-26 11:00")
        self.assertEqual(res["remainder"], "")

        date_res = parse_followup_command("cb may 11", now)
        self.assertIsNotNone(date_res)
        self.assertEqual(date_res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2027-05-11 11:00")

    def test_alias_keywords_do_not_fire_mid_sentence(self):
        """'alert'/'timer' only act as triggers at the start of a message."""
        self.assertIsNone(parse_followup_command("security alert tomorrow", self.test_now))
        res = parse_followup_command("alert tomorrow", self.test_now)
        self.assertIsNotNone(res)
        self.assertEqual(res["trigger_time"].strftime("%Y-%m-%d %H:%M"), "2026-10-18 11:00")

    def test_parse_duration(self):
        """Test standalone duration parsing used by /snooze."""
        self.assertEqual(parse_duration("10m"), timedelta(minutes=10))
        self.assertEqual(parse_duration("1h30m"), timedelta(minutes=90))
        self.assertEqual(parse_duration("half an hour"), timedelta(minutes=30))
        self.assertEqual(parse_duration("2 days"), timedelta(days=2))
        self.assertIsNone(parse_duration("10m call client"))

    def test_decode_restore_payload(self):
        raw = [
            {"text": "  call client  ", "trigger_iso": "2026-10-24T11:00:00+05:30"},
            {"text": "send quote", "trigger_iso": "2026-10-26T16:00:00"},
        ]
        payload = base64.urlsafe_b64encode(
            zlib.compress(json.dumps(raw).encode("utf-8"))
        ).decode("ascii")

        items = decode_restore_payload(payload)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["text"], "call client")
        self.assertEqual(items[0]["trigger_time"].isoformat(), "2026-10-24T11:00:00+05:30")
        self.assertEqual(items[1]["trigger_time"].isoformat(), "2026-10-26T16:00:00+05:30")

        with self.assertRaises(ValueError):
            decode_restore_payload("not-a-payload")
        with self.assertRaises(ValueError):
            decode_restore_payload("")

    def test_format_relative_delta(self):
        now = self.test_now
        t1 = datetime(2026, 10, 19, 16, 0, 0, tzinfo=IST)
        self.assertEqual(format_relative_delta(t1, now), "in 2 days, 2 hrs")

        t2 = datetime(2026, 10, 17, 14, 10, 0, tzinfo=IST)
        self.assertEqual(format_relative_delta(t2, now), "in 10 mins")

        t3 = datetime(2026, 10, 17, 14, 0, 10, tzinfo=IST)
        self.assertEqual(format_relative_delta(t3, now), "in 10 secs")


if __name__ == "__main__":
    unittest.main()
