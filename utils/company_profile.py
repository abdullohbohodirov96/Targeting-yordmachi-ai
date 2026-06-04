"""
Kompaniya profili — saqlash, yuklash, AI kontekst uchun formatlash.
"""
import json
import os
from utils.logger import logger

PROFILE_PATH = "data/company_profile.json"

DEFAULT_PROFILE = {
    "name": None,
    "industry": None,
    "products": None,
    "target_audience": None,
    "goals": None,
    "location": "O'zbekiston",
    "monthly_budget": None,
    "is_setup": False,
}


def load_profile() -> dict:
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(PROFILE_PATH):
        return DEFAULT_PROFILE.copy()
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Company profile yuklashda xato: {e}")
        return DEFAULT_PROFILE.copy()


def save_profile(profile: dict):
    os.makedirs("data", exist_ok=True)
    try:
        with open(PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Company profile saqlashda xato: {e}")


def get_profile_context() -> str:
    """AI system prompt uchun kompaniya kontekstini formatlaydi."""
    profile = load_profile()
    if not profile.get("is_setup"):
        return ""
    lines = ["KOMPANIYA PROFILI:"]
    field_labels = {
        "name": "Nomi",
        "industry": "Soha",
        "products": "Mahsulot/Xizmatlar",
        "target_audience": "Maqsadli auditoriya",
        "goals": "Reklama maqsadi",
        "location": "Joylashuv",
        "monthly_budget": "Oylik byudjet",
    }
    for key, label in field_labels.items():
        val = profile.get(key)
        if val:
            lines.append(f"* {label}: {val}")
    return "\n".join(lines)


def is_profile_setup() -> bool:
    return load_profile().get("is_setup", False)


def get_company_name() -> str:
    profile = load_profile()
    return profile.get("name") or "Kompaniyangiz"
