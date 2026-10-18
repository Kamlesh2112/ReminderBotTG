"""
bot.py - Telegram Followup Reminder Bot
Handles:
- Natural language followups with typo & error tolerance
- Date support: 'cb 9 nov', 'cb 9 nov 430', 'cb 25 dec'
- Weekdays: 'rajesh 937 cb monday' (defaults to 11:00 AM IST)
- Specific times: 'rutik 254 cb tuesday 430' (4:30 PM IST)
- Relative delays: 'xx cb 2 days', 'cb 10m', 'cb 2hr'
- Daytime window: 9 AM to 8 PM IST
- Single bell copyable reminders: 🔔 <code>...</code>
- 'dell' to delete last set reminder
- Persistent SQLite database
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

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
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

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("ReminderBot")

IST = ZoneInfo("Asia/Kolkata")
SCHEDULER_INTERVAL_SECONDS = 3


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
        "  <code>cb 10m</code> → In 10 minutes\n"
        "  <code>cb 2hr</code> or <code>cb 2h</code> → In 2 hours\n"
        "  <code>xx cb 2 days</code> → In 2 days at same time\n\n"
        "• <b>Cancel Last Reminder:</b>\n"
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
        "/dell — Cancel last reminder\n"
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

    lines.append("\n💡 <i>Type <code>dell</code> to delete the last reminder, or <code>/del &lt;id&gt;</code> for a specific one.</i>")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def handle_dell(update: Update, specific_id: int | None = None) -> None:
    """Deletes last reminder or a specific reminder by ID."""
    if not update.effective_message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    if specific_id is not None:
        deleted = database.delete_reminder_by_id(specific_id, chat_id)
        if deleted:
            dt = datetime.fromisoformat(deleted["trigger_time_iso"])
            time_str = parser.format_ist_datetime(dt)
            escaped_text = html.escape(deleted["original_text"])
            await update.effective_message.reply_text(
                f"🗑️ <b>Deleted reminder #{specific_id}:</b>\n\n"
                f"<code>{escaped_text}</code>\n\n"
                f"⏰ <i>Was scheduled for: {time_str}</i>",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.effective_message.reply_text(
                f"⚠️ Reminder #{specific_id} not found or already sent/deleted.",
                parse_mode=ParseMode.HTML
            )
        return

    # Delete the last reminder
    deleted = database.delete_last_pending_reminder(chat_id)
    if deleted:
        dt = datetime.fromisoformat(deleted["trigger_time_iso"])
        time_str = parser.format_ist_datetime(dt)
        escaped_text = html.escape(deleted["original_text"])
        await update.effective_message.reply_text(
            f"🗑️ <b>Deleted last reminder:</b>\n\n"
            f"<code>{escaped_text}</code>\n\n"
            f"⏰ <i>Was scheduled for: {time_str}</i>",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.effective_message.reply_text(
            "ℹ️ <b>No active reminders found to delete.</b>",
            parse_mode=ParseMode.HTML
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

    chat_id = chat.id
    user_id = user.id
    username = user.username or user.first_name
    message_id = update.effective_message.message_id

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
    now_ist = parser.get_current_ist_time()
    parsed = parser.parse_followup_command(raw_text, now_ist)

    if parsed:
        trigger_dt = parsed["trigger_time"]
        reminder_id = database.add_reminder(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            original_text=raw_text,
            trigger_time=trigger_dt,
            message_id=message_id
        )

        time_str = parser.format_ist_datetime(trigger_dt)
        countdown = parser.format_relative_delta(trigger_dt, now_ist)
        escaped_text = html.escape(raw_text)

        confirm_msg = (
            f"✅ <b>Followup Scheduled!</b>\n\n"
            f"<code>{escaped_text}</code>\n\n"
            f"⏰ <b>When:</b> {time_str}\n"
            f"⏳ <b>Countdown:</b> {countdown}\n\n"
            f"<i>Tap the text above to copy. Send <code>dell</code> to cancel.</i>"
        )
        await update.effective_message.reply_text(
            confirm_msg,
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message_id
        )
        return

    # 4. If text contains 'cb' but could not be parsed
    if re.search(r'\b(?:cb|cbb|call\s*back)\b', raw_text, flags=re.IGNORECASE):
        error_msg = (
            "⚠️ <b>Could not understand the time for 'cb'.</b>\n\n"
            "Try one of these formats:\n"
            "• <code>cb 9 nov</code> or <code>cb 9 nov 430</code>\n"
            "• <code>rajesh 937 cb monday</code>\n"
            "• <code>rutik 254 cb tuesday 430</code>\n"
            "• <code>cb 10m</code> or <code>cb 2hr</code>\n"
            "• <code>xx cb 2 days</code>"
        )
        await update.effective_message.reply_text(
            error_msg,
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message_id
        )
        return

    # 5. Message doesn't contain 'cb' in a private chat
    if chat.type == "private":
        hint = (
            "💡 <b>To set a followup, include <code>cb</code> with your time:</b>\n"
            "• <code>cb 9 nov</code>\n"
            "• <code>rajesh 937 cb monday</code>\n"
            "• <code>rutik 254 cb tuesday 430</code>\n"
            "• <code>cb 10m</code> or <code>cb 2h</code>\n\n"
            "<i>Type /help for full guide, /list for pending followups, or <code>dell</code> to delete the last one.</i>"
        )
        await update.effective_message.reply_text(hint, parse_mode=ParseMode.HTML)


async def run_reminder_scheduler(application: Application) -> None:
    """
    Background worker loop that checks SQLite every few seconds
    and delivers due followup reminders.
    Sends: 🔔 <code>{original_text}</code> (one bell symbol and copyable text)
    """
    logger.info("Background reminder scheduler started.")
    while True:
        try:
            due_reminders = database.get_due_reminders()
            for reminder in due_reminders:
                rem_id = reminder["id"]
                chat_id = reminder["chat_id"]
                orig_text = reminder["original_text"]
                msg_id = reminder.get("message_id")

                # Exact format requested: one bell symbol and copyable text
                notification_text = f"🔔 <code>{html.escape(orig_text)}</code>"

                sent_ok = False
                # Try sending as a reply to the original message first
                if msg_id:
                    try:
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text=notification_text,
                            parse_mode=ParseMode.HTML,
                            reply_to_message_id=msg_id
                        )
                        sent_ok = True
                    except TelegramError as e:
                        logger.warning(f"Could not reply to message {msg_id} (may have been deleted): {e}")

                # If reply failed or no message_id, send standard message
                if not sent_ok:
                    try:
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text=notification_text,
                            parse_mode=ParseMode.HTML
                        )
                        sent_ok = True
                    except TelegramError as e:
                        logger.error(f"Failed to send reminder #{rem_id} to chat {chat_id}: {e}")

                if sent_ok:
                    database.mark_reminder_sent(rem_id)
                    logger.info(f"Delivered reminder #{rem_id} to chat {chat_id}: {orig_text}")

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
    app.add_handler(CommandHandler("dell", lambda u, c: handle_dell(u)))
    app.add_handler(CommandHandler("del", lambda u, c: handle_dell(u)))

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
