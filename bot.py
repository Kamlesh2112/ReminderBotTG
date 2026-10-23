"""
bot.py - Telegram Followup Reminder Bot
Handles:
- Natural language followups with typo & error tolerance
- Date support: 'cb 9 nov', 'cb 9 nov 430', 'cb 25 dec'
- Weekdays: 'rajesh 937 cb monday' (defaults to 11:00 AM IST)
- Specific times: 'rutik 254 cb tuesday 430' (4:30 PM IST)
- Relative delays: 'xx cb 2 days', 'cb 10m', 'cb 1h30m', 'cb next week'
- Day periods: 'cb tomorrow evening', 'cb monday morning', 'cb tonight'
- Commands: /remind, /timer, /alert, /snooze, /list, /del
- Daytime window: 9 AM to 8 PM IST
- Single bell reminders: 🔔 text
- Persistent SQLite database with atomic claims and retry/backoff
"""

import asyncio
import html
import logging
import os
import re
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Load environment variables before importing modules that read them at import time.
load_dotenv()

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import database
import parser

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("ReminderBot")

IST = ZoneInfo("Asia/Kolkata")
SCHEDULER_INTERVAL_SECONDS = 1
CLAIM_TTL_SECONDS = 120
RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 900
MAX_NOTIFICATION_CHARS = 4000


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /start command with a beautifully formatted guide and rich examples."""
    if not update.effective_message:
        return

    welcome_text = (
        "✨ <b>Followup & Reminder Bot</b>\n"
        "<i>Intelligent, typo-tolerant assistant for client calls, leads, and tasks.</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>Quick Examples (Tap code to copy):</b>\n\n"
        "• <b>Specific Dates:</b>\n"
        "  <code>cb 9 nov</code> → Nov 9 at 11:00 AM IST\n"
        "  <code>quote review cb 9 nov 430</code> → Nov 9 at 4:30 PM IST\n\n"
        "• <b>Weekdays (Defaults to 11:00 AM):</b>\n"
        "  <code>rajesh 937 cb monday</code> → Monday at 11:00 AM IST\n"
        "  <code>rutik 254 cb tuesday 430</code> → Tuesday at 4:30 PM IST\n\n"
        "• <b>Relative Timers:</b>\n"
        "  <code>cb 10m</code>, <code>cb 1h30m</code>, <code>cb half an hour</code>\n"
        "  <code>cb 2hr</code> or <code>cb 2h</code> → In 2 hours\n"
        "  <code>xx cb 2 days at 5pm</code> → In 2 days at 5:00 PM\n"
        "  <code>cb next week</code> → Same time next week\n\n"
        "• <b>Day Periods:</b>\n"
        "  <code>cb tomorrow evening</code> → Tomorrow at 6:00 PM\n"
        "  <code>cb monday morning</code> → Monday at 10:00 AM\n"
        "  <code>cb tonight</code> → Today at 8:00 PM\n"
        "  <code>cb eod</code> → Today at 6:00 PM\n\n"
        "• <b>Commands:</b>\n"
        "  <code>/remind 10m call client</code> → In 10 minutes\n"
        "  <code>/snooze 4 10m</code> → Delay reminder #4 by 10 minutes\n"
        "  <code>dell</code> → Deletes your last scheduled reminder\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🕒 <b>IST Daytime Rule (9:00 AM – 8:00 PM):</b>\n"
        "• Single digits <b>1 to 8</b> mean <b>PM</b> (e.g. <code>cb 4</code> = 4:00 PM).\n"
        "• Digits <b>9 to 11</b> mean <b>AM</b> (e.g. <code>cb 10</code> = 10:00 AM).\n"
        "• <b>430</b> = 4:30 PM, <b>1130</b> = 11:30 AM (also supports <code>4.30</code>, <code>4:30</code>).\n\n"
        "🤖 <b>Typo & Mistake Tolerant:</b>\n"
        "Understands typos like <code>mondy</code>, <code>tuseday</code>, <code>wensday</code>, <code>novmber</code>, <code>tomorow</code>, <code>2 dys</code>, etc.\n\n"
        "📋 <b>Commands:</b>\n"
        "/list — View pending followups\n"
        "/remind &lt;time&gt; &lt;note&gt; — Set a timer\n"
        "/snooze &lt;id&gt; &lt;duration&gt; — Delay a reminder\n"
        "/del &lt;id&gt; — Cancel a specific reminder\n"
        "/dell — Cancel the last reminder\n"
        "/help — Show this guide"
    )
    await update.effective_message.reply_text(welcome_text, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /help command."""
    await start_command(update, context)


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists all pending reminders for the current chat with copyable text."""
    if not update.effective_message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    reminders = database.get_pending_reminders_for_chat(chat_id)

    if not reminders:
        await update.effective_message.reply_text(
            "✨ <b>You have no pending followups.</b>",
            parse_mode=ParseMode.HTML
        )
        return

    now = parser.get_current_ist_time()
    lines = [f"📋 <b>Your Pending Followups ({len(reminders)}):</b>\n"]

    for r in reminders:
        dt = datetime.fromisoformat(r["trigger_time_iso"])
        time_str = parser.format_ist_datetime(dt)
        rel_str = parser.format_relative_delta(dt, now)
        escaped_text = html.escape(r["original_text"])
        lines.append(
            f"• <b>#{r['id']}</b>: <code>{escaped_text}</code>\n"
            f"   ⏰ {time_str} (<i>{rel_str}</i>)"
        )

    lines.append(
        "\n💡 <i>Type <code>dell</code> to delete the last reminder, "
        "<code>/del &lt;id&gt;</code> for a specific one, "
        "or <code>/snooze &lt;id&gt; 10m</code> to delay one.</i>"
    )
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def handle_dell(update: Update, specific_id: int | None = None) -> None:
    """Deletes last reminder or a specific reminder by ID."""
    if not update.effective_message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    if specific_id is not None:
        deleted = database.delete_reminder_by_id(specific_id, chat_id)
        if deleted:
            await update.effective_message.reply_text(f"🗑️ Deleted #{specific_id}: {deleted['original_text']}")
        else:
            await update.effective_message.reply_text(f"⚠️ Reminder #{specific_id} not found.")
        return

    # Delete the last reminder
    deleted = database.delete_last_pending_reminder(chat_id)
    if deleted:
        await update.effective_message.reply_text(f"🗑️ Deleted: {deleted['original_text']}")
    else:
        await update.effective_message.reply_text("ℹ️ No active reminders.")


async def create_reminder(
    update: Update,
    parse_text: str,
    store_text: str | None = None
) -> bool:
    """Parses and stores a reminder. Returns True when the reminder was created."""
    if not update.effective_message or not update.effective_chat or not update.effective_user:
        return False

    now_ist = parser.get_current_ist_time()
    parsed = parser.parse_followup_command(parse_text, now_ist)
    if not parsed:
        return False

    trigger_dt = parsed["trigger_time"]
    reminder_id = database.add_reminder(
        chat_id=update.effective_chat.id,
        user_id=update.effective_user.id,
        username=update.effective_user.username or update.effective_user.first_name,
        original_text=store_text or parse_text,
        trigger_time=trigger_dt,
        message_id=update.effective_message.message_id
    )

    time_str = parser.format_minimal_set_time(trigger_dt, now_ist)
    await update.effective_message.reply_text(
        f"✅ Set for {time_str} (#{reminder_id})",
        reply_to_message_id=update.effective_message.message_id
    )
    return True


async def send_parse_error(update: Update) -> None:
    """Sends a compact help message when a reminder time cannot be understood."""
    if not update.effective_message:
        return

    error_msg = (
        "⚠️ <b>Could not understand that time.</b>\n\n"
        "Try one of these formats:\n"
        "• <code>cb 9 nov</code> or <code>cb 9 nov 430</code>\n"
        "• <code>cb in 2 days at 5pm</code>\n"
        "• <code>cb monday morning</code> or <code>cb tomorrow evening</code>\n"
        "• <code>cb 10m</code>, <code>cb 2hr</code>, <code>cb half an hour</code>\n"
        "• <code>cb next week</code> or <code>cb tonight</code>\n"
        "• <code>/remind 10m call client</code>"
    )
    await update.effective_message.reply_text(
        error_msg,
        parse_mode=ParseMode.HTML,
        reply_to_message_id=update.effective_message.message_id
    )


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /remind, /timer, and /alert: time first, then an optional note."""
    if not update.effective_message:
        return

    args = context.args or []
    if not args:
        await update.effective_message.reply_text(
            "Usage: <code>/remind 10m call client</code> or <code>/remind 9 nov 430 quote review</code>",
            parse_mode=ParseMode.HTML
        )
        return

    note = " ".join(args).strip()
    if not await create_reminder(update, f"cb {note}", note):
        await send_parse_error(update)


