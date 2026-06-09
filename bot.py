import os
import logging
from dotenv import load_dotenv
from supabase import create_client
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()  # read secrets from .env

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# One database connection the whole bot shares.
db = create_client(SUPABASE_URL, SUPABASE_KEY)
# Remembers (telegram_id, match_id) pairs already pinged this run, so we don't repeat.
already_pinged = set()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Make sure this person exists in our users table (so later commands have a row to update).
    db.table("users").upsert({
        "telegram_id": user.id,
        "name": user.first_name,
    }).execute()
    await update.message.reply_text(
        f"⚽ Hey {user.first_name}! You're set up.\n\n"
        "Commands coming online:\n"
        "/ping – check I'm alive\n"
        "More soon: /remind, /teams, /predict, /leaderboard."
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")
async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args  # words typed after /remind, e.g. ["30"]

    if not args:
        await update.message.reply_text(
            "Set how early I ping you before kickoff:\n"
            "/remind 30  – 30 minutes before\n"
            "/remind 5   – 5 minutes before\n"
            "/remind off – stop reminders"
        )
        return

    choice = args[0].lower()

    if choice == "off":
        db.table("users").upsert({"telegram_id": user.id, "remind_minutes": 0}).execute()
        await update.message.reply_text("🔕 Reminders off.")
        return

    if not choice.isdigit():
        await update.message.reply_text("Give me a number of minutes, e.g. /remind 15")
        return

    minutes = int(choice)
    db.table("users").upsert({
        "telegram_id": user.id,
        "name": user.first_name,
        "remind_minutes": minutes,
    }).execute()
    await update.message.reply_text(f"⏰ Got it — I'll ping you {minutes} min before kickoff.")
from datetime import datetime, timezone

async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(timezone.utc)

    # Upcoming matches that haven't kicked off yet.
    matches = db.table("matches").select("*").eq("status", "scheduled").execute().data
    # Everyone who wants reminders (remind_minutes > 0).
    users = db.table("users").select("*").gt("remind_minutes", 0).execute().data
    if not matches or not users:
        return

    for m in matches:
        if not m.get("kickoff_utc"):
            continue
        kickoff = datetime.fromisoformat(m["kickoff_utc"])
        minutes_until = (kickoff - now).total_seconds() / 60
        if minutes_until <= 0:
            continue  # already started

        for u in users:
            lead = u["remind_minutes"]
            key = (u["telegram_id"], m["id"])
            # Ping if we're now within their lead window and haven't pinged yet.
            if minutes_until <= lead and key not in already_pinged:
                already_pinged.add(key)
                # Convert kickoff to Singapore time for the message.
                from datetime import timedelta
                sgt = kickoff.astimezone(timezone(timedelta(hours=8)))
                try:
                    await context.bot.send_message(
                        chat_id=u["telegram_id"],
                        text=(f"⚽ Kickoff soon!\n"
                              f"{m['team1']} v {m['team2']}\n"
                              f"{sgt.strftime('%H:%M')} SGT "
                              f"(in ~{int(minutes_until)} min)")
                    )
                except Exception as e:
                    logging.warning(f"Couldn't message {u['telegram_id']}: {e}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("remind", remind))
    app.job_queue.run_repeating(check_reminders, interval=60, first=10)
    print("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()