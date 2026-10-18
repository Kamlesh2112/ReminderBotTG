# 🔔 Telegram Followup Reminder Bot

An intelligent, typo-tolerant Telegram bot built in Python to track client callbacks, sales followups, and reminders.

---

## ⚡ Highlights & Features

- **One-Tap Copyable Reminders**: Sent reminders use exact format: `🔔 <code>text</code>` (a single tap on the text copies it directly to your clipboard).
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
- **`dell` Command**: Instant cancellation of the last set reminder (or `/del <id>` for a specific one).
- **Dual Engine (Fuzzy + LLM)**:
  - Ultra-fast built-in fuzzy engine (zero API cost, instant execution).
  - Optional LLM integration: Add `GEMINI_API_KEY` to unlock conversational understanding.
- **Reliable Persistence**: Uses an indexed SQLite database in WAL mode—reminders persist across bot reboots, and any due followups during downtime are dispatched immediately upon restart.

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
| `cb 2hr` or `cb 2 hourse` | Sends text back in **2 hours**. |
| `cb tomorrow 5` or `cb tomorow 5` | Sends text **tomorrow at 5:00 PM IST** (17:00). |
| `dell` or `del` | **Deletes the last scheduled reminder**. |
| `/list` or `list` | Lists all upcoming followups with IDs and countdowns. |

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
```

### 3. Run the Bot
```bash
python bot.py
```

---

## 🧪 Running Unit Tests

Run the automated test suite verifying all parsing rules, typo handling, and database operations:

```bash
python -m unittest discover tests
```