async def del_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /del, optionally with a reminder ID."""
    args = context.args or []
    target_id = None
    if args:
        raw_id = args[0].lstrip("#")
        if not raw_id.isdigit():
            if update.effective_message:
                await update.effective_message.reply_text("Usage: /del &lt;id&gt;", parse_mode=ParseMode.HTML)
            return
        target_id = int(raw_id)
    await handle_dell(update, specific_id=target_id)


async def snooze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /snooze <id> <duration>, e.g. /snooze 4 10m."""
    if not update.effective_message or not update.effective_chat:
        return

    args = context.args or []
    if len(args) < 2 or not args[0].lstrip("#").isdigit():
        await update.effective_message.reply_text(
            "Usage: <code>/snooze &lt;id&gt; &lt;duration&gt;</code>\n"
            "Example: <code>/snooze 4 10m</code> or <code>/snooze 4 2h</code>",
            parse_mode=ParseMode.HTML
        )
        return

    reminder_id = int(args[0].lstrip("#"))
    delta = parser.parse_duration(" ".join(args[1:]))
    if delta is None:
        await update.effective_message.reply_text(
            "⚠️ Could not understand that duration. Try <code>/snooze 4 10m</code> or <code>/snooze 4 2h</code>.",
            parse_mode=ParseMode.HTML
        )
        return

    now_ist = parser.get_current_ist_time()
    new_time = now_ist + delta
    updated = database.reschedule_reminder(reminder_id, update.effective_chat.id, new_time)
    if not updated:
        await update.effective_message.reply_text(f"⚠️ Pending reminder #{reminder_id} not found.")
        return

    new_time = datetime.fromisoformat(updated["trigger_time_iso"])
    await update.effective_message.reply_text(
        f"😴 Snoozed #{reminder_id} until {parser.format_minimal_set_time(new_time, now_ist)} "
        f"({parser.format_relative_delta(new_time, now_ist)})"
    )


async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Restores reminders from a compact backup payload (used after DB loss)."""
    if not update.effective_message or not update.effective_chat or not update.effective_user:
        return

    raw_text = update.effective_message.text or ""
    parts = raw_text.split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""
    if not payload:
        await update.effective_message.reply_text(
            "Usage: <code>/restore &lt;backup payload&gt;</code>\n"
            "The payload is generated from a saved reminder backup.",
            parse_mode=ParseMode.HTML
        )
        return

    try:
        items = parser.decode_restore_payload(payload)
    except ValueError as e:
        await update.effective_message.reply_text(f"⚠️ {e}")
        return

    chat_id = update.effective_chat.id
    existing = database.get_pending_reminders_for_chat(chat_id)
    existing_keys = {(r["original_text"], r["trigger_time_iso"]) for r in existing}
    restored = 0
    skipped = 0
    username = update.effective_user.username or update.effective_user.first_name

    for item in items:
        trigger_time = item["trigger_time"]
        key = (item["text"], trigger_time.isoformat())
        if key in existing_keys:
            skipped += 1
            continue
        database.add_reminder(
            chat_id=chat_id,
            user_id=update.effective_user.id,
            username=username,
            original_text=item["text"],
            trigger_time=trigger_time,
            message_id=update.effective_message.message_id
        )
        existing_keys.add(key)
        restored += 1

    await update.effective_message.reply_text(
        f"✅ Restored {restored} reminder(s)."
        + (f" Skipped {skipped} already pending." if skipped else "")
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes incoming text messages."""
    if not update.effective_message or not update.effective_message.text:
        return

    raw_text = update.effective_message.text.strip()
    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    # 1. Check for 'dell' / 'del' / 'delete' (and common typos like 'dlete', 'delet')
    dell_match = re.match(r'^(?:dell|del|delete|dlete|delet|delte)(?:\s+(\d+))?$', raw_text, flags=re.IGNORECASE)
    if dell_match:
        target_id = int(dell_match.group(1)) if dell_match.group(1) else None
        await handle_dell(update, specific_id=target_id)
        return

    # 2. Check for 'list' keyword
    if raw_text.lower() == "list":
        await list_command(update, context)
        return

    # 3. Parse reminder (fuzzy + date + daytime rules + optional LLM)
    if await create_reminder(update, raw_text):
        return

    # 4. Text contains a reminder keyword but the time could not be parsed
    if parser.has_reminder_trigger(raw_text):
        await send_parse_error(update)
        return

    # 5. Message doesn't contain a reminder keyword in a private chat
    if chat.type == "private":
        hint = (
            "💡 <b>To set a followup, include <code>cb</code> or use <code>/remind</code>:</b>\n"
            "• <code>cb 9 nov</code>\n"
            "• <code>cb in 2 days at 5pm</code>\n"
            "• <code>cb monday morning</code>\n"
            "• <code>cb 10m</code> or <code>cb 2h</code>\n"
            "• <code>/remind 10m call client</code>\n\n"
            "<i>Type /help for full guide, /list for pending followups, <code>dell</code> to delete the last one, or /snooze to delay one.</i>"
        )
        await update.effective_message.reply_text(hint, parse_mode=ParseMode.HTML)


