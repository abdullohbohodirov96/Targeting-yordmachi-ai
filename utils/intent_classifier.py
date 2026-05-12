"""
Natural Language Intent Classifier.
Ruxsat etilgan intentlar:
- CREATIVE_TASK (Marketing yordam, AI)
- META_STATS (Statistika)
- META_ACTION (O'zgartirishlar, pause, budget, vs)
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

    # 2. CREATIVE / MARKETING (AI Advice)
    creative_keywords = [
        "creative", "kreativ", "ssenariy", "reels", "hook", "caption", 
        "matn", "reklama matni", "g'oya", "idea", "yozib ber", "tuzib ber", 
        "qilib ber", "maslahat ber", "audience ber", "target setting ber"
    ]
    if any(kw in text_lower for kw in creative_keywords):
        return "CREATIVE_TASK"

    # 3. META_STATS (Statistika)
    stats_keywords = [
        "statistika", "hisobot", "report", "natija", "bugun", "kecha", "hafta", "oy"
    ]
    if any(kw in text_lower for kw in stats_keywords):
        return "META_STATS"

    # 4. META_ACTION (O'zgartirishlar - strictly for Meta objects)
    # "qil" so'zi judayam ko'p uchraydi, uni olib tashlaymiz yoki faqat kombinatsiyada qoldiramiz
    action_keywords = [
        "o'chir", "pause qil", "to'xtat", "yoq", "active qil", "enable qil",
        "budgetni oshir", "budgetni kamaytir", "budget qo'y",
        "copy qil", "duplicate qil", "nusxa ol", "clone qil",
        "yarat", "och", "new", "yangi ad set", "yangi campaign"
    ]
    # "create" o'rniga "create " (space bilan) yoki boshqa usul
    if any(kw in text_lower for kw in action_keywords) or "create" in text_lower.split():
        return "META_ACTION"

    # 5. OBJECT_SEARCH (Faqat aniq buyruqlar)
    search_prefixes = [
        "adset qidir:", "campaign qidir:", "ads qidir:", "reklamani top:"
    ]
    if any(text_lower.startswith(prefix) for prefix in search_prefixes):
        return "OBJECT_SEARCH"

    # 6. Default
    return "AI_CHAT"
