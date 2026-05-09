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
REPORT_HOURS = [9]

# === ADMIN REPORT SCHEDULER ===
# Env: ADMIN_REPORT_TIMES=09:00,13:00,18:00
_admin_times_raw = os.getenv("ADMIN_REPORT_TIMES", "09:00,13:00,18:00")
ADMIN_REPORT_TIMES = []
for t in _admin_times_raw.split(","):
    t = t.strip()
    if ":" in t:
        parts = t.split(":")
        ADMIN_REPORT_TIMES.append({"hour": int(parts[0]), "minute": int(parts[1])})
# === MONITORING THRESHOLDS ===
CPL_MULTIPLIER_ALERT = float(os.getenv("CPL_MULTIPLIER_ALERT", 2.0))
CTR_MIN_ALERT = float(os.getenv("CTR_MIN_ALERT", 1.0))
FREQUENCY_MAX_ALERT = float(os.getenv("FREQUENCY_MAX_ALERT", 2.5))
CPM_INCREASE_ALERT = float(os.getenv("CPM_INCREASE_ALERT", 1.5))

# ALERT SPAM FILTER (Hours)
ALERT_COOLDOWN_HOURS = 3
