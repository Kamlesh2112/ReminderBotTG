"""
parser.py - Intelligent parsing engine for Telegram followup reminders.
Features:
- Timezone: Indian Standard Time (IST, UTC+05:30)
- Working Hours Rule: Daytime between 9:00 AM and 8:00 PM IST (single digits 1..8 -> PM, 9..11 -> AM).
- Typo & Spelling Error Tolerance: Uses fuzzy matching for days, months, and units.
- Date Support: 'cb 9 nov', 'cb 9th nov', 'cb 9 nov 430', 'cb nov 9', 'cb 25 dec 5', etc.
- Optional LLM Fallback: Uses Google Gemini if GEMINI_API_KEY is configured.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("ReminderParser")

IST = ZoneInfo("Asia/Kolkata")

# Canonical mappings
WEEKDAYS_MAP: dict[str, int] = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

MONTHS_MAP: dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

DEFAULT_DAY_HOUR = 11
DEFAULT_DAY_MINUTE = 0


def get_current_ist_time() -> datetime:
    """Returns the current datetime in IST."""
    return datetime.now(IST)


def fuzzy_match(token: str, dictionary: dict[str, int], cutoff: float = 0.6) -> int | None:
    """Fuzzy matches a token against dictionary keys (e.g. for weekdays or months)."""
    token = token.lower().strip()
    # Exclude second-related tokens from ever matching months (e.g. 'sec' should not match 'sep')
    if token in ["s", "sec", "secs", "second", "seconds"]:
        return None
    if token in dictionary:
        return dictionary[token]
    matches = difflib.get_close_matches(token, list(dictionary.keys()), n=1, cutoff=cutoff)
    if matches:
        return dictionary[matches[0]]
    return None


def match_duration_unit(u: str) -> str | None:
    """Matches duration unit with typo tolerance."""
    u = u.lower().strip()
    if u in ["s", "sec", "secs", "second", "seconds"]:
        return "s"
    if u in ["m", "min", "mins", "minute", "minutes", "mn"]:
        return "m"
    if u in ["h", "hr", "hrs", "hour", "hours"]:
        return "h"
    if u in ["d", "day", "days"]:
        return "d"
    if u in ["w", "week", "weeks"]:
        return "w"

    for opt, target in [("seconds", "s"), ("minutes", "m"), ("hours", "h"), ("days", "d"), ("weeks", "w")]:
        if difflib.get_close_matches(u, [opt], n=1, cutoff=0.6):
            return target
    return None


def resolve_hour(hour: int, minute: int = 0, am_pm: str | None = None) -> tuple[int, int]:
    """
    Resolve hour based on IST daytime hours between 9:00 AM and 8:00 PM.
    - If explicit am/pm is supplied, respects it.
    - Otherwise:
      * 1 through 8 -> 1:00 PM to 8:00 PM (13:00 to 20:00)
      * 9 through 11 -> 9:00 AM to 11:00 AM (09:00 to 11:00)
      * 12 -> 12:00 PM (noon, 12:00)
      * >= 13 -> 24-hr format as is (e.g. 16 -> 16:00)
    """
    if am_pm:
        am_pm = am_pm.lower().strip()
        if am_pm == "am":
            if hour == 12:
                hour = 0
        elif am_pm == "pm":
            if hour < 12:
                hour += 12
        return hour, minute

    # No AM/PM specified: apply daytime 9am - 8pm IST rule
    if 1 <= hour <= 8:
        hour += 12
    # 9, 10, 11 remain AM (09, 10, 11)
    # 12 remains noon (12:00)
    return hour, minute


def parse_time_component(s: str) -> tuple[int, int] | None:
    """
    Parses a time string into (hour, minute) in 24-hour format.
    Supports '430' (4:30 PM), '1130' (11:30 AM), '4.30', '4:30', '4pm', '11am', '4', '11', etc.
    """
    s = s.strip().lower()
    if s.startswith("at "):
        s = s[3:].strip()
    s = s.rstrip('.!,')

    # 1. Matches '4:30 pm', '4.30pm', '11:00 am', '4:30', '4.30'
    m = re.match(r'^(\d{1,2})[:.](\d{2})\s*(am|pm)?$', s)
    if m:
        h = int(m.group(1))
        minute = int(m.group(2))
        ampm = m.group(3)
        if 0 <= h <= 24 and 0 <= minute < 60:
            return resolve_hour(h, minute, ampm)

    # 2. Matches '4pm', '11 am', '4 am', '12pm'
    m = re.match(r'^(\d{1,2})\s*(am|pm)$', s)
    if m:
        h = int(m.group(1))
        ampm = m.group(2)
        if 1 <= h <= 12:
            return resolve_hour(h, 0, ampm)

    # 3. Matches 3 or 4 digit compact time: '430' -> 4:30, '1130' -> 11:30, '815' -> 8:15
    m = re.match(r'^(\d{3,4})\s*(am|pm)?$', s)
    if m:
        val = m.group(1)
        ampm = m.group(2)
        if len(val) == 3:
            h = int(val[0])
            minute = int(val[1:])
        else:
            h = int(val[:2])
            minute = int(val[2:])
        if minute < 60 and 0 <= h <= 24:
            return resolve_hour(h, minute, ampm)

    # 4. Matches single or double digit hour: '4', '11', '8'
    m = re.match(r'^(\d{1,2})$', s)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 24:
            return resolve_hour(h, 0, None)

    return None


def parse_relative_duration(s: str) -> tuple[timedelta | None, str]:
    """
    Parses relative duration tokens at the beginning of s, tolerant of typos:
      - '10m', '10 min', '10 mins', '10 mintes', '10 minuts'
      - '2hr', '2h', '2 hours', '2 hourse', '2 hrs'
      - '2 days', '2d', '2 dys', '2 dasys'
      - '1 week', '1w', '1 wek'
    """
    s = s.strip()
    clean = s.lower()
    if clean.startswith("in "):
        clean = clean[3:].strip()
        s = s[3:].strip()

    pattern = r'^(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\b'
    total_delta = timedelta()
    matched = False

    while True:
        m = re.match(pattern, clean)
        if not m:
            break
        val = float(m.group(1))
        unit_str = m.group(2)
        unit = match_duration_unit(unit_str)
        if not unit:
            break

        matched = True
        if unit == "s":
            total_delta += timedelta(seconds=val)
        elif unit == "w":
            total_delta += timedelta(weeks=val)
        elif unit == "d":
            total_delta += timedelta(days=val)
        elif unit == "h":
            total_delta += timedelta(hours=val)
        elif unit == "m":
            total_delta += timedelta(minutes=val)

        span_end = m.end()
        clean = clean[span_end:].strip()
        s = s[span_end:].strip()

    if matched:
        return total_delta, s
    return None, s


def parse_date_component(tokens: list[str]) -> tuple[int, int, int | None, list[str]] | None:
    """
    Parses a date like '9 nov', '9th nov', 'nov 9', '9/11', '09-11-2026' from tokens.
    Returns (day, month, year_or_none, remaining_tokens) or None.
    """
    if not tokens:
        return None

    # Case 1: '9', '9th', or '9' followed by 'th', then month
    m_day = re.match(r'^(\d{1,2})(?:st|nd|rd|th)?$', tokens[0], re.IGNORECASE)
    if m_day:
        day = int(m_day.group(1))
        idx = 1
        if idx < len(tokens) and tokens[idx].lower() in ['st', 'nd', 'rd', 'th']:
            idx += 1
        if idx < len(tokens):
            month = fuzzy_match(tokens[idx], MONTHS_MAP)
            if month and 1 <= day <= 31:
                year = None
                rem_idx = idx + 1
                if rem_idx < len(tokens) and re.match(r'^\d{4}$', tokens[rem_idx]):
                    year = int(tokens[rem_idx])
                    rem_idx += 1
                return day, month, year, tokens[rem_idx:]

    # Case 2: 'nov 9', 'november 9th'
    month = fuzzy_match(tokens[0], MONTHS_MAP)
    if month and len(tokens) >= 2:
        m_day = re.match(r'^(\d{1,2})(?:st|nd|rd|th)?$', tokens[1], re.IGNORECASE)
        if m_day:
            day = int(m_day.group(1))
            if 1 <= day <= 31:
                year = None
                rem_idx = 2
                if len(tokens) >= 3 and re.match(r'^\d{4}$', tokens[2]):
                    year = int(tokens[2])
                    rem_idx = 3
                return day, month, year, tokens[rem_idx:]

    # Case 3: '9/11', '9-11', '9/11/2026'
    m_num_date = re.match(r'^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?$', tokens[0])
    if m_num_date:
        day = int(m_num_date.group(1))
        month = int(m_num_date.group(2))
        yr_str = m_num_date.group(3)
        year = None
        if yr_str:
            year = int(yr_str) if len(yr_str) == 4 else 2000 + int(yr_str)
        if 1 <= day <= 31 and 1 <= month <= 12:
            return day, month, year, tokens[1:]

    return None


def parse_with_llm(raw_text: str, now: datetime) -> dict[str, Any] | None:
    """
    Optional LLM parser using Google Gemini (via google-genai).
    Active only when GEMINI_API_KEY is configured in .env.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key.strip() == "YOUR_GEMINI_API_KEY_HERE":
        return None

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S (IST, %A)")
        
        prompt = (
            f"You are a followup reminder parser. Current time is: {now_str}.\n"
            f"Parse the following user message for a followup reminder: '{raw_text}'.\n"
            "Rules:\n"
            "1. Output valid JSON only with keys: 'is_reminder' (boolean), 'trigger_iso' (ISO 8601 string in IST +05:30), and 'note' (string).\n"
            "2. IST daytime rule: Single digits 1-8 mean PM (13:00 to 20:00), 9-11 mean AM (09:00 to 11:00).\n"
            "3. If only a day or date is given without time, default to 11:00 AM IST.\n"
            "4. Be tolerant of spelling errors, typos, and shorthand.\n"
            "JSON:"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        text = response.text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text)
            text = re.sub(r"```$", "", text).strip()

        data = json.loads(text)
        if data.get("is_reminder") and data.get("trigger_iso"):
            trigger_dt = datetime.fromisoformat(data["trigger_iso"]).astimezone(IST)
            return {
                "original_text": raw_text,
                "prefix": data.get("note", raw_text),
                "remainder": "",
                "trigger_time": trigger_dt,
                "type": "llm"
            }
    except Exception as e:
        logger.warning(f"LLM parsing failed or unavailable: {e}")

    return None


