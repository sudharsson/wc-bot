
"""
Step 3 — load fixtures into the `matches` table (run once; safe to re-run).
Downloads the public-domain openfootball World Cup 2026 schedule, converts each
kickoff to UTC, and upserts into Supabase.
 
Run:
    pip install requests
    python load_fixtures.py
"""
 
import os
import re
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

DATA_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

db = create_client(SUPABASE_URL, SUPABASE_KEY)
 
 
def to_utc(date_str, time_str):
    """'2026-06-11' + '13:00 UTC-6' -> aware UTC datetime."""
    m = re.match(r"(\d{1,2}:\d{2})\s*UTC([+-]\d+)", time_str.strip())
    if not m:
        return None
    hhmm, offset_h = m.group(1), int(m.group(2))
    local = datetime.strptime(f"{date_str} {hhmm}", "%Y-%m-%d %H:%M")
    # local = UTC + offset, so UTC = local - offset
    return (local - timedelta(hours=offset_h)).replace(tzinfo=timezone.utc)
 
 
def stage_from_round(rnd):
    r = rnd.lower()
    if "final" in r and "quarter" not in r and "semi" not in r:
        return "final"
    if "semi" in r:
        return "sf"
    if "quarter" in r:
        return "qf"
    if "round of 16" in r or "16" in r:
        return "ro16"
    if "round of 32" in r or "32" in r:
        return "ro32"
    return "group"
 
 
def main():
    print("Downloading fixtures...")
    data = requests.get(DATA_URL, timeout=30).json()
    matches = data.get("matches", [])
    print(f"Found {len(matches)} matches.")
 
    rows = []
    for i, m in enumerate(matches, start=1):
        kickoff = to_utc(m.get("date", ""), m.get("time", ""))
        rows.append({
            "id": f"m{i:03d}",
            "team1": m.get("team1"),
            "team2": m.get("team2"),
            "kickoff_utc": kickoff.isoformat() if kickoff else None,
            "stage": stage_from_round(m.get("round", "")),
            "status": "scheduled",
        })
 
    db.table("matches").upsert(rows).execute()
    print(f"Loaded {len(rows)} matches into Supabase ✅")
    # show a couple as a sanity check
    for r in rows[:3]:
        print(" ", r["id"], r["team1"], "v", r["team2"], "@", r["kickoff_utc"], f"({r['stage']})")
 
 
if __name__ == "__main__":
    main()
