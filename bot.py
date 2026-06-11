import os
import logging
import random
import string
import time
import httpx
from dotenv import load_dotenv
from supabase import create_client
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)

load_dotenv()  # read secrets from .env

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
TOURNAMENT_WINNER = os.environ.get("TOURNAMENT_WINNER", "")
GOLDEN_BOOT_WINNER = os.environ.get("GOLDEN_BOOT_WINNER", "")
GOLDEN_BALL_WINNER = os.environ.get("GOLDEN_BALL_WINNER", "")

# One database connection the whole bot shares.
db = create_client(SUPABASE_URL, SUPABASE_KEY)
# Remembers (telegram_id, match_id) pairs already pinged this run, so we don't repeat.
already_pinged = set()
# Match IDs that have had a missed-prediction nudge sent this run.
already_nudged = set()
PICK_MATCH, ENTER_SCORE = range(2)

# Rate limiting: tracks last command timestamp per user.
_last_command: dict[int, float] = {}

def _is_rate_limited(user_id: int, seconds: float = 2.0) -> bool:
    now = time.time()
    if now - _last_command.get(user_id, 0) < seconds:
        return True
    _last_command[user_id] = now
    return False

FLAGS = {
    # South America
    "Argentina": "🇦🇷", "Brazil": "🇧🇷", "Uruguay": "🇺🇾", "Colombia": "🇨🇴",
    "Ecuador": "🇪🇨", "Paraguay": "🇵🇾", "Chile": "🇨🇱", "Peru": "🇵🇪",
    "Venezuela": "🇻🇪", "Bolivia": "🇧🇴",
    # North/Central America & Caribbean
    "USA": "🇺🇸", "United States": "🇺🇸", "Mexico": "🇲🇽", "Canada": "🇨🇦",
    "Panama": "🇵🇦", "Costa Rica": "🇨🇷", "Honduras": "🇭🇳", "Jamaica": "🇯🇲",
    "Trinidad and Tobago": "🇹🇹", "El Salvador": "🇸🇻", "Guatemala": "🇬🇹",
    "Cuba": "🇨🇺", "Haiti": "🇭🇹",
    # Europe
    "Germany": "🇩🇪", "France": "🇫🇷", "Spain": "🇪🇸", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "Portugal": "🇵🇹", "Netherlands": "🇳🇱", "Italy": "🇮🇹", "Belgium": "🇧🇪",
    "Croatia": "🇭🇷", "Switzerland": "🇨🇭", "Denmark": "🇩🇰", "Austria": "🇦🇹",
    "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Turkey": "🇹🇷", "Poland": "🇵🇱", "Serbia": "🇷🇸",
    "Romania": "🇷🇴", "Slovakia": "🇸🇰", "Hungary": "🇭🇺", "Ukraine": "🇺🇦",
    "Norway": "🇳🇴", "Greece": "🇬🇷", "Czech Republic": "🇨🇿", "Czechia": "🇨🇿",
    "Slovenia": "🇸🇮", "Albania": "🇦🇱", "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿", "Sweden": "🇸🇪",
    "Finland": "🇫🇮", "Bosnia and Herzegovina": "🇧🇦", "Montenegro": "🇲🇪",
    "North Macedonia": "🇲🇰", "Iceland": "🇮🇸", "Georgia": "🇬🇪",
    "Luxembourg": "🇱🇺", "Armenia": "🇦🇲", "Estonia": "🇪🇪",
    "Latvia": "🇱🇻", "Lithuania": "🇱🇹", "Kosovo": "🇽🇰",
    # Africa
    "Morocco": "🇲🇦", "Senegal": "🇸🇳", "Cameroon": "🇨🇲", "Nigeria": "🇳🇬",
    "Ivory Coast": "🇨🇮", "Côte d'Ivoire": "🇨🇮", "Egypt": "🇪🇬",
    "South Africa": "🇿🇦", "Tunisia": "🇹🇳", "DR Congo": "🇨🇩",
    "Ghana": "🇬🇭", "Algeria": "🇩🇿", "Mali": "🇲🇱", "Zambia": "🇿🇲",
    "Uganda": "🇺🇬", "Kenya": "🇰🇪", "Burkina Faso": "🇧🇫", "Guinea": "🇬🇳",
    "Cape Verde": "🇨🇻", "Angola": "🇦🇴", "Benin": "🇧🇯", "Ethiopia": "🇪🇹",
    "Mozambique": "🇲🇿", "Tanzania": "🇹🇿", "Rwanda": "🇷🇼", "Comoros": "🇰🇲",
    "Gabon": "🇬🇦", "Libya": "🇱🇾", "Sudan": "🇸🇩",
    # Asia
    "Japan": "🇯🇵", "South Korea": "🇰🇷", "Korea Republic": "🇰🇷",
    "Iran": "🇮🇷", "Saudi Arabia": "🇸🇦", "Australia": "🇦🇺",
    "Qatar": "🇶🇦", "Uzbekistan": "🇺🇿", "Jordan": "🇯🇴",
    "Oman": "🇴🇲", "Iraq": "🇮🇶", "China": "🇨🇳", "China PR": "🇨🇳",
    "Indonesia": "🇮🇩", "UAE": "🇦🇪", "United Arab Emirates": "🇦🇪",
    "Thailand": "🇹🇭", "Vietnam": "🇻🇳", "India": "🇮🇳",
    "Bahrain": "🇧🇭", "Kuwait": "🇰🇼", "Palestine": "🇵🇸",
    "Syria": "🇸🇾", "Kyrgyzstan": "🇰🇬", "Tajikistan": "🇹🇯",
    "Philippines": "🇵🇭", "Malaysia": "🇲🇾",
    # Oceania
    "New Zealand": "🇳🇿", "Fiji": "🇫🇯", "Vanuatu": "🇻🇺",
    "Papua New Guinea": "🇵🇬", "Solomon Islands": "🇸🇧",
    "Tahiti": "🇵🇫", "New Caledonia": "🇳🇨",
}

def flag(name: str) -> str:
    """Return 'emoji name' if a flag is known, else just 'name'."""
    return f"{FLAGS[name]} {name}" if name in FLAGS else name

def round_multiplier(round_name: str) -> int:
    knockout = {"round of 16", "quarter-final", "quarter final", "semi-final", "semi final", "third place", "final"}
    return 2 if (round_name or "").lower() in knockout else 1

def _generate_league_code() -> str:
    chars = string.ascii_uppercase + string.digits
    for _ in range(10):
        code = "".join(random.choices(chars, k=6))
        if not db.table("leagues").select("id").eq("code", code).execute().data:
            return code
    raise RuntimeError("Could not generate a unique league code after 10 attempts")

def _build_leaderboard_text(title: str, user_ids=None) -> str:
    from collections import defaultdict
    q = db.table("users").select("telegram_id, name, winner_pick, golden_boot_pick, golden_ball_pick")
    if user_ids is not None:
        if not user_ids:
            return "No players in this league yet\\."
        q = q.in_("telegram_id", user_ids)
    users = q.execute().data
    if not users:
        return "No players yet\\."
    preds = db.table("predictions").select("*").execute().data
    matches = db.table("matches").select("id, score_home, score_away, round").execute().data
    match_map = {m["id"]: m for m in matches}
    by_user = defaultdict(list)
    for p in preds:
        by_user[p["telegram_id"]].append(p)
    def score_for(p):
        m = match_map.get(p["match_id"])
        if not m or m.get("score_home") is None:
            return 0
        return calc_points(p["pred_home"], p["pred_away"], m["score_home"], m["score_away"]) * round_multiplier(m.get("round", ""))
    rows = []
    for u in users:
        uid = u["telegram_id"]
        pts = sum(score_for(p) for p in by_user[uid])
        winner_bonus = 10 if TOURNAMENT_WINNER and u.get("winner_pick") == TOURNAMENT_WINNER else 0
        boot_bonus = 5 if GOLDEN_BOOT_WINNER and (u.get("golden_boot_pick") or "").lower() == GOLDEN_BOOT_WINNER.lower() else 0
        ball_bonus = 5 if GOLDEN_BALL_WINNER and (u.get("golden_ball_pick") or "").lower() == GOLDEN_BALL_WINNER.lower() else 0
        pts += winner_bonus + boot_bonus + ball_bonus
        rows.append((pts, len(by_user[uid]), u.get("name") or "Anonymous", winner_bonus + boot_bonus + ball_bonus))
    rows.sort(key=lambda x: (-x[0], -x[1]))
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 *{title}*\n"]
    for i, (pts, cnt, name, bonus_pts) in enumerate(rows[:15]):
        rank = medals[i] if i < 3 else f"{i + 1}\\."
        bonus = " ⭐" if bonus_pts > 0 else ""
        lines.append(f"{rank} {name}{bonus}  —  {pts} pts  _({cnt} predictions)_")
    notes = []
    if TOURNAMENT_WINNER:
        notes.append(f"🏆 \\+10 winner")
    if GOLDEN_BOOT_WINNER:
        notes.append(f"👟 \\+5 golden boot")
    if GOLDEN_BALL_WINNER:
        notes.append(f"🏅 \\+5 golden ball")
    if notes:
        lines.append("\n_⭐ = bonus pts: " + " · ".join(notes) + "_")
    elif not any(r[0] > 0 for r in rows):
        lines.append("\n_Points will appear once match results are in\\._")
    return "\n".join(lines)

def calc_points(pred_home, pred_away, score_home, score_away) -> int:
    ph, pa, sh, sa = pred_home, pred_away, score_home, score_away
    if ph == sh and pa == sa:
        return 3
    if (ph > pa) == (sh > sa) and ph != pa:
        return 1
    if ph == pa and sh == sa:  # predicted draw, actual draw, wrong score
        return 1
    return 0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.table("users").upsert({
        "telegram_id": user.id,
        "name": user.first_name,
    }).execute()
    await update.message.reply_text(
        f"⚽ *Hey {user.first_name}! Welcome to the World Cup 2026 Prediction Game.*\n\n"
        "Predict the scoreline of every match, earn points, and beat your mates to the top of the leaderboard.\n\n"
        "🎯 *How points work:*\n"
        "• Exact scoreline → *3 pts*\n"
        "• Correct outcome (win or draw) → *1 pt*\n"
        "• Knockout rounds → points are *doubled*\n"
        "• Pick the tournament winner → *+10 bonus pts*\n"
        "• Pick the Golden Boot winner → *+5 bonus pts*\n"
        "• Pick the Golden Ball winner → *+5 bonus pts*\n\n"
        "🚀 *Get started in 3 steps:*\n"
        "1️⃣ /predict — pick your first match scoreline\n"
        "2️⃣ /winner · /goldenboot · /goldenball — pick your award winners\n"
        "3️⃣ /createleague MyLeagueName — create a private league and share the join code with friends\n"
        "   (or /joinleague CODE if a friend already made one)\n\n"
        "📋 *All commands:*\n"
        "/mypoints — your score, rank & stats\n"
        "/leaderboard — your league standings\n"
        "/masterleaderboard — everyone across all leagues\n"
        "/next — next 3 upcoming matches\n"
        "/fixtures — full fixture list\n"
        "/mypredictions — review or cancel your picks\n"
        "/whopicked — see everyone's pick after kickoff\n"
        "/myleague — your leagues and share codes\n"
        "/remind 30 — reminder 30 min before kickoff\n"
        "/digest 20 — daily digest at 8pm SGT\n\n"
        "_Predictions lock the moment a match kicks off. Good luck!_",
        parse_mode="Markdown",
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")
async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args  # words typed after /remind, e.g. ["30"]

    if not args:
        await update.message.reply_text(
            "Set how early I ping you before kickoff:\n"
            "/remind 30 mins  – 30 minutes before\n"
            "/remind 5 mins  – 5 minutes before\n"
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
    if minutes > 180:
        await update.message.reply_text("Max reminder is 180 minutes before kickoff.")
        return
    db.table("users").upsert({
        "telegram_id": user.id,
        "name": user.first_name,
        "remind_minutes": minutes,
    }).execute()
    await update.message.reply_text(f"⏰ Got it — I'll ping you {minutes} min before kickoff.")
from datetime import datetime, timezone

async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    from datetime import timedelta
    now = datetime.now(timezone.utc)

    matches = db.table("matches").select("*").eq("status", "scheduled").execute().data
    all_users = db.table("users").select("*").execute().data
    if not matches or not all_users:
        return

    for m in matches:
        if not m.get("kickoff_utc"):
            continue
        kickoff = datetime.fromisoformat(m["kickoff_utc"])
        minutes_until = (kickoff - now).total_seconds() / 60
        sgt = kickoff.astimezone(timezone(timedelta(hours=8)))

        if minutes_until > 0:
            # Remind users who are within their chosen lead window.
            for u in all_users:
                lead = u.get("remind_minutes") or 0
                if lead <= 0:
                    continue
                key = (u["telegram_id"], m["id"])
                if minutes_until <= lead and key not in already_pinged:
                    already_pinged.add(key)
                    try:
                        await context.bot.send_message(
                            chat_id=u["telegram_id"],
                            text=(f"⚽ Kickoff soon!\n"
                                  f"{flag(m['team1'])} v {flag(m['team2'])}\n"
                                  f"{sgt.strftime('%H:%M')} SGT "
                                  f"(in ~{int(minutes_until)} min)")
                        )
                    except Exception as e:
                        logging.warning(f"Couldn't message {u['telegram_id']}: {e}")

        elif minutes_until > -5 and m["id"] not in already_nudged:
            # Match just kicked off — nudge anyone who skipped it.
            already_nudged.add(m["id"])
            preds = db.table("predictions").select("telegram_id").eq("match_id", m["id"]).execute().data
            predicted_ids = {p["telegram_id"] for p in preds}
            for u in all_users:
                if u["telegram_id"] not in predicted_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=u["telegram_id"],
                            text=(f"⏰ Just kicked off — you missed this one!\n"
                                  f"{flag(m['team1'])} v {flag(m['team2'])}")
                        )
                    except Exception as e:
                        logging.warning(f"Nudge failed for {u['telegram_id']}: {e}")
def _build_predict_keyboard(uid: int, page: int):
    """Return (text, keyboard) for the match picker, or (None, None) if no matches."""
    from datetime import datetime, timezone, timedelta
    sgt = timezone(timedelta(hours=8))
    now = datetime.now(timezone.utc)

    all_matches = (
        db.table("matches").select("*").eq("status", "scheduled").order("kickoff_utc").execute().data
    )
    upcoming = [
        m for m in all_matches
        if m.get("kickoff_utc") and datetime.fromisoformat(m["kickoff_utc"]) > now
    ]
    if not upcoming:
        return None, None

    predicted_ids = {
        p["match_id"] for p in
        db.table("predictions").select("match_id").eq("telegram_id", uid).execute().data
    }

    PAGE_SIZE = 8
    total = len(upcoming)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    start = page * PAGE_SIZE
    page_matches = upcoming[start: start + PAGE_SIZE]

    buttons = []
    for m in page_matches:
        ko = datetime.fromisoformat(m["kickoff_utc"]).astimezone(sgt)
        mark = "✅" if m["id"] in predicted_ids else "⬜"
        label = f"{mark}  {flag(m['team1'])} v {flag(m['team2'])}  ·  {ko.strftime('%d %b %H:%M')}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"predict_match:{m['id']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("← Back", callback_data=f"predict_page:{page - 1}"))
    if start + PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("More →", callback_data=f"predict_page:{page + 1}"))
    if nav:
        buttons.append(nav)

    text = (
        f"⚽ *Pick a match to predict*  _(page {page + 1}/{total_pages})_\n"
        "_✅ = already predicted — tap again to update_"
    )
    return text, InlineKeyboardMarkup(buttons)


async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    # Text-based shortcut: /predict Brazil 2-1 Morocco still works
    if args:
        await _predict_from_args(update, context)
        return ConversationHandler.END

    db.table("users").upsert({"telegram_id": user.id, "name": user.first_name}).execute()
    text, keyboard = _build_predict_keyboard(user.id, 0)
    if not text:
        await update.message.reply_text("No upcoming matches to predict right now.")
        return ConversationHandler.END

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    return PICK_MATCH


async def predict_page_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":")[1])
    text, keyboard = _build_predict_keyboard(query.from_user.id, page)
    if not text:
        await query.edit_message_text("No upcoming matches.")
        return ConversationHandler.END
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    return PICK_MATCH


async def predict_pick_match_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    match_id = query.data.split(":", 1)[1]

    row = db.table("matches").select("*").eq("id", match_id).execute().data
    if not row:
        await query.edit_message_text("Match not found.")
        return ConversationHandler.END

    m = row[0]
    from datetime import datetime, timezone
    if datetime.now(timezone.utc) >= datetime.fromisoformat(m["kickoff_utc"]):
        await query.edit_message_text("That match has already kicked off — predictions are closed.")
        return ConversationHandler.END

    context.user_data["predict_match"] = m
    await query.edit_message_text(
        f"⚽ *{flag(m['team1'])} v {flag(m['team2'])}*\n\n"
        "Enter your score prediction, e.g. `2-1`\n\n"
        "_/cancel to go back_",
        parse_mode="Markdown",
    )
    return ENTER_SCORE


async def predict_enter_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    m = context.user_data.get("predict_match")
    if not m:
        await update.message.reply_text("Something went wrong. Try /predict again.")
        return ConversationHandler.END

    raw = update.message.text.strip().replace(" ", "")
    parts = raw.split("-", 1)
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await update.message.reply_text(
            "That doesn't look right — send just the score, e.g. `2-1`.",
            parse_mode="Markdown",
        )
        return ENTER_SCORE  # ask again

    pred_home, pred_away = int(parts[0]), int(parts[1])
    if pred_home > 20 or pred_away > 20:
        await update.message.reply_text("That score looks a bit off — max 20 goals per side. Try again.")
        return ENTER_SCORE

    from datetime import datetime, timezone
    if datetime.now(timezone.utc) >= datetime.fromisoformat(m["kickoff_utc"]):
        await update.message.reply_text("That match has now started — predictions are closed.")
        return ConversationHandler.END

    db.table("users").upsert({"telegram_id": user.id, "name": user.first_name}).execute()
    db.table("predictions").upsert({
        "telegram_id": user.id,
        "match_id": m["id"],
        "pred_home": pred_home,
        "pred_away": pred_away,
    }, on_conflict="telegram_id,match_id").execute()

    await update.message.reply_text(
        f"✅ Saved: {flag(m['team1'])} {pred_home}–{pred_away} {flag(m['team2'])}\n\n"
        "_/predict again to make another pick._",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def predict_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Use /predict to start again.")
    return ConversationHandler.END


async def _predict_from_args(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the shortcut: /predict Brazil 2-1 Morocco."""
    user = update.effective_user
    args = context.args

    score_idx = next((i for i, a in enumerate(args) if "-" in a and any(c.isdigit() for c in a)), None)
    if score_idx is None or score_idx == 0 or score_idx == len(args) - 1:
        await update.message.reply_text(
            "Couldn't parse that. Use `/predict Brazil 2-1 Morocco`\n"
            "or just `/predict` to pick from a list.",
            parse_mode="Markdown",
        )
        return

    team1_text = " ".join(args[:score_idx]).strip()
    team2_text = " ".join(args[score_idx + 1:]).strip()
    try:
        pred_home, pred_away = [int(x) for x in args[score_idx].split("-")]
    except ValueError:
        await update.message.reply_text("Score should look like 2-1. Try again.")
        return
    if pred_home > 20 or pred_away > 20:
        await update.message.reply_text("That score looks a bit off — max 20 goals per side.")
        return

    db.table("users").upsert({"telegram_id": user.id, "name": user.first_name}).execute()

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
            "Check spelling, or use /predict to pick from a list."
        )
        return

    from datetime import datetime, timezone
    if datetime.now(timezone.utc) >= datetime.fromisoformat(found["kickoff_utc"]):
        await update.message.reply_text("That match has already started — predictions are closed.")
        return

    if t1 in (found["team1"] or "").lower():
        h, a = pred_home, pred_away
    else:
        h, a = pred_away, pred_home

    db.table("predictions").upsert({
        "telegram_id": user.id,
        "match_id": found["id"],
        "pred_home": h,
        "pred_away": a,
    }, on_conflict="telegram_id,match_id").execute()

    await update.message.reply_text(
        f"✅ Saved: {flag(found['team1'])} {h}–{a} {flag(found['team2'])}\n\n"
        "_/predict again to make another pick._",
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
            lines.append(f"{mark} {ko_sgt}  {flag(m['team1'])} v {flag(m['team2'])}")

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
    uid = update.effective_user.id

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

    predicted_ids = {
        p["match_id"] for p in
        db.table("predictions").select("match_id").eq("telegram_id", uid).execute().data
    }

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    lines = [f"📅 *Upcoming Fixtures* — page {page}/{total_pages}  _(✅ = predicted)_\n"]
    for m in page_matches:
        ko = datetime.fromisoformat(m["kickoff_utc"]).astimezone(sgt)
        mark = "✅" if m["id"] in predicted_ids else "⬜"
        lines.append(f"{mark} {ko.strftime('%a %d %b  %H:%M')} SGT   {flag(m['team1'])} v {flag(m['team2'])}")

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
    uid = query.from_user.id
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

    predicted_ids = {
        p["match_id"] for p in
        db.table("predictions").select("match_id").eq("telegram_id", uid).execute().data
    }

    total = len(upcoming)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page_matches = upcoming[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    lines = [f"📅 *Upcoming Fixtures* — page {page}/{total_pages}  _(✅ = predicted)_\n"]
    for m in page_matches:
        ko = datetime.fromisoformat(m["kickoff_utc"]).astimezone(sgt)
        mark = "✅" if m["id"] in predicted_ids else "⬜"
        lines.append(f"{mark} {ko.strftime('%a %d %b  %H:%M')} SGT   {flag(m['team1'])} v {flag(m['team2'])}")

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
            lines.append(f"⬜ {flag(m['team1'])} {p['pred_home']}–{p['pred_away']} {flag(m['team2'])}  _{ko_str} SGT_")
            buttons.append([InlineKeyboardButton(
                f"🗑 Cancel: {flag(m['team1'])} v {flag(m['team2'])}",
                callback_data=f"cancel_pred:{m['id']}",
            )])

    if played:
        lines.append("\n*Played:*")
        for ko, p, m in played:
            ko_str = ko.astimezone(sgt).strftime("%a %d %b")
            sh, sa = m.get("score_home"), m.get("score_away")
            if sh is not None and sa is not None:
                pts = calc_points(p["pred_home"], p["pred_away"], sh, sa) * round_multiplier(m.get("round", ""))
                result = f"{sh}–{sa}, +{pts}pts"
            else:
                result = "result pending"
            lines.append(f"🔒 {flag(m['team1'])} {p['pred_home']}–{p['pred_away']} {flag(m['team2'])}  _({result})_  _{ko_str}_")

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
    uid = update.effective_user.id
    if _is_rate_limited(uid):
        await update.message.reply_text("⏳ Slow down! Wait a moment and try again.")
        return
    memberships = db.table("league_members").select("league_id").eq("telegram_id", uid).execute().data

    if not memberships:
        text = _build_leaderboard_text("Master Leaderboard")
        await update.message.reply_text(text, parse_mode="MarkdownV2")
        return

    league_ids = [m["league_id"] for m in memberships]
    leagues = db.table("leagues").select("*").in_("id", league_ids).execute().data

    if len(leagues) == 1:
        league = leagues[0]
        members = db.table("league_members").select("telegram_id").eq("league_id", league["id"]).execute().data
        user_ids = [m["telegram_id"] for m in members]
        text = _build_leaderboard_text(league["name"], user_ids)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌍 Master Leaderboard", callback_data="leaderboard:global")
        ]])
        await update.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)
    else:
        buttons = [[InlineKeyboardButton(lg["name"], callback_data=f"leaderboard:league:{lg['id']}")] for lg in leagues]
        buttons.append([InlineKeyboardButton("🌍 Master Leaderboard", callback_data="leaderboard:global")])
        await update.message.reply_text("Which leaderboard?", reply_markup=InlineKeyboardMarkup(buttons))


async def leaderboard_global_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = _build_leaderboard_text("Master Leaderboard")
    await query.edit_message_text(text, parse_mode="MarkdownV2")


async def leaderboard_league_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    league_id = int(query.data.split(":")[-1])
    league = db.table("leagues").select("*").eq("id", league_id).execute().data
    if not league:
        await query.edit_message_text("League not found.")
        return
    league = league[0]
    members = db.table("league_members").select("telegram_id").eq("league_id", league_id).execute().data
    user_ids = [m["telegram_id"] for m in members]
    text = _build_leaderboard_text(league["name"], user_ids)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🌍 Master Leaderboard", callback_data="leaderboard:global")
    ]])
    await query.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)


async def mypoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from collections import defaultdict
    uid = update.effective_user.id
    if _is_rate_limited(uid):
        await update.message.reply_text("⏳ Slow down! Wait a moment and try again.")
        return

    preds = db.table("predictions").select("*").eq("telegram_id", uid).execute().data
    if not preds:
        await update.message.reply_text("You haven't made any predictions yet. Use /predict to get started!")
        return

    match_ids = [p["match_id"] for p in preds]
    matches = db.table("matches").select("id, score_home, score_away, round").in_("id", match_ids).execute().data
    match_map = {m["id"]: m for m in matches}

    total_pts = 0
    exact = 0
    exact_pts = 0
    correct_outcome = 0
    outcome_pts = 0
    pending = 0

    for p in preds:
        m = match_map.get(p["match_id"])
        if not m or m.get("score_home") is None:
            pending += 1
            continue
        pts = calc_points(p["pred_home"], p["pred_away"], m["score_home"], m["score_away"]) * round_multiplier(m.get("round", ""))
        total_pts += pts
        if pts >= 3:
            exact += 1
            exact_pts += pts
        elif pts > 0:
            correct_outcome += 1
            outcome_pts += pts

    user_row = db.table("users").select("winner_pick, golden_boot_pick, golden_ball_pick").eq("telegram_id", uid).execute().data
    user_row = user_row[0] if user_row else {}
    winner_pick = user_row.get("winner_pick")
    boot_pick = user_row.get("golden_boot_pick")
    ball_pick = user_row.get("golden_ball_pick")
    winner_bonus = 10 if TOURNAMENT_WINNER and winner_pick == TOURNAMENT_WINNER else 0
    boot_bonus = 5 if GOLDEN_BOOT_WINNER and (boot_pick or "").lower() == GOLDEN_BOOT_WINNER.lower() else 0
    ball_bonus = 5 if GOLDEN_BALL_WINNER and (ball_pick or "").lower() == GOLDEN_BALL_WINNER.lower() else 0
    total_pts += winner_bonus + boot_bonus + ball_bonus

    # Compute rank across all players
    all_users = db.table("users").select("telegram_id, winner_pick, golden_boot_pick, golden_ball_pick").execute().data
    all_preds = db.table("predictions").select("*").execute().data
    all_matches_data = db.table("matches").select("id, score_home, score_away, round").execute().data
    all_match_map = {m["id"]: m for m in all_matches_data}
    preds_by_user = defaultdict(list)
    for p in all_preds:
        preds_by_user[p["telegram_id"]].append(p)

    def user_total(u):
        s = sum(
            calc_points(p["pred_home"], p["pred_away"],
                        all_match_map[p["match_id"]]["score_home"],
                        all_match_map[p["match_id"]]["score_away"]) *
            round_multiplier(all_match_map[p["match_id"]].get("round", ""))
            for p in preds_by_user[u["telegram_id"]]
            if p["match_id"] in all_match_map and all_match_map[p["match_id"]].get("score_home") is not None
        )
        if TOURNAMENT_WINNER and u.get("winner_pick") == TOURNAMENT_WINNER:
            s += 10
        if GOLDEN_BOOT_WINNER and (u.get("golden_boot_pick") or "").lower() == GOLDEN_BOOT_WINNER.lower():
            s += 5
        if GOLDEN_BALL_WINNER and (u.get("golden_ball_pick") or "").lower() == GOLDEN_BALL_WINNER.lower():
            s += 5
        return s

    all_scores = sorted([user_total(u) for u in all_users], reverse=True)
    rank = next((i + 1 for i, s in enumerate(all_scores) if s <= total_pts), len(all_scores))
    total_players = len(all_users)

    settled = len(preds) - pending
    lines = [
        "🎯 *Your Score*\n",
        f"*{total_pts} pts* — #{rank} of {total_players}",
        f"from {settled} settled prediction{'s' if settled != 1 else ''}",
    ]
    if exact:
        lines.append(f"✅ {exact} exact score{'s' if exact != 1 else ''} (+{exact_pts} pts)")
    if correct_outcome:
        lines.append(f"👍 {correct_outcome} correct outcome{'s' if correct_outcome != 1 else ''} (+{outcome_pts} pts)")
    if pending:
        lines.append(f"⏳ {pending} result{'s' if pending != 1 else ''} still pending")
    if settled > 0:
        hit_rate = round((exact + correct_outcome) / settled * 100)
        lines.append(f"\n_Hit rate: {hit_rate}% ({exact + correct_outcome}/{settled})_")

    streak = _compute_streak(uid, preds_by_user, all_match_map)
    if streak >= 2:
        lines.append(f"\n🔥 {streak} correct in a row!")

    if winner_pick:
        note = " ✅ +10 pts!" if winner_bonus else ""
        lines.append(f"\n🏆 Winner: {flag(winner_pick)}{note}")
    if boot_pick:
        note = " ✅ +5 pts!" if boot_bonus else ""
        lines.append(f"👟 Golden Boot: {boot_pick}{note}")
    if ball_pick:
        note = " ✅ +5 pts!" if ball_bonus else ""
        lines.append(f"🏅 Golden Ball: {ball_pick}{note}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if _is_rate_limited(user.id):
        await update.message.reply_text("⏳ Slow down! Wait a moment and try again.")
        return
    args = context.args

    if not args:
        row = db.table("users").select("winner_pick").eq("telegram_id", user.id).execute().data
        current = row[0].get("winner_pick") if row else None
        if current:
            await update.message.reply_text(
                f"🏆 Your winner pick: {flag(current)}\n\n"
                "_To change: /winner <team>_\n"
                "_To clear: /winner off_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "🏆 *Who's winning the World Cup?*\n\n"
                "Set your pick: `/winner Brazil`\n"
                "Correct pick at the final = *+10 bonus points!*\n\n"
                "_Can be changed up until the final kicks off._",
                parse_mode="Markdown",
            )
        return

    if args[0].lower() == "off":
        db.table("users").update({"winner_pick": None}).eq("telegram_id", user.id).execute()
        await update.message.reply_text("🏆 Winner pick cleared.")
        return

    team = " ".join(args)
    matched = next((t for t in FLAGS if t.lower() == team.lower()), None)
    if not matched:
        await update.message.reply_text(
            f"I don't recognise '{team}'. Check the spelling and try again.\n"
            "Use /fixtures to see team names."
        )
        return

    db.table("users").upsert({"telegram_id": user.id, "name": user.first_name, "winner_pick": matched}).execute()
    await update.message.reply_text(
        f"🏆 Winner pick saved: {flag(matched)}\n\n"
        "_Correct pick = +10 bonus pts at the final!_",
        parse_mode="Markdown",
    )


async def goldenboot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if _is_rate_limited(user.id):
        await update.message.reply_text("⏳ Slow down! Wait a moment and try again.")
        return
    args = context.args

    if not args:
        row = db.table("users").select("golden_boot_pick").eq("telegram_id", user.id).execute().data
        current = (row[0].get("golden_boot_pick") if row else None)
        if current:
            await update.message.reply_text(
                f"👟 Your Golden Boot pick: *{current}*\n\n"
                "_To change: /goldenboot Player Name_\n"
                "_To clear: /goldenboot off_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "👟 *Who'll be the top scorer?*\n\n"
                "Set your pick: `/goldenboot Kylian Mbappe`\n"
                "Correct pick = *+5 bonus points!*",
                parse_mode="Markdown",
            )
        return

    if args[0].lower() == "off":
        db.table("users").update({"golden_boot_pick": None}).eq("telegram_id", user.id).execute()
        await update.message.reply_text("👟 Golden Boot pick cleared.")
        return

    pick = " ".join(args).strip()
    if len(pick) > 50:
        await update.message.reply_text("That name is too long. Try again.")
        return
    db.table("users").upsert({"telegram_id": user.id, "name": user.first_name, "golden_boot_pick": pick}).execute()
    await update.message.reply_text(
        f"👟 Golden Boot pick saved: *{pick}*\n\n"
        "_Correct pick = +5 bonus pts!_",
        parse_mode="Markdown",
    )


async def goldenball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if _is_rate_limited(user.id):
        await update.message.reply_text("⏳ Slow down! Wait a moment and try again.")
        return
    args = context.args

    if not args:
        row = db.table("users").select("golden_ball_pick").eq("telegram_id", user.id).execute().data
        current = (row[0].get("golden_ball_pick") if row else None)
        if current:
            await update.message.reply_text(
                f"🏅 Your Golden Ball pick: *{current}*\n\n"
                "_To change: /goldenball Player Name_\n"
                "_To clear: /goldenball off_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "🏅 *Who'll be the best player?*\n\n"
                "Set your pick: `/goldenball Lamine Yamal`\n"
                "Correct pick = *+5 bonus points!*",
                parse_mode="Markdown",
            )
        return

    if args[0].lower() == "off":
        db.table("users").update({"golden_ball_pick": None}).eq("telegram_id", user.id).execute()
        await update.message.reply_text("🏅 Golden Ball pick cleared.")
        return

    pick = " ".join(args).strip()
    if len(pick) > 50:
        await update.message.reply_text("That name is too long. Try again.")
        return
    db.table("users").upsert({"telegram_id": user.id, "name": user.first_name, "golden_ball_pick": pick}).execute()
    await update.message.reply_text(
        f"🏅 Golden Ball pick saved: *{pick}*\n\n"
        "_Correct pick = +5 bonus pts!_",
        parse_mode="Markdown",
    )


def _compute_streak(uid: int, preds_by_user: dict, match_map: dict) -> int:
    results = []
    for p in preds_by_user[uid]:
        m = match_map.get(p["match_id"])
        if not m or m.get("score_home") is None:
            continue
        pts = calc_points(p["pred_home"], p["pred_away"], m["score_home"], m["score_away"])
        results.append((m.get("kickoff_utc", ""), pts > 0))
    results.sort(key=lambda x: x[0])
    streak = 0
    for _, correct_pred in reversed(results):
        if correct_pred:
            streak += 1
        else:
            break
    return streak


async def _broadcast_match_result(bot, match, sh, sa):
    """DM every predictor with result, points, streak, and group stats. Also posts to group chat."""
    from collections import Counter, defaultdict

    preds = db.table("predictions").select("*").eq("match_id", match["id"]).execute().data
    if not preds:
        return

    mult = round_multiplier(match.get("round", ""))
    total = len(preds)
    pick_counts = Counter((p["pred_home"], p["pred_away"]) for p in preds)
    top_pick, top_count = pick_counts.most_common(1)[0]
    correct = sum(1 for p in preds if calc_points(p["pred_home"], p["pred_away"], sh, sa) > 0)
    stats_line = (
        f"\n\n📊 {correct}/{total} predicted correctly"
        f" · Most picked: {top_pick[0]}–{top_pick[1]} ({top_count})"
    )

    # Batch-load all predictions + match results for streak computation
    all_predictor_ids = [p["telegram_id"] for p in preds]
    all_preds = db.table("predictions").select("*").in_("telegram_id", all_predictor_ids).execute().data
    all_match_ids = list({p["match_id"] for p in all_preds})
    streak_matches = db.table("matches").select("id, kickoff_utc, score_home, score_away").in_("id", all_match_ids).execute().data
    streak_match_map = {m["id"]: m for m in streak_matches}
    preds_by_user = defaultdict(list)
    for p in all_preds:
        preds_by_user[p["telegram_id"]].append(p)

    for p in preds:
        pts = calc_points(p["pred_home"], p["pred_away"], sh, sa) * mult
        if pts >= 3:
            verdict = f"✅ Exact score! *+{pts} pts*"
        elif pts > 0:
            verdict = f"👍 Correct outcome! *+{pts} pt{'s' if pts > 1 else ''}*"
        else:
            verdict = "❌ Unlucky. +0 pts"

        streak = _compute_streak(p["telegram_id"], preds_by_user, streak_match_map)
        streak_line = f"\n🔥 {streak} correct in a row!" if streak >= 3 else (f"\n🔥 {streak} in a row!" if streak == 2 else "")

        try:
            await bot.send_message(
                chat_id=p["telegram_id"],
                text=(
                    f"⚽ Full time!\n"
                    f"{flag(match['team1'])} {sh}–{sa} {flag(match['team2'])}\n\n"
                    f"Your prediction: {p['pred_home']}–{p['pred_away']}\n"
                    f"{verdict}"
                    f"{streak_line}"
                    f"{stats_line}"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logging.warning(f"Broadcast failed for {p['telegram_id']}: {e}")



async def poll_results(context: ContextTypes.DEFAULT_TYPE):
    """Fetch finished WC match results from api-football and update Supabase."""
    if not FOOTBALL_API_KEY:
        return

    from datetime import timedelta
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=105)).isoformat()

    pending = (
        db.table("matches")
        .select("*")
        .eq("status", "scheduled")
        .lt("kickoff_utc", cutoff)
        .execute()
        .data
    )
    if not pending:
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://v3.football.api-sports.io/fixtures",
                headers={"x-apisports-key": FOOTBALL_API_KEY},
                params={"league": 1, "season": 2026, "status": "FT"},
            )
    except Exception as e:
        logging.warning(f"poll_results request failed: {e}")
        return

    if resp.status_code != 200:
        logging.warning(f"poll_results: API returned {resp.status_code}")
        return

    api_fixtures = resp.json().get("response", [])
    if not api_fixtures:
        return

    # Build lookup: (home_name_lower, away_name_lower) -> (score_home, score_away)
    api_lookup = {}
    for f in api_fixtures:
        home = f["teams"]["home"]["name"].lower()
        away = f["teams"]["away"]["name"].lower()
        goals = f["goals"]
        if goals["home"] is not None and goals["away"] is not None:
            api_lookup[(home, away)] = (int(goals["home"]), int(goals["away"]))

    for match in pending:
        t1 = (match["team1"] or "").lower()
        t2 = (match["team2"] or "").lower()

        # Exact match first, then partial (handles name differences like "Korea Republic" vs "South Korea")
        result = api_lookup.get((t1, t2))
        if not result:
            for (ah, aa), scores in api_lookup.items():
                if (t1 in ah or ah in t1) and (t2 in aa or aa in t2):
                    result = scores
                    break

        if result:
            sh, sa = result
            db.table("matches").update({
                "score_home": sh,
                "score_away": sa,
                "status": "finished",
            }).eq("id", match["id"]).execute()
            logging.info(f"Result saved: {match['team1']} {sh}-{sa} {match['team2']}")

            # Broadcast result to everyone who predicted this match.
            await _broadcast_match_result(context.bot, match, sh, sa)


async def setresult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    args = context.args
    score_idx = next((i for i, a in enumerate(args) if "-" in a and any(c.isdigit() for c in a)), None)
    if not args or score_idx is None or score_idx == 0 or score_idx == len(args) - 1:
        await update.message.reply_text("Usage: /setresult Brazil 2-1 Morocco")
        return

    team1_text = " ".join(args[:score_idx]).strip()
    team2_text = " ".join(args[score_idx + 1:]).strip()
    try:
        sh, sa = [int(x) for x in args[score_idx].split("-")]
    except ValueError:
        await update.message.reply_text("Score should look like 2-1.")
        return

    matches = db.table("matches").select("*").execute().data
    t1, t2 = team1_text.lower(), team2_text.lower()
    found = None
    for m in matches:
        mt1, mt2 = (m["team1"] or "").lower(), (m["team2"] or "").lower()
        if (t1 in mt1 and t2 in mt2) or (t1 in mt2 and t2 in mt1):
            found = m
            break

    if not found:
        await update.message.reply_text(f"No match found for {team1_text} v {team2_text}.")
        return

    if t1 in (found["team1"] or "").lower():
        final_sh, final_sa = sh, sa
    else:
        final_sh, final_sa = sa, sh

    already_finished = found.get("status") == "finished"
    db.table("matches").update({
        "score_home": final_sh,
        "score_away": final_sa,
        "status": "finished",
    }).eq("id", found["id"]).execute()

    note = " (score updated — no re-broadcast)" if already_finished else ""
    await update.message.reply_text(
        f"✅ Result set: {flag(found['team1'])} {final_sh}–{final_sa} {flag(found['team2'])}{note}"
    )

    if not already_finished:
        await _broadcast_match_result(context.bot, found, final_sh, final_sa)


async def next_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime, timezone, timedelta
    sgt = timezone(timedelta(hours=8))
    now = datetime.now(timezone.utc)
    uid = update.effective_user.id

    all_matches = (
        db.table("matches").select("*").eq("status", "scheduled").order("kickoff_utc").execute().data
    )
    upcoming = [m for m in all_matches if m.get("kickoff_utc") and datetime.fromisoformat(m["kickoff_utc"]) > now]

    if not upcoming:
        await update.message.reply_text("No upcoming matches.")
        return

    predicted_ids = {
        p["match_id"] for p in
        db.table("predictions").select("match_id").eq("telegram_id", uid).execute().data
    }

    lines = ["🗓 *Next up:*\n"]
    for m in upcoming[:3]:
        ko = datetime.fromisoformat(m["kickoff_utc"]).astimezone(sgt)
        mark = "✅" if m["id"] in predicted_ids else "⬜"
        lines.append(f"{mark} {ko.strftime('%a %d %b  %H:%M')} SGT   {flag(m['team1'])} v {flag(m['team2'])}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def whopicked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime, timezone, timedelta
    args = context.args

    if len(args) < 2:
        await update.message.reply_text("Usage: /whopicked Brazil Morocco")
        return
    if any(len(a) > 50 for a in args):
        await update.message.reply_text("Team name too long. Check spelling and try again.")
        return

    # Parse team names (ignore any score token if present)
    score_idx = next((i for i, a in enumerate(args) if "-" in a and any(c.isdigit() for c in a)), None)
    if score_idx is not None:
        team1_text = " ".join(args[:score_idx]).strip()
        team2_text = " ".join(args[score_idx + 1:]).strip()
    else:
        team1_text = args[0]
        team2_text = " ".join(args[1:])

    matches = db.table("matches").select("*").execute().data
    t1, t2 = team1_text.lower(), team2_text.lower()
    found = None
    for m in matches:
        mt1, mt2 = (m["team1"] or "").lower(), (m["team2"] or "").lower()
        if (t1 in mt1 and t2 in mt2) or (t1 in mt2 and t2 in mt1):
            found = m
            break

    if not found:
        await update.message.reply_text(f"No match found for {team1_text} v {team2_text}.")
        return

    kickoff = datetime.fromisoformat(found["kickoff_utc"])
    if datetime.now(timezone.utc) < kickoff:
        sgt = timezone(timedelta(hours=8))
        ko_sgt = kickoff.astimezone(sgt).strftime("%a %d %b %H:%M")
        await update.message.reply_text(
            f"Picks for {flag(found['team1'])} v {flag(found['team2'])} are hidden until kickoff ({ko_sgt} SGT)."
        )
        return

    preds = db.table("predictions").select("*").eq("match_id", found["id"]).execute().data
    if not preds:
        await update.message.reply_text(f"Nobody predicted {flag(found['team1'])} v {flag(found['team2'])}.")
        return

    users = db.table("users").select("telegram_id, name").execute().data
    user_names = {u["telegram_id"]: u.get("name") or "Anonymous" for u in users}

    sh, sa = found.get("score_home"), found.get("score_away")
    lines = [f"🔮 *{flag(found['team1'])} v {flag(found['team2'])}*\n"]
    for p in sorted(preds, key=lambda x: (x["pred_home"], x["pred_away"])):
        name = user_names.get(p["telegram_id"], "Anonymous")
        score_str = f"{p['pred_home']}–{p['pred_away']}"
        if sh is not None and sa is not None:
            pts = calc_points(p["pred_home"], p["pred_away"], sh, sa) * round_multiplier(found.get("round", ""))
            pts_tag = f"  ✅ +{pts}pts" if pts > 0 else "  ❌"
        else:
            pts_tag = ""
        lines.append(f"{name}: {score_str}{pts_tag}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def createleague(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text(
            "Give your league a name: `/createleague My Friends`",
            parse_mode="Markdown",
        )
        return
    name = " ".join(context.args).strip()
    if len(name) > 30:
        await update.message.reply_text("League name must be 30 characters or fewer.")
        return
    if _is_rate_limited(user.id):
        await update.message.reply_text("⏳ Slow down! Wait a moment and try again.")
        return
    try:
        db.table("users").upsert({"telegram_id": user.id, "name": user.first_name}).execute()
        code = _generate_league_code()
        result = db.table("leagues").insert({"name": name, "code": code}).execute()
        league_id = result.data[0]["id"]
        db.table("league_members").insert({"league_id": league_id, "telegram_id": user.id}).execute()
    except Exception as e:
        logging.error(f"createleague failed for {user.id}: {e}")
        await update.message.reply_text("❌ Couldn't create the league. Please try again later.")
        return
    await update.message.reply_text(
        f"🏆 League *{name}* created!\n\n"
        f"Share this code with your friends:\n"
        f"`{code}`\n\n"
        f"They join with: `/joinleague {code}`",
        parse_mode="Markdown",
    )


async def joinleague(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("Usage: `/joinleague ABC123`", parse_mode="Markdown")
        return
    if _is_rate_limited(user.id):
        await update.message.reply_text("⏳ Slow down! Wait a moment and try again.")
        return
    code = context.args[0][:10].upper()
    row = db.table("leagues").select("*").eq("code", code).execute().data
    if not row:
        await update.message.reply_text(
            f"No league found with code `{code}`\\. Check the code and try again.",
            parse_mode="Markdown",
        )
        return
    league = row[0]
    db.table("users").upsert({"telegram_id": user.id, "name": user.first_name}).execute()
    existing = (
        db.table("league_members")
        .select("league_id")
        .eq("league_id", league["id"])
        .eq("telegram_id", user.id)
        .execute().data
    )
    if existing:
        await update.message.reply_text(f"You're already in *{league['name']}*!", parse_mode="Markdown")
        return
    db.table("league_members").insert({"league_id": league["id"], "telegram_id": user.id}).execute()
    count = len(db.table("league_members").select("telegram_id").eq("league_id", league["id"]).execute().data)
    await update.message.reply_text(
        f"✅ Joined *{league['name']}*! ({count} member{'s' if count != 1 else ''})\n\n"
        f"Use /leaderboard to see the standings.",
        parse_mode="Markdown",
    )


async def myleague(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from collections import defaultdict
    uid = update.effective_user.id
    memberships = db.table("league_members").select("league_id").eq("telegram_id", uid).execute().data
    if not memberships:
        await update.message.reply_text(
            "You're not in any league yet.\n\n"
            "Create one: `/createleague My Friends`\n"
            "Or join one: `/joinleague ABC123`",
            parse_mode="Markdown",
        )
        return
    league_ids = [m["league_id"] for m in memberships]
    leagues = db.table("leagues").select("*").in_("id", league_ids).execute().data

    all_member_rows = db.table("league_members").select("league_id, telegram_id").in_("league_id", league_ids).execute().data
    all_member_ids = list({r["telegram_id"] for r in all_member_rows})
    user_rows = db.table("users").select("telegram_id, name").in_("telegram_id", all_member_ids).execute().data
    user_name_map = {u["telegram_id"]: u.get("name") or "Anonymous" for u in user_rows}

    members_by_league = defaultdict(list)
    for r in all_member_rows:
        members_by_league[r["league_id"]].append(r["telegram_id"])

    lines = ["🏆 *Your Leagues*\n"]
    for lg in leagues:
        member_ids = members_by_league[lg["id"]]
        count = len(member_ids)
        names = ", ".join(user_name_map.get(mid, "Anonymous") for mid in member_ids)
        lines.append(f"*{lg['name']}* — code: `{lg['code']}` ({count} member{'s' if count != 1 else ''})")
        lines.append(f"_{names}_\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def masterleaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _is_rate_limited(update.effective_user.id):
        await update.message.reply_text("⏳ Slow down! Wait a moment and try again.")
        return
    text = _build_leaderboard_text("Master Leaderboard")
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("predict",           "Predict a match scoreline"),
        BotCommand("next",              "See the next 3 upcoming matches"),
        BotCommand("mypoints",          "Your score and stats"),
        BotCommand("winner",            "Pick your tournament winner (+10 pts)"),
        BotCommand("goldenboot",        "Pick the top scorer (+5 pts)"),
        BotCommand("goldenball",        "Pick the best player (+5 pts)"),
        BotCommand("leaderboard",       "Your league standings"),
        BotCommand("masterleaderboard", "Everyone across all leagues"),
        BotCommand("createleague",      "Create a new league"),
        BotCommand("joinleague",        "Join a league with a code"),
        BotCommand("myleague",          "See your leagues and share codes"),
        BotCommand("whopicked",         "See everyone's pick for a match"),
        BotCommand("fixtures",          "Full fixture list"),
        BotCommand("mypredictions",     "Review or cancel your picks"),
        BotCommand("remind",            "Set kickoff reminders"),
        BotCommand("digest",            "Daily match digest"),
        BotCommand("start",             "Welcome & setup"),
        BotCommand("ping",              "Check the bot is alive"),
    ])


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(set_commands).build()
    predict_conv = ConversationHandler(
        entry_points=[CommandHandler("predict", predict)],
        states={
            PICK_MATCH: [
                CallbackQueryHandler(predict_page_cb, pattern=r"^predict_page:\d+$"),
                CallbackQueryHandler(predict_pick_match_cb, pattern=r"^predict_match:.+$"),
            ],
            ENTER_SCORE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, predict_enter_score),
            ],
        },
        fallbacks=[CommandHandler("cancel", predict_cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(predict_conv)
    app.job_queue.run_repeating(check_reminders, interval=60, first=10)
    app.job_queue.run_repeating(send_daily_digest, interval=3600, first=20)
    app.job_queue.run_repeating(poll_results, interval=120, first=30)
    app.add_handler(CommandHandler("digest", digest))
    app.add_handler(CommandHandler("fixtures", fixtures))
    app.add_handler(CallbackQueryHandler(fixtures_cb, pattern=r"^fixtures:\d+$"))
    app.add_handler(CommandHandler("mypredictions", mypredictions))
    app.add_handler(CallbackQueryHandler(cancel_pred_cb, pattern=r"^cancel_pred:.+$"))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("masterleaderboard", masterleaderboard))
    app.add_handler(CallbackQueryHandler(leaderboard_global_cb, pattern=r"^leaderboard:global$"))
    app.add_handler(CallbackQueryHandler(leaderboard_league_cb, pattern=r"^leaderboard:league:\d+$"))
    app.add_handler(CommandHandler("createleague", createleague))
    app.add_handler(CommandHandler("joinleague", joinleague))
    app.add_handler(CommandHandler("myleague", myleague))
    app.add_handler(CommandHandler("mypoints", mypoints))
    app.add_handler(CommandHandler("winner", winner))
    app.add_handler(CommandHandler("goldenboot", goldenboot))
    app.add_handler(CommandHandler("goldenball", goldenball))
    app.add_handler(CommandHandler("setresult", setresult))
    app.add_handler(CommandHandler("next", next_matches))
    app.add_handler(CommandHandler("whopicked", whopicked))
    print("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()