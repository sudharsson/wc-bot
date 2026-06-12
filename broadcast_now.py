"""One-off broadcast script. Run locally; does not affect the Railway bot."""
import os
import asyncio
from dotenv import load_dotenv
from supabase import create_client
from telegram import Bot

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

MESSAGE = (
    "⚽ The World Cup 2026 kicks off today!\n\n"
    "Lock in your predictions for the first two matches before kickoff at 3am lol! — "
    "once the whistle blows, predictions will be closed.\n\n"
    "👉 /predict to submit your picks\n"
    "🏆 /winner · /goldenboot · /goldenball for bonus pts\n\n"
    "Good luck! 🔮"
)


async def main():
    bot = Bot(token=BOT_TOKEN)
    db = create_client(SUPABASE_URL, SUPABASE_KEY)
    users = db.table("users").select("telegram_id").execute().data
    print(f"Sending to {len(users)} users...")
    sent, failed = 0, 0
    for u in users:
        try:
            await bot.send_message(chat_id=u["telegram_id"], text=MESSAGE)
            sent += 1
        except Exception as e:
            print(f"  Failed {u['telegram_id']}: {e}")
            failed += 1
    print(f"Done — {sent} sent, {failed} failed.")


asyncio.run(main())
