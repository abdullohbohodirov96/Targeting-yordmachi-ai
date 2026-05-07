import os
from dotenv import load_dotenv

load_dotenv()

# === MAJBURIY ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

# === TELEGRAM ===
GROUP_ID = os.getenv("GROUP_ID")
try:
    GROUP_ID = int(GROUP_ID) if GROUP_ID else None
except Exception:
    pass

ADMIN_ID = os.getenv("ADMIN_ID")
try:
    ADMIN_ID = int(ADMIN_ID) if ADMIN_ID else None
except Exception:
    ADMIN_ID = None

# === META ADS ===
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")
META_API_VERSION = "v19.0"
META_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"

# === OPENAI ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# === GOOGLE SHEETS ===
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON") # Sheets API uchun

# === SCHEDULER ===
TIMEZONE = "Asia/Tashkent"
REPORT_HOURS = [9, 15, 21]