def parse_followup_command(raw_text: str, now: datetime | None = None) -> dict[str, Any] | None:
    """
    Main parser function for followup commands.
    Combines rule-based fuzzy matching with optional LLM fallback.
    """
    if now is None:
        now = datetime.now(IST)
    else:
        now = now.astimezone(IST)

    text = raw_text.strip()

    # Match 'cb', 'cbb', 'call back', 'callback' with word boundaries
    match = re.search(r'\b(?:cb|cbb|call\s*back)\b', text, flags=re.IGNORECASE)
    if not match:
        llm_res = parse_with_llm(text, now)
        if llm_res:
            return llm_res
        return None

    cb_start = match.start()
    cb_end = match.end()

    prefix = text[:cb_start].strip()
    after_cb = text[cb_end:].strip().rstrip('.!,')

    if not after_cb:
        return None

    # Strip optional leading 'on ', 'at ', or 'in '
    if after_cb.lower().startswith("on "):
        after_cb = after_cb[3:].strip()
    elif after_cb.lower().startswith("at "):
        after_cb = after_cb[3:].strip()

    # 1. Relative duration check (e.g. '2 days', '10m', '2hr', '2h', '2 dys', '10 minuts')
    delta, remainder = parse_relative_duration(after_cb)
    if delta is not None and delta.total_seconds() > 0:
        return {
            "original_text": text,
            "prefix": prefix,
            "remainder": remainder.strip(),
            "trigger_time": now + delta,
            "type": "relative"
        }

    # Normalize glued numbers + letters except ordinals (e.g. '9nov' -> '9 nov', but preserve '9th')
    normalized_after = re.sub(r'(\d+)(?!(?:st|nd|rd|th)\b)([a-zA-Z]+)', r'\1 \2', after_cb)
    tokens = normalized_after.split()
    if not tokens:
        return None

    # 2. Check for Date format: '9 nov', '9th nov', '9 november', 'nov 9', '9/11'
    date_parsed = parse_date_component(tokens)
    if date_parsed:
        day, month, yr, rem_tokens = date_parsed
        year = yr if yr is not None else now.year

        # Check for optional time following the date (e.g. '430', '4:30', '5pm')
        if rem_tokens and rem_tokens[0].lower() == "at":
            rem_tokens = rem_tokens[1:]

        time_part = None
        for k in [2, 1]:
            if len(rem_tokens) >= k:
                cand = " ".join(rem_tokens[:k])
                parsed = parse_time_component(cand)
                if parsed:
                    time_part = parsed
                    rem_tokens = rem_tokens[k:]
                    break

        if time_part:
            h, m = time_part
        else:
            h, m = DEFAULT_DAY_HOUR, DEFAULT_DAY_MINUTE

        try:
            cand_time = datetime(year, month, day, h, m, 0, tzinfo=IST)
        except ValueError:
            return None

        # If year was not specified and date has already passed, schedule for next year
        if yr is None and cand_time <= now:
            cand_time = datetime(year + 1, month, day, h, m, 0, tzinfo=IST)

        return {
            "original_text": text,
            "prefix": prefix,
            "remainder": " ".join(rem_tokens).strip(),
            "trigger_time": cand_time,
            "type": "date"
        }

    first = tokens[0].lower()
    is_next = False
    if first in ["next", "this"] and len(tokens) > 1:
        is_next = (first == "next")
        tokens = tokens[1:]
        first = tokens[0].lower()

    # 3. Weekday check with fuzzy typo tolerance ('monday', 'mondy', 'tuseday', 'wensday', etc.)
    target_weekday = fuzzy_match(first, WEEKDAYS_MAP)
    if target_weekday is not None:
        current_weekday = now.weekday()
        days_ahead = (target_weekday - current_weekday) % 7

        rem_tokens = tokens[1:]
        if rem_tokens and rem_tokens[0].lower() == "at":
            rem_tokens = rem_tokens[1:]

        time_part = None
        for k in [2, 1]:
            if len(rem_tokens) >= k:
                cand = " ".join(rem_tokens[:k])
                parsed = parse_time_component(cand)
                if parsed:
                    time_part = parsed
                    rem_tokens = rem_tokens[k:]
                    break

        if time_part:
            h, m = time_part
        else:
            h, m = DEFAULT_DAY_HOUR, DEFAULT_DAY_MINUTE

        if is_next and days_ahead == 0:
            days_ahead = 7
        elif is_next and days_ahead > 0:
            days_ahead += 7

        cand_date = now.date() + timedelta(days=days_ahead)
        cand_time = datetime(cand_date.year, cand_date.month, cand_date.day, h, m, 0, tzinfo=IST)

        if cand_time <= now:
            cand_time += timedelta(days=7)

        return {
            "original_text": text,
            "prefix": prefix,
            "remainder": " ".join(rem_tokens).strip(),
            "trigger_time": cand_time,
            "type": "weekday"
        }

    # 4. Tomorrow check with typo tolerance ('tomorrow', 'tomorow', 'tommorrow', 'tmrw', 'tmr')
    tom_match = difflib.get_close_matches(first, ["tomorrow", "tom", "tmrw", "tmr", "2moro", "tomorow"], n=1, cutoff=0.6)
    if tom_match:
        rem_tokens = tokens[1:]
        if rem_tokens and rem_tokens[0].lower() == "at":
            rem_tokens = rem_tokens[1:]

        # Check if user requested "same time"
        rem_text = " ".join(rem_tokens).lower()
        wants_same_time = bool(re.search(r'\b(?:same\s*time|current\s*time)\b', rem_text))
        if wants_same_time:
            rem_tokens = [t for t in rem_tokens if t.lower() not in ["same", "time", "at", "current"]]
            h, m = now.hour, now.minute
        else:
            time_part = None
            for k in [2, 1]:
                if len(rem_tokens) >= k:
                    cand = " ".join(rem_tokens[:k])
                    parsed = parse_time_component(cand)
                    if parsed:
                        time_part = parsed
                        rem_tokens = rem_tokens[k:]
                        break

            if time_part:
                h, m = time_part
            else:
                h, m = DEFAULT_DAY_HOUR, DEFAULT_DAY_MINUTE

        tom_date = now.date() + timedelta(days=1)
        cand_time = datetime(tom_date.year, tom_date.month, tom_date.day, h, m, 0, tzinfo=IST)
        return {
            "original_text": text,
            "prefix": prefix,
            "remainder": " ".join(rem_tokens).strip(),
            "trigger_time": cand_time,
            "type": "tomorrow"
        }

    # 5. Today check with typo tolerance ('today', 'tod', 'tday')
    today_match = difflib.get_close_matches(first, ["today", "tod", "tday"], n=1, cutoff=0.6)
    if today_match:
        rem_tokens = tokens[1:]
        if rem_tokens and rem_tokens[0].lower() == "at":
            rem_tokens = rem_tokens[1:]

        time_part = None
        for k in [2, 1]:
            if len(rem_tokens) >= k:
                cand = " ".join(rem_tokens[:k])
                parsed = parse_time_component(cand)
                if parsed:
                    time_part = parsed
                    rem_tokens = rem_tokens[k:]
                    break

        if time_part:
            h, m = time_part
        else:
            h, m = DEFAULT_DAY_HOUR, DEFAULT_DAY_MINUTE

        cand_time = datetime(now.year, now.month, now.day, h, m, 0, tzinfo=IST)
        if cand_time <= now:
            return None
        return {
            "original_text": text,
            "prefix": prefix,
            "remainder": " ".join(rem_tokens).strip(),
            "trigger_time": cand_time,
            "type": "today"
        }

    # 6. Direct time today / tomorrow (e.g. 'cb 430', 'cb 4:30', 'cb 11', 'cb 5pm')
    for k in [2, 1]:
        if len(tokens) >= k:
            cand = " ".join(tokens[:k])
            parsed = parse_time_component(cand)
            if parsed:
                h, m = parsed
                cand_time = datetime(now.year, now.month, now.day, h, m, 0, tzinfo=IST)
                if cand_time <= now:
                    cand_time += timedelta(days=1)
                return {
                    "original_text": text,
                    "prefix": prefix,
                    "remainder": " ".join(tokens[k:]).strip(),
                    "trigger_time": cand_time,
                    "type": "time_only"
                }

    # Fallback to LLM if configured
    llm_res = parse_with_llm(text, now)
    if llm_res:
        return llm_res

    return None


