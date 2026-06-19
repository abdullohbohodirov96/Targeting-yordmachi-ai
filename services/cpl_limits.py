"""
CPL limit boshqaruvi.
Har bir kampaniyaga max CPL limit qo'yiladi.
Limit oshsa kampaniya avtomatik to'xtatiladi.
"""
import json
import os
from utils.logger import logger

CPL_LIMITS_FILE = "cpl_limits.json"
SEEN_CAMPAIGNS_FILE = "seen_campaigns.json"


def _load_file(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Fayl o'qishda xato ({path}): {e}")
        return {}


def _save_file(path: str, data: dict):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Fayl saqlashda xato ({path}): {e}")


# === CPL LIMITS ===

def get_all_limits() -> dict:
    return _load_file(CPL_LIMITS_FILE)


def get_limit(campaign_id: str) -> float | None:
    limits = _load_file(CPL_LIMITS_FILE)
    entry = limits.get(str(campaign_id))
    if entry:
        return entry.get("cpl_limit")
    return None


def set_limit(campaign_id: str, campaign_name: str, cpl_limit: float):
    limits = _load_file(CPL_LIMITS_FILE)
    limits[str(campaign_id)] = {
        "campaign_name": campaign_name,
        "cpl_limit": cpl_limit,
    }
    _save_file(CPL_LIMITS_FILE, limits)
    logger.info(f"CPL limit o'rnatildi: {campaign_name} → ${cpl_limit}")


def remove_limit(campaign_id: str):
    limits = _load_file(CPL_LIMITS_FILE)
    removed = limits.pop(str(campaign_id), None)
    _save_file(CPL_LIMITS_FILE, limits)
    if removed:
        logger.info(f"CPL limit o'chirildi: {removed.get('campaign_name')}")


# === SEEN CAMPAIGNS (yangi kampaniyalarni track qilish) ===

def get_seen_campaigns() -> set:
    data = _load_file(SEEN_CAMPAIGNS_FILE)
    return set(data.get("ids", []))


def mark_campaign_seen(campaign_id: str):
    data = _load_file(SEEN_CAMPAIGNS_FILE)
    ids = set(data.get("ids", []))
    ids.add(str(campaign_id))
    data["ids"] = list(ids)
    _save_file(SEEN_CAMPAIGNS_FILE, data)


def get_new_campaigns(current_campaigns: list) -> list:
    """Avval ko'rilmagan faol kampaniyalarni qaytaradi."""
    seen = get_seen_campaigns()
    new_ones = []
    for c in current_campaigns:
        cid = str(c.get("id", ""))
        if cid and cid not in seen:
            new_ones.append(c)
    return new_ones
