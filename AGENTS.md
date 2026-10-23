# AGENTS.md

Persistent project context for agents and future sessions. Read this before changing code,
especially before touching the database or deploying.

## What this project is

A Telegram bot that parses natural-language follow-up reminders in IST (India Standard Time),
stores them in SQLite, and sends `🔔 <text>` messages when they are due.

Core files:

- `bot.py` — Telegram handlers/commands and the background delivery scheduler.
- `parser.py` — fuzzy, typo-tolerant reminder/time parser (with optional Gemini fallback).
- `database.py` — SQLite schema, additive migrations, atomic claims, retries, rescheduling.
- `tests/` — `unittest` suite covering parser and database behavior.
- `data/followups.db` — runtime database (ignored by git; never commit it).
- `.env` — secrets (`TELEGRAM_BOT_TOKEN`, optional `GEMINI_API_KEY`; ignored by git).

## Production and deployment facts

- GitHub remote: `https://github.com/Kamlesh2112/ReminderBotTG.git`, branch `main`.
- Render hosts the bot from `main`. `Procfile` runs `web: python bot.py`; a `Dockerfile` also exists.
- The bot starts an HTTP health server on Render's `$PORT`; `/` returns
  `OK - Followup Reminder Bot is running!`.
- UptimeRobot pings that URL to keep the Render free instance awake. UptimeRobot does not
  persist application data.
- Render builds only pushed GitHub commits. Local changes do nothing in production until
  committed and pushed.

### CRITICAL: production reminders must never be deleted

The user has reminders stored by an older production version. Preserve them across deploys.

Rules:

1. **Never drop, recreate, truncate, or reinitialize the `reminders` table.** Schema changes
   must be additive (`ALTER TABLE ... ADD COLUMN`) and appended to the `migrations` dict in
   `database.py`.
2. `init_db()` creates a consistent SQLite backup (`<db>.bak-<timestamp>`) before applying
   any missing-column migration. Keep this behavior.
3. Tests must prove old-schema rows survive migration. See
   `test_migrates_old_database_schema` in `tests/test_database.py`.
4. Render free web services have **ephemeral storage and cannot attach persistent disks**
   (Render docs: free services lose filesystem changes on every deploy, restart, or spin-down).
   A deploy will erase `/app/data/followups.db` unless the service is on a paid instance with
   a disk mounted at `/app/data`, or `REMINDER_DB_PATH` points to a persistent-disk path
   (for example `/var/data/followups.db`).
5. This project uses UptimeRobot to keep a free Render instance awake, which strongly suggests
   the service is on the free plan. Before deploying, verify the Render service has a
   persistent disk. If that is uncertain or the service is free, **do not deploy until pending
   reminders are exported** (`/list`) and ready to re-add, or the database has been moved to
   Postgres/external storage. Do not assume UptimeRobot protects data.
6. Default DB path is `data/followups.db`; `REMINDER_DB_PATH` overrides it. Do not change
   this env var in production without moving/copying the existing database to the new path.
7. Never commit `.env`, `data/`, `*.db`, `*.db-wal`, `*.db-shm`, or backup files.

## Timer behavior

- Timezone is fixed to `Asia/Kolkata` (IST).
- Daytime rule when no AM/PM is given: `1..8` → PM (`13..20`), `9..11` → AM, `12` → noon.
- Weekday/date without a time defaults to 11:00 AM IST.
- `cb`, `cbb`, `call back`, `callback` trigger anywhere; `remind me`, `reminder`, `timer`,
  `alert`, `alarm`, `set a timer/reminder/alarm for` trigger only at message start to avoid
  false positives in normal chat.
- Supported examples: `cb 9 nov 430`, `cb 10m`, `cb 1h30m`, `cb half an hour`,
  `cb in 2 days at 5pm`, `cb next week`, `cb tomorrow evening`, `cb monday morning`,
  `cb tonight`, `cb eod`, `cb 9 nov same time`.
- Commands: `/remind`, `/timer`, `/alert`, `/alarm`, `/list`, `/del <id>`, `/dell`,
  `/snooze <id> <duration>`, `/restore <payload>`, `/help`.
- `/restore` decodes URL-safe base64 + zlib-compressed JSON (`text`, `trigger_iso`), scopes
  inserts to the current chat, and skips exact pending duplicates. Use it to recover after
  DB loss from a saved `/list` export. Never commit reminder payloads containing personal data.

## Delivery reliability invariants

- Scheduler polls every second and uses `database.claim_due_reminders()`.
- Claims are atomic (`BEGIN IMMEDIATE`); claimed rows cannot be selected by another worker.
- Stale claims become reclaimable after `CLAIM_TTL_SECONDS` (120s).
- Transient failures retry with exponential backoff (`5s` up to `15min`).
- Telegram `RetryAfter` is honored.
- `Forbidden` and `BadRequest` are permanent failures: mark `is_failed=1`; do not retry forever.
- Due reminders missed during downtime are delivered on startup.
- Notifications longer than Telegram's limit are truncated to 4000 characters.
- Do not replace claim/mark-sent flow with a plain `get_due_reminders()` + send loop; that
  reintroduces duplicate-delivery races.

## Development commands

```powershell
# Install dependencies
pip install -r requirements.txt

# Run all tests
python -m unittest discover tests -v

# Compile check
python -m compileall -q bot.py parser.py database.py tests

# Run locally (stops/replaces a previous local instance via .bot.pid)
python bot.py
```

There is no separate lint/typecheck command configured in this repo.

## Deploy and verify checklist

1. Run the full test suite.
2. Confirm the production DB persistence setup (persistent disk or `REMINDER_DB_PATH`).
3. Commit and push to `main` (only when the user asks for deployment).
4. Render auto-deploys if enabled; otherwise use **Manual Deploy → Deploy latest commit**.
5. Check Render logs for:
   - `Database ready at ...`
   - `Background reminder scheduler started.`
   - `Bot starting polling...`
6. Confirm the health URL returns `OK - Followup Reminder Bot is running!`.
7. Live-test in Telegram:
   - `/help` shows the new commands/formats.
   - `/remind 1m smoke test` confirms with an ID and fires after ~1 minute.
   - `cb 30s quick test` verifies second-level timers.
   - `/list`, `/snooze <id> 1m`, `/del <id>`, `dell`.
   - Set `cb 3m restart test`, restart the Render service, confirm delivery after restart
     (this only works if the database is on persistent storage).
8. Never test by deleting the production database or running `DELETE FROM reminders`.

## Known limitations / cautions

- SQLite is local to the Render service; without a persistent disk, data is lost on
  deploy/restart despite UptimeRobot keeping the service awake.
- Scheduler runs inside the single bot process. Multiple bot instances can still fight over
  Telegram `getUpdates`; keep one instance per token. Atomic claims prevent duplicate sends.
- Timezone is hardcoded to IST.
- Optional Gemini parsing only activates when `GEMINI_API_KEY` is set.
- `ensure_single_instance()` uses `.bot.pid`; stale PID files are harmless locally.
- Do not commit generated `__pycache__`, databases, logs, or backups.

## Last verified

2026-10-24 — 20 unit tests passing; additive migration preserves old reminders and creates a
pre-migration backup; `/restore` payload decoding and weekday-with-time parsing tested.