def format_relative_delta(trigger_time: datetime, now: datetime | None = None) -> str:
    """Returns human-readable remaining time string like 'in 2 days, 3 hrs'."""
    if now is None:
        now = datetime.now(IST)
    else:
        now = now.astimezone(IST)

    total_seconds = int((trigger_time - now).total_seconds())
    if total_seconds <= 0:
        return "now"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days} day" if days == 1 else f"{days} days")
    if hours > 0:
        parts.append(f"{hours} hr" if hours == 1 else f"{hours} hrs")
    if minutes > 0 and days == 0:
        parts.append(f"{minutes} min" if minutes == 1 else f"{minutes} mins")
    if seconds > 0 and days == 0 and hours == 0 and minutes == 0:
        parts.append(f"{seconds} sec" if seconds == 1 else f"{seconds} secs")

    if not parts:
        return "in less than a second"

    return "in " + ", ".join(parts)


def format_ist_datetime(dt: datetime) -> str:
    """Formats datetime as 'Tuesday, 20 Oct 2026 at 04:30 PM IST'"""
    dt_ist = dt.astimezone(IST)
    return dt_ist.strftime("%A, %d %b %Y at %I:%M %p IST")


def format_minimal_set_time(trigger_time: datetime, now: datetime | None = None) -> str:
    """Formats minimal readable time for confirmation: e.g. 'Tuesday, 20 Oct at 4:30 PM'"""
    if now is None:
        now = datetime.now(IST)
    else:
        now = now.astimezone(IST)

    dt_ist = trigger_time.astimezone(IST)
    time_str = dt_ist.strftime("%I:%M %p").lstrip("0")
    diff_days = (dt_ist.date() - now.date()).days

    if diff_days == 0:
        total_seconds = int((dt_ist - now).total_seconds())
        if total_seconds < 3600:
            delta_str = format_relative_delta(dt_ist, now)
            return f"today at {time_str} ({delta_str})"
        return f"today at {time_str}"
    elif diff_days == 1:
        return f"tomorrow at {time_str}"
    else:
        day_str = dt_ist.strftime("%A, %d %b").replace(" 0", " ")
        if dt_ist.year != now.year:
            day_str += f" {dt_ist.year}"
        return f"{day_str} at {time_str}"

