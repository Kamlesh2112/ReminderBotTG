# 🔔 Telegram Followup Reminder Bot

An intelligent, typo-tolerant Telegram bot built in Python to track client callbacks, sales followups, and reminders.

---

## ⚡ Highlights & Features

- **Clean Reminder Messages**: Sent reminders use the simple format `🔔 text` and reply to the original message when it is still available.
- **Spelling & Typo Tolerant**: Understands common typos without failing:
  - Weekdays: `mondy`, `tuseday`, `wensday`, `thrusday`, `firday`, `satruday`, `sundey`
  - Months: `novmber`, `decemebr`, `octber`, `febraury`
  - Units & words: `2 dys`, `10 minuts`, `2 hourse`, `tomorow`, `cb 9nov`
- **Calendar Dates**:
  - `cb 9 nov` → Nov 9 at 11:00 AM IST
  - `quote review cb 9 nov 430` → Nov 9 at 4:30 PM IST (16:30)
  - Also supports `9th nov`, `nov 9`, `25 dec 5pm`, `9/11`
- **IST Daytime Hours (9:00 AM – 8:00 PM)**:
  - Single digits **1 to 8** automatically resolve to **1:00 PM to 8:00 PM** (`cb 4` → 4:00 PM IST).
  - Single/double digits **9 to 11** resolve to **9:00 AM to 11:00 AM** (`cb 10` → 10:00 AM IST).
  - **12** resolves to **12:00 PM (Noon)**.
  - Compact format: `430` means **4:30 PM**, `1130` means **11:30 AM**. Also supports `4.30` and `4:30`.
- **Default Weekday Time**: Day-of-week without an explicit time defaults to **11:00 AM IST** (`cb monday` → Monday at 11:00 AM).
- **Multiple Timer Keywords**: `cb`, `remind me`, `reminder`, `timer`, `alert`, `alarm`, and `set a timer/reminder/alarm for` all work (`timer 15m`, `remind me in 2h`, `set an alarm for 30m`).
- **More Relative Formats**: `1h30m`, `90m`, `half an hour`, `a couple of hours`, `in 2 days at 5pm`, `next week`, and `in 1 week evening`.
- **Day Periods**: `morning` (10 AM), `afternoon` (3 PM), `evening`/`eod` (6 PM), `night`/`tonight` (8 PM), `noon`, and `midnight`.
- **Commands**: `/remind <time> <note>`, `/timer`, `/alert`, `/list`, `/del <id>`, `/dell`, `/snooze <id> <duration>`, and `/restore <backup>`.
- **Reliable Timers**:
  - Reminders are **atomically claimed** in SQLite, so the same reminder can never be delivered twice.
  - Transient Telegram/network failures **retry automatically** with exponential backoff (up to 15 minutes).
  - Rate limits honour Telegram's `retry_after`; blocked chats and invalid targets are dropped instead of retrying forever.
  - Due reminders missed during downtime are delivered immediately on restart.
  - Scheduler polls every second; the database auto-migrates from older versions.
- **Dual Engine (Fuzzy + LLM)**:
  - Ultra-fast built-in fuzzy engine (zero API cost, instant execution).
  - Optional LLM integration: Add `GEMINI_API_KEY` to unlock conversational understanding.

---

## 📝 Syntax & Examples

| Example Input | Interpretation & Scheduled Time |
| :--- | :--- |
| `cb 9 nov` | Sends the note on **9 November at 11:00 AM IST**. |
| `quote review cb 9 nov 430` | Sends the note on **9 November at 4:30 PM IST** (`430` = 4:30 PM). |
| `rajesh 937 cb monday` | Sends the note on **Monday at 11:00 AM IST**. |
| `rutik 254 cb tuesday 430` | Sends the note on **Tuesday at 4:30 PM IST** (`430` = 4:30 PM). |
| `rutik 254 cb tuseday 4.30` | Typo tolerant: Sends on **Tuesday at 4:30 PM IST**. |
| `xx cb 2 days` or `xx cb 2 dys` | Sends the whole text after **2 days at the exact same time**. |
| `cb 10m` or `cb 10 minuts` | Sends text back in **10 minutes**. |
| `cb 1h30m` or `timer 90m` | Sends text back in **90 minutes**. |
| `cb half an hour` | Sends text back in **30 minutes**. |
| `cb 2hr` or `cb 2 hourse` | Sends text back in **2 hours**. |
| `cb in 2 days at 5pm` | Sends text **2 days from now at 5:00 PM IST**. |
| `cb next week` | Sends text **7 days later at the same time**. |
| `cb tomorrow 5` or `cb tomorow 5` | Sends text **tomorrow at 5:00 PM IST** (17:00). |
| `cb tomorrow evening` | Sends text **tomorrow at 6:00 PM IST**. |
| `cb monday morning` | Sends text **Monday at 10:00 AM IST**. |
| `cb tonight` or `cb eod` | Sends text **today at 8:00 PM / 6:00 PM IST** (rolls to the next day if already past). |
| `/remind 10m call client` | Sets a timer **10 minutes** from now. |
| `/snooze 4 10m` | Delays reminder **#4 by 10 minutes**. |
| `dell` or `del` | **Deletes the last scheduled reminder**. |
| `/list` or `list` | Lists all upcoming followups with IDs and countdowns. |

> Timer reliability: claiming is atomic, transient failures retry with backoff, and rate limits/blocked chats are handled without duplicate or endless notifications.

---

## 🚀 Setup & Run Instructions

### 1. Prerequisites
- Python 3.10+ (Tested on Python 3.14)
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)

### 2. Configure Bot Token
Open [`.env`](file:///.env) and set your tokens:
```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# Optional: Add Gemini API key for conversational LLM understanding
GEMINI_API_KEY=

# Optional: override the SQLite path (use a persistent disk path in production)
REMINDER_DB_PATH=
```

### 3. Run the Bot
```bash
python bot.py
```

---

## ☁️ Deployment (Render)

Render builds only pushed GitHub commits on `main`. The bot exposes a health endpoint on
`$PORT`, and UptimeRobot pings it to keep the free instance awake.

**Important:** Render free services use ephemeral storage. To keep reminders across deploys
and restarts, mount a persistent disk at `/app/data` (the default DB location) or set
`REMINDER_DB_PATH` to a file on a persistent disk. UptimeRobot keeps the service awake but
does **not** persist the database.

Schema upgrades are additive and never delete existing reminders. Before applying a
missing-column migration, the bot creates a `followups.db.bak-<timestamp>` backup.

If the database is wiped by an ephemeral-storage deploy, reminders can be restored from a
compact backup with `/restore <payload>`. Generate the payload from a saved `/list` export
(URL-safe base64 of zlib-compressed JSON containing `text` and `trigger_iso` fields). The
command is scoped to the current chat and skips exact duplicates.

---

## 🧪 Running Unit Tests

Run the automated test suite verifying all parsing rules, typo handling, and database operations:

```bash
python -m unittest discover tests
```
