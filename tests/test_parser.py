"""
Automated unit tests for parser, daytime logic, typo tolerance, and date parsing
"""

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from parser import (
    IST,
    parse_followup_command,
    parse_time_component,
    resolve_hour,
    format_relative_delta,
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
