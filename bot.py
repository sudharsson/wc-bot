import os
import logging
from dotenv import load_dotenv
from supabase import create_client
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

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
    db.table("users").upsert({
        "telegram_id": user.id,
        "name": user.first_name,
    }).execute()
    await update.message.reply_text(
        f"⚽ Hey {user.first_name}! Welcome to the World Cup prediction game.\n\n"
        "Here's what I can do:\n"
        "/predict – predict a scoreline, e.g. /predict Brazil 2-1 Morocco\n"
        "/remind – ping me before kickoff, e.g. /remind 30 (or /remind off)\n"
        "/digest – daily list of upcoming matches, e.g. /digest 20 for 8pm SGT\n"
        "/ping – check I'm alive\n\n"
        "/fixtures – see upcoming matches\n"
        "/mypredictions – review or cancel your picks\n"
        "/leaderboard – points standings\n"
        "/ping – check I'm alive"
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
async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args  # e.g. ["Brazil", "2-1", "Morocco"]

    if len(args) < 3:
        await update.message.reply_text(
            "Predict a scoreline like this:\n"
            "/predict Brazil 2-1 Morocco\n\n"
            "Format: /predict <team> <home>-<away> <team>"
        )
        return

    # Find the score token (the one containing '-'), teams are around it.
    score_idx = next((i for i, a in enumerate(args) if "-" in a and any(c.isdigit() for c in a)), None)
    if score_idx is None or score_idx == 0 or score_idx == len(args) - 1:
        await update.message.reply_text(
            "I couldn't find the score. Use: /predict Brazil 2-1 Morocco"
        )
        return

    team1_text = " ".join(args[:score_idx]).strip()
    team2_text = " ".join(args[score_idx + 1:]).strip()
    score = args[score_idx]

    try:
        home_str, away_str = score.split("-")
        pred_home, pred_away = int(home_str), int(away_str)
    except ValueError:
        await update.message.reply_text("Score should look like 2-1. Try again.")
        return

    # Make sure the user exists in users table.
    db.table("users").upsert({"telegram_id": user.id, "name": user.first_name}).execute()

    # Find a scheduled match where both typed names appear (case-insensitive).
    matches = db.table("matches").select("*").eq("status", "scheduled").execute().data
    t1, t2 = team1_text.lower(), team2_text.lower()
    found = None
    for m in matches:
        mt1, mt2 = (m["team1"] or "").lower(), (m["team2"] or "").lower()
        if (t1 in mt1 and t2 in mt2) or (t1 in mt2 and t2 in mt1):
            found = m
            break

    if not found:
        await update.message.reply_text(
            f"No upcoming match found for {team1_text} v {team2_text}.\n"
            "Check spelling, or see /fixtures for what's open."
        )
        return

    # Reject if already kicked off.
    from datetime import datetime, timezone
    kickoff = datetime.fromisoformat(found["kickoff_utc"])
    if datetime.now(timezone.utc) >= kickoff:
        await update.message.reply_text("That match has already started — predictions are closed.")
        return

    # Orient the score to the fixture's team order (team1 is home in our table).
    if t1 in (found["team1"] or "").lower():
        h, a = pred_home, pred_away
    else:
        h, a = pred_away, pred_home  # user typed teams in reverse order

    db.table("predictions").upsert({
        "telegram_id": user.id,
        "match_id": found["id"],
        "pred_home": h,
        "pred_away": a,
    }, on_conflict="telegram_id,match_id").execute()

    await update.message.reply_text(
        f"✅ Prediction saved:\n{found['team1']} {h}–{a} {found['team2']}\n\n"
        "_To change it, just /predict the same match again._",
        parse_mode="Markdown",
    )
async def digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(
            "Get a daily list of upcoming matches to predict.\n"
            "/digest 20  – send it at 8pm SGT (use 24h time, 0–23)\n"
            "/digest 9   – send it at 9am SGT\n"
            "/digest off – stop the daily digest"
        )
        return

    choice = args[0].lower()

    if choice == "off":
        db.table("users").upsert({"telegram_id": user.id, "digest_hour": None}).execute()
        await update.message.reply_text("🔕 Daily digest off.")
        return

    if not choice.isdigit() or not (0 <= int(choice) <= 23):
        await update.message.reply_text("Give me an hour 0–23, e.g. /digest 20 for 8pm SGT.")
        return

    hour = int(choice)
    db.table("users").upsert({
        "telegram_id": user.id,
        "name": user.first_name,
        "digest_hour": hour,
    }).execute()
    # friendly 12h label
    label = f"{hour % 12 or 12}{'am' if hour < 12 else 'pm'}"
    await update.message.reply_text(f"📋 Daily digest set for {label} SGT.")
async def send_daily_digest(context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime, timezone, timedelta
    sgt = timezone(timedelta(hours=8))
    now_utc = datetime.now(timezone.utc)
    current_sgt_hour = now_utc.astimezone(sgt).hour

    # Who wants their digest this hour?
    users = db.table("users").select("*").eq("digest_hour", current_sgt_hour).execute().data
    if not users:
        return

    # Matches kicking off in the next 24h.
    window_end = now_utc + timedelta(hours=24)
    matches = db.table("matches").select("*").eq("status", "scheduled").execute().data
    upcoming = []
    for m in matches:
        if not m.get("kickoff_utc"):
            continue
        ko = datetime.fromisoformat(m["kickoff_utc"])
        if now_utc < ko <= window_end:
            upcoming.append((ko, m))
    upcoming.sort(key=lambda x: x[0])

    if not upcoming:
        return  # nothing in next 24h, skip everyone

    for u in users:
        # Which match_ids has this user already predicted?
        preds = db.table("predictions").select("match_id").eq("telegram_id", u["telegram_id"]).execute().data
        done = {p["match_id"] for p in preds}

        lines = ["📋 *Next 24 hours* — get your predictions in!\n"]
        unpredicted = 0
        for ko, m in upcoming:
            ko_sgt = ko.astimezone(sgt).strftime("%a %H:%M")
            if m["id"] in done:
                mark = "✅"
            else:
                mark = "⬜"
                unpredicted += 1
            lines.append(f"{mark} {ko_sgt}  {m['team1']} v {m['team2']}")

        if unpredicted:
            lines.append(f"\n{unpredicted} still to predict. Use /predict <team> <score> <team>.")
        else:
            lines.append("\nAll predicted — nice. 👏")

        try:
            await context.bot.send_message(
                chat_id=u["telegram_id"],
                text="\n".join(lines),
                parse_mode="Markdown",
            )
        except Exception as e:
            logging.warning(f"Digest send failed for {u['telegram_id']}: {e}")
async def fixtures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime, timezone, timedelta
    sgt = timezone(timedelta(hours=8))
    now = datetime.now(timezone.utc)

    args = context.args
    page = 1
    if args and args[0].isdigit():
        page = max(1, int(args[0]))

    PAGE_SIZE = 10
    all_matches = (
        db.table("matches")
        .select("*")
        .eq("status", "scheduled")
        .order("kickoff_utc")
        .execute()
        .data
    )
    upcoming = [m for m in all_matches if m.get("kickoff_utc") and datetime.fromisoformat(m["kickoff_utc"]) > now]

    total = len(upcoming)
    if not total:
        await update.message.reply_text("No upcoming fixtures found.")
        return

    offset = (page - 1) * PAGE_SIZE
    page_matches = upcoming[offset: offset + PAGE_SIZE]
    if not page_matches:
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        await update.message.reply_text(f"Only {total_pages} page(s) available. Try /fixtures 1.")
        return

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    lines = [f"📅 *Upcoming Fixtures* — page {page}/{total_pages}\n"]
    for m in page_matches:
        ko = datetime.fromisoformat(m["kickoff_utc"]).astimezone(sgt)
        lines.append(f"{ko.strftime('%a %d %b  %H:%M')} SGT   {m['team1']} v {m['team2']}")

    keyboard = None
    if page < total_pages:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Next page →", callback_data=f"fixtures:{page + 1}")]])

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


async def fixtures_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime, timezone, timedelta
    sgt = timezone(timedelta(hours=8))
    now = datetime.now(timezone.utc)

    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":")[1])
    PAGE_SIZE = 10

    all_matches = (
        db.table("matches")
        .select("*")
        .eq("status", "scheduled")
        .order("kickoff_utc")
        .execute()
        .data
    )
    upcoming = [m for m in all_matches if m.get("kickoff_utc") and datetime.fromisoformat(m["kickoff_utc"]) > now]

    total = len(upcoming)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page_matches = upcoming[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    lines = [f"📅 *Upcoming Fixtures* — page {page}/{total_pages}\n"]
    for m in page_matches:
        ko = datetime.fromisoformat(m["kickoff_utc"]).astimezone(sgt)
        lines.append(f"{ko.strftime('%a %d %b  %H:%M')} SGT   {m['team1']} v {m['team2']}")

    keyboard = None
    if page < total_pages:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Next page →", callback_data=f"fixtures:{page + 1}")]])

    await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


async def _predictions_message(telegram_id):
    """Build (text, reply_markup) for a user's predictions list."""
    from datetime import datetime, timezone, timedelta
    sgt = timezone(timedelta(hours=8))
    now = datetime.now(timezone.utc)

    preds = db.table("predictions").select("*").eq("telegram_id", telegram_id).execute().data
    if not preds:
        return "You haven't made any predictions yet.\nUse /predict to get started!", None

    match_ids = [p["match_id"] for p in preds]
    matches = db.table("matches").select("*").in_("id", match_ids).execute().data
    match_map = {m["id"]: m for m in matches}

    upcoming, played = [], []
    for p in preds:
        m = match_map.get(p["match_id"])
        if not m or not m.get("kickoff_utc"):
            continue
        ko = datetime.fromisoformat(m["kickoff_utc"])
        (upcoming if ko > now else played).append((ko, p, m))

    upcoming.sort(key=lambda x: x[0])
    played.sort(key=lambda x: x[0], reverse=True)

    lines = ["🔮 *Your Predictions*\n"]
    buttons = []

    if upcoming:
        lines.append("*Upcoming:*")
        for ko, p, m in upcoming:
            ko_str = ko.astimezone(sgt).strftime("%a %d %b %H:%M")
            lines.append(f"⬜ {m['team1']} {p['pred_home']}–{p['pred_away']} {m['team2']}  _{ko_str} SGT_")
            buttons.append([InlineKeyboardButton(
                f"🗑 Cancel: {m['team1']} v {m['team2']}",
                callback_data=f"cancel_pred:{m['id']}",
            )])

    if played:
        lines.append("\n*Played:*")
        for ko, p, m in played:
            ko_str = ko.astimezone(sgt).strftime("%a %d %b")
            sh, sa = m.get("score_home"), m.get("score_away")
            result = f"actual: {sh}–{sa}" if sh is not None and sa is not None else "result pending"
            lines.append(f"🔒 {m['team1']} {p['pred_home']}–{p['pred_away']} {m['team2']}  _({result})_  _{ko_str}_")

    if upcoming:
        lines.append("\n_To edit, /predict the same match with a new score._")

    return "\n".join(lines), InlineKeyboardMarkup(buttons) if buttons else None


async def mypredictions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, markup = await _predictions_message(update.effective_user.id)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)