def _retry_delay_for_attempt(attempts: int) -> int:
    """Exponential backoff for transient delivery failures."""
    exponent = max(0, attempts - 1)
    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** exponent))


async def _deliver_reminder(application: Application, reminder: dict) -> None:
    """Delivers one reminder, preferring a reply to the original message."""
    rem_id = reminder["id"]
    chat_id = reminder["chat_id"]
    orig_text = reminder["original_text"]
    msg_id = reminder.get("message_id")

    notification_text = f"🔔 {orig_text}"
    if len(notification_text) > MAX_NOTIFICATION_CHARS:
        notification_text = notification_text[:MAX_NOTIFICATION_CHARS - 1] + "…"

    # Try replying to the original message first.
    if msg_id:
        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=notification_text,
                reply_to_message_id=msg_id
            )
            database.mark_reminder_sent(rem_id)
            logger.info(f"Delivered reminder #{rem_id} to chat {chat_id}: {orig_text}")
            return
        except (RetryAfter, Forbidden):
            raise
        except TelegramError as e:
            logger.warning(f"Could not reply to message {msg_id} (may have been deleted): {e}")

    # Fall back to a normal message.
    try:
        await application.bot.send_message(chat_id=chat_id, text=notification_text)
    except (RetryAfter, Forbidden, BadRequest):
        raise
    database.mark_reminder_sent(rem_id)
    logger.info(f"Delivered reminder #{rem_id} to chat {chat_id}: {orig_text}")


async def run_reminder_scheduler(application: Application) -> None:
    """
    Background worker loop that atomically claims due reminders and delivers them.
    Transient failures retry with exponential backoff; permanent failures are dropped.
    Sends: 🔔 {original_text}
    """
    logger.info("Background reminder scheduler started.")
    while True:
        try:
            due_reminders = database.claim_due_reminders(claim_ttl_seconds=CLAIM_TTL_SECONDS)
            for reminder in due_reminders:
                rem_id = reminder["id"]
                chat_id = reminder["chat_id"]
                attempts = int(reminder.get("attempts") or 0) + 1

                try:
                    await _deliver_reminder(application, reminder)
                except RetryAfter as e:
                    retry_after_value = getattr(e, "retry_after", 30) or 30
                    if hasattr(retry_after_value, "total_seconds"):
                        retry_after_value = retry_after_value.total_seconds()
                    retry_after = max(1, int(retry_after_value))
                    database.mark_reminder_failed(
                        rem_id, str(e), retry_delay_seconds=retry_after
                    )
                    logger.warning(
                        f"Reminder #{rem_id} rate-limited; retrying in {retry_after}s."
                    )
                except Forbidden as e:
                    database.mark_reminder_failed(rem_id, str(e), permanent=True)
                    logger.error(f"Reminder #{rem_id} dropped: bot is blocked from chat {chat_id}.")
                except BadRequest as e:
                    database.mark_reminder_failed(rem_id, str(e), permanent=True)
                    logger.error(f"Reminder #{rem_id} dropped after Telegram rejected it: {e}")
                except Exception as e:
                    delay = _retry_delay_for_attempt(attempts)
                    database.mark_reminder_failed(
                        rem_id, str(e), retry_delay_seconds=delay
                    )
                    logger.warning(
                        f"Delivery of reminder #{rem_id} failed (attempt {attempts}); "
                        f"retrying in {delay}s: {e}"
                    )

        except Exception as e:
            logger.error(f"Unexpected error in reminder scheduler loop: {e}", exc_info=True)

        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


async def post_init(application: Application) -> None:
    """Called after application initializes, starts background scheduler."""
    database.init_db()
    asyncio.create_task(run_reminder_scheduler(application))
    logger.info("Database initialized and scheduler task spawned.")


def ensure_single_instance(pid_file: str = ".bot.pid") -> None:
    """Ensures only one instance of the bot runs, preventing Telegram Conflict errors."""
    my_pid = os.getpid()
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                content = f.read().strip()
                if content.isdigit():
                    old_pid = int(content)
                    if old_pid != my_pid:
                        try:
                            import signal
                            os.kill(old_pid, signal.SIGTERM)
                            logger.info(f"Terminated previously running bot instance (PID {old_pid}).")
                        except (OSError, ProcessLookupError):
                            pass
        except Exception as e:
            logger.debug(f"PID check note: {e}")

    try:
        with open(pid_file, "w") as f:
            f.write(str(my_pid))
    except Exception as e:
        logger.debug(f"Could not write PID file: {e}")


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP responder for cloud health checks (Render, Koyeb, etc.)."""
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - Followup Reminder Bot is running!\n")

    def log_message(self, format: str, *args: object) -> None:
        # Suppress routine health check request logs
        pass


def start_health_check_server() -> None:
    """Starts a lightweight HTTP server on $PORT if provided by the cloud platform."""
    port_env = os.getenv("PORT")
    if not port_env:
        return

    try:
        port = int(port_env)
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Cloud health-check HTTP server listening on port {port}")
    except Exception as e:
        logger.warning(f"Failed to start health-check HTTP server on port {port_env}: {e}")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token.strip() == "YOUR_BOT_TOKEN_HERE":
        print("\n" + "=" * 60)
        print("ERROR: TELEGRAM_BOT_TOKEN is not set.")
        print("Please create or edit the .env file in the project directory:")
        print("  TELEGRAM_BOT_TOKEN=your_telegram_bot_token_from_botfather")
        print("=" * 60 + "\n")
        sys.exit(1)

    # Prevent multiple bot instances from running simultaneously
    ensure_single_instance()

    # Start health-check server if running on cloud service (Render, Koyeb, etc.)
    start_health_check_server()

    app = (
        ApplicationBuilder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("del", del_command))
    app.add_handler(CommandHandler("dell", del_command))
    app.add_handler(CommandHandler(["remind", "timer", "alert", "alarm"], remind_command))
    app.add_handler(CommandHandler("snooze", snooze_command))
    app.add_handler(CommandHandler("restore", restore_command))

    # Text message handler (handles 'cb', 'dell', 'list', etc.)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Bot starting polling...")
    try:
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        if "Conflict" in str(e) or "terminated by other getUpdates request" in str(e).lower():
            print("\n" + "=" * 60)
            print("⚠️ CONFLICT WARNING: Another bot instance is already polling.")
            print("Please close any other running terminal window or background process running bot.py.")
            print("=" * 60 + "\n")
        else:
            raise e


if __name__ == "__main__":
    main()
