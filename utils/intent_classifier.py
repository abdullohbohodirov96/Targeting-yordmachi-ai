"""
Natural Language Intent Classifier.
Ruxsat etilgan intentlar:
- CREATIVE_TASK (Marketing yordam, AI)
- META_STATS (Statistika)
- META_ACTION (O'zgartirishlar, pause, budget, vs)
- CPL_LIMIT (CPL limit o'rnatish/ko'rish)
- OBJECT_SEARCH (Faqat aniq qidiruv buyruqlari)
- AI_CHAT (Qolgan holatlar)
"""

def detect_intent(text: str) -> str:
    text_lower = text.lower()

    # 1. SEND_TO_GROUP (Guruhga xabar yuborish / Task) - Highest Priority
    group_keywords = [
        "guruhga yoz", "guruhga tashla", "guruhga yubor", "send to group", "post qil", "kanalga yoz",
        "vazifa", "topshiriq"
    ]
    if any(kw in text_lower for kw in group_keywords):
        return "SEND_TO_GROUP"

    # 2. CPL_LIMIT (Limit o'rnatish/ko'rish) - HIGH PRIORITY
    limit_keywords = [
        "limit", "cpl limit", "max cpl", "max limit", "limit qo'y", "limit qoy",
        "limit belgi", "limit o'rnat", "limit ornat", "limit bel",
        "limit ko'r", "limit kor", "limitni ko'r", "limitni kor",
        "limitlar", "qancha limit", "nechi limit", "limit necha",
        "limit oq", "limit och", "necha dollar limit", "dollar limit",
        "target limit", "kampaniya limit", "cpl max", "max cpl",
    ]
    if any(kw in text_lower for kw in limit_keywords):
        return "CPL_LIMIT"

    # 3. CREATIVE / MARKETING (AI Advice)
    creative_keywords = [
        "creative", "kreativ", "ssenariy", "reels", "hook", "caption",
        "matn", "reklama matni", "g'oya", "idea", "yozib ber", "tuzib ber",
        "qilib ber", "maslahat ber", "audience ber", "target setting ber"
    ]
    if any(kw in text_lower for kw in creative_keywords):
        return "CREATIVE_TASK"

    # 4. META_STATS (Statistika)
    stats_keywords = [
        "statistika", "hisobot", "report", "natija", "bugun", "kecha", "hafta", "oy"
    ]
    if any(kw in text_lower for kw in stats_keywords):
        return "META_STATS"

    # 5. META_ACTION (O'zgartirishlar - strictly for Meta objects)
    action_keywords = [
        "o'chir", "pause qil", "to'xtat", "yoq", "active qil", "enable qil",
        "budgetni oshir", "budgetni kamaytir", "budget qo'y",
        "copy qil", "duplicate qil", "nusxa ol", "clone qil",
        "yarat", "och", "new", "yangi ad set", "yangi campaign"
    ]
    if any(kw in text_lower for kw in action_keywords) or "create" in text_lower.split():
        return "META_ACTION"

    # 6. OBJECT_SEARCH (Faqat aniq buyruqlar)
    search_prefixes = [
        "adset qidir:", "campaign qidir:", "ads qidir:", "reklamani top:"
    ]
    if any(text_lower.startswith(prefix) for prefix in search_prefixes):
        return "OBJECT_SEARCH"

    # 7. Default
    return "AI_CHAT"