async def cancel_pred_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime, timezone
    query = update.callback_query
    match_id = query.data.split(":", 1)[1]
    telegram_id = query.from_user.id

    row = db.table("matches").select("kickoff_utc").eq("id", match_id).execute().data
    if row and row[0].get("kickoff_utc"):
        if datetime.now(timezone.utc) >= datetime.fromisoformat(row[0]["kickoff_utc"]):
            await query.answer("Match already started — can't cancel.", show_alert=True)
            return

    db.table("predictions").delete().eq("telegram_id", telegram_id).eq("match_id", match_id).execute()
    await query.answer("Prediction cancelled.")
    text, markup = await _predictions_message(telegram_id)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from collections import defaultdict

    users = db.table("users").select("telegram_id, name").execute().data
    if not users:
        await update.message.reply_text("No players yet!")
        return

    preds = db.table("predictions").select("*").execute().data
    matches = db.table("matches").select("id, score_home, score_away").execute().data
    match_map = {m["id"]: m for m in matches}

    def points(p):
        m = match_map.get(p["match_id"])
        if not m:
            return 0
        sh, sa = m.get("score_home"), m.get("score_away")
        if sh is None or sa is None:
            return 0
        ph, pa = p["pred_home"], p["pred_away"]
        if ph == sh and pa == sa:
            return 3
        if (ph > pa) == (sh > sa) and ph != pa:  # correct outcome, not a draw mismatch
            return 1
        if ph == pa == sh == sa:  # both predicted draw, both drew (covered by exact above)
            return 3
        if ph == pa and sh == sa:  # predicted draw, actual draw, wrong score
            return 1
        return 0

    by_user = defaultdict(list)
    for p in preds:
        by_user[p["telegram_id"]].append(p)

    rows = []
    for u in users:
        uid = u["telegram_id"]
        ups = by_user[uid]
        pts = sum(points(p) for p in ups)
        rows.append((pts, len(ups), u.get("name") or "Anonymous"))

    rows.sort(key=lambda x: (-x[0], -x[1]))

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 *Leaderboard*\n"]
    for i, (pts, cnt, name) in enumerate(rows[:15]):
        rank = medals[i] if i < 3 else f"{i + 1}\\."
        lines.append(f"{rank} {name}  —  {pts} pts  _({cnt} predictions)_")

    if not any(r[0] > 0 for r in rows):
        lines.append("\n_Points will appear once match results are in._")

    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("predict",        "Predict a match scoreline"),
        BotCommand("fixtures",       "See upcoming matches"),
        BotCommand("mypredictions",  "Review your picks"),
        BotCommand("remind",         "Set kickoff reminders"),
        BotCommand("digest",         "Daily match digest"),
        BotCommand("leaderboard",    "See the points standings"),
        BotCommand("start",          "Welcome & setup"),
        BotCommand("ping",           "Check the bot is alive"),
    ])


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(set_commands).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(CommandHandler("predict", predict))
    app.job_queue.run_repeating(check_reminders, interval=60, first=10)
    app.job_queue.run_repeating(send_daily_digest, interval=3600, first=20)
    app.add_handler(CommandHandler("digest", digest))
    app.add_handler(CommandHandler("fixtures", fixtures))
    app.add_handler(CallbackQueryHandler(fixtures_cb, pattern=r"^fixtures:\d+$"))
    app.add_handler(CommandHandler("mypredictions", mypredictions))
    app.add_handler(CallbackQueryHandler(cancel_pred_cb, pattern=r"^cancel_pred:.+$"))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    print("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()