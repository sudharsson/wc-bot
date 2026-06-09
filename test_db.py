from supabase import create_client

# Paste your two values from Supabase Settings -> API:
SUPABASE_URL = "https://hamdfegumgskkhnvbgqn.supabase.co"      # https://xxxx.supabase.co
SUPABASE_KEY = "sb_publishable_y8WYb03AszvXc_8dqbVy9A_dyA1_fVV"         # the long eyJ... string

db = create_client(SUPABASE_URL, SUPABASE_KEY)

# 1. Write a fake user row
db.table("users").upsert({
    "telegram_id": 999,
    "name": "Test User"
}).execute()
print("Wrote test user.")

# 2. Read it back
result = db.table("users").select("*").eq("telegram_id", 999).execute()
print("Read back:", result.data)

# 3. Clean up — delete the test row
db.table("users").delete().eq("telegram_id", 999).execute()
print("Deleted test user. Connection works ✅")
