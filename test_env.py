import os
from dotenv import load_dotenv

load_dotenv()  # reads the .env file into the environment

print("BOT_TOKEN starts with:", os.environ["BOT_TOKEN"][:10], "...")
print("SUPABASE_URL:", os.environ["SUPABASE_URL"])
print("SUPABASE_KEY starts with:", os.environ["SUPABASE_KEY"][:12], "...")
print("All three secrets loaded ✅")