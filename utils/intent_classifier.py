"""
Aqlli Natural Language Intent Classifier.
O'zbek, Rus va Ingliz tillarida ishlaydi.
Har qanday so'z shaklini tushunadi.

Intentlar:
- SEND_TO_GROUP  : Guruhga xabar yuborish
- CREATIVE_TASK  : Marketing/kreativ yordam
- META_STATS     : Statistika va hisobotlar
- META_ACTION    : Kampaniya boshqaruvi (pause, enable, budget)
- OBJECT_SEARCH  : Kampaniya/adset/reklama qidirish
- AI_CHAT        : Umumiy savol-javob
"""


def detect_intent(text: str) -> str:
    t = text.lower().strip()

    # ── 1. SEND_TO_GROUP (eng yuqori prioritet) ─────────────────────────
    group_kw = [
        "guruhga yoz", "guruhga tashla", "guruhga yubor", "guruhga chiqar",
        "guruhga e'lon", "guruhga post", "send to group", "post qil",
        "kanalga yoz", "kanalga tashla", "publiklash", "publish qil",
        "guruhga jo'nat", "guruhga berish", "hammaga yoz",
    ]
    if any(kw in t for kw in group_kw):
        return "SEND_TO_GROUP"

    # ── 2. META_ACTION (aniq harakat so'zlari — yuqori prioritet) ───────
    # "pause", "o'chir", "yoq", "budget", "copy" kabi qat'iy harakat so'zlari
    action_kw = [
        # Pause / O'chirish
        "o'chir", "o'chirish", "o'chirib", "ochirsin", "o'chirilsin",
        "pauza", "pause qil", "pause ber", "pauselan", "to'xtat", "to'xtatish",
        "stop qil", "stopla", "stoplan",
        # Enable / Yoqish
        "yoq", "yoqish", "yoqilsin", "qayta yoq", "active qil", "aktivlashtir",
        "enable qil", "ishga tushir", "run qil", "launchla",
        # Budget
        "budget qo'y", "budjetni oshir", "budgetni oshir", "budgetni kamaytir",
        "budjetni kamaytir", "budget o'zgartir", "budjetni o'zgartir",
        "budget bel", "byudjet qo'y", "$ qil", "dollar qil", "budget yoz",
        # Copy / Duplicate
        "copy qil", "duplicate qil", "nusxa ol", "clone qil", "ko'paytir",
        "nusxala", "dublikat", "copy ber",
        # Create
        "yangi adset yarat", "yangi kampaniya yarat", "yangi reklama yarat",
        "yangi target yarat", "yaratib ber",
    ]
    if any(kw in t for kw in action_kw):
        return "META_ACTION"

    # "X ni o'chir" yoki "X targetni yoq" pattern — regex-less approach
    # Agar "create" alohida so'z bo'lsa (not inside "creative")
    words = t.split()
    if "create" in words:
        return "META_ACTION"

    # ── 3. CREATIVE_TASK ────────────────────────────────────────────────
    creative_kw = [
        "creative", "kreativ", "kreatif",
        "ssenariy", "skript", "script", "stsenariy",
        "reels", "rils", "tiktok", "shorts",
        "hook", "xuk", "caption", "kepshn",
        "matn yoz", "matn yozib", "reklama matni", "ad matn",
        "g'oya ber", "idea ber", "g'oyalar", "ideyalar",
        "yozib ber", "tuzib ber", "qilib ber",
        "maslahat ber", "tavsiya ber",
        "ad copy", "content plan", "kontentplan",
        "dm script", "dm skript", "sales script",
        "oferta yoz", "taklifnoma",
        "taglayn", "slogan", "headline",
        "post yoz", "post tayyorla", "hikoya yoz",
        "reklama matni", "reklama yoz",
        "targeting maslahat", "audience maslahat",
    ]
    if any(kw in t for kw in creative_kw):
        return "CREATIVE_TASK"

    # ── 4. META_STATS ───────────────────────────────────────────────────
    stats_kw = [
        "statistika", "statka", "stats",
        "hisobot", "report", "repport",
        "natija", "natijalar", "ko'rsatkich", "performance",
        "bugun", "kecha", "hafta", "oy", "oylik", "haftalik",
        "spend", "xarajat", "sarflash",
        "cpl", "ctr", "cpm", "roas", "roi",
        "leads", "lead soni", "lid",
        "kampaniya natija", "reklama natija", "ads natija",
        "qancha ketdi", "qancha ishlandi", "pul sarflandi",
        # Russian
        "статистика", "отчет", "результат",
        "сегодня", "вчера", "неделю", "месяц",
    ]
    if any(kw in t for kw in stats_kw):
        return "META_STATS"

    # ── 5. OBJECT_SEARCH ────────────────────────────────────────────────
    # Aniq prefikslar
    search_prefixes = [
        "adset qidir:", "campaign qidir:", "ads qidir:",
        "reklamani top:", "target qidir:", "kampaniya qidir:",
        "reklama qidir:", "adset top:", "kampaniyani top:",
    ]
    if any(t.startswith(p) for p in search_prefixes):
        return "OBJECT_SEARCH"

    # Tabiiy til qidiruv: qidiruv fe'li bor bo'lsa
    search_verbs = [
        "qidir", "qidiring", "topla", "topib ber", "toping",
        "izla", "izlab ber", "search", "topt",
        "ko'rsat", "chiqar", "listini ber", "ro'yxat",
        "list", "listing", "barchasi", "hammasi",
        "qaysilar", "qaysi bor", "nechta bor",
    ]
    has_search_verb = any(sv in t for sv in search_verbs)

    obj_words = [
        "campaign", "kampaniya", "kampaniyalar",
        "adset", "ad set", "adsetlar",
        "reklama", "reklamalar", "ads",
        "target", "targetlar",
    ]
    has_obj_word = any(ow in t for ow in obj_words)

    # Qidiruv fe'li yoki (ob'ekt + ko'rsatish so'zi)
    if has_search_verb:
        # Agar stats so'zlari ham bo'lsa — stats ustunlik
        stats_in_text = any(kw in t for kw in stats_kw)
        if not stats_in_text:
            return "OBJECT_SEARCH"

    if has_obj_word and any(sv in t for sv in ["ko'rsat", "chiqar", "list", "barchasi"]):
        return "OBJECT_SEARCH"

    # ── 6. AI_CHAT (default) ────────────────────────────────────────────
    return "AI_CHAT"


def extract_search_params(text: str) -> tuple[str, str]:
    """
    Tabiiy tildan qidiruv so'zi va ob'ekt turini ajratadi.
    Returns: (query, obj_type)
    obj_type: "campaigns" | "adsets" | "ads"
    """
    t = text.lower().strip()

    # Ob'ekt turini aniqlash
    obj_type = "campaigns"  # default
    if any(w in t for w in ["adset", "ad set", "adsetlar"]):
        obj_type = "adsets"
    elif any(w in t for w in ["kampaniya", "campaign", "kampaniyalar"]):
        obj_type = "campaigns"
    elif any(w in t for w in ["reklama", "ads", "reklamalar", "ad "]):
        obj_type = "ads"

    # Prefikslarni olib tashlash
    prefixes = [
        "adset qidir:", "campaign qidir:", "ads qidir:",
        "reklamani top:", "target qidir:", "kampaniya qidir:",
        "reklama qidir:", "adset top:", "kampaniyani top:",
    ]
    for p in prefixes:
        if t.startswith(p):
            return t.replace(p, "").strip(), obj_type

    # Qidiruv fe'llari va ob'ekt so'zlarini olib tashlash
    remove_words = [
        "qidir", "topla", "topib ber", "toping", "izla", "search",
        "ko'rsat", "chiqar", "listini ber", "ro'yxat", "list",
        "barchasi", "hammasi", "qaysilar",
        "adset", "ad set", "campaign", "kampaniya", "reklama", "ads", "target",
        "ni", "ni ", "ga", "dan", "dagi", "larni", "lardan",
        "ber", "bering", "qilib", "qiling",
    ]
    query = t
    for w in remove_words:
        query = query.replace(w, " ")
    query = " ".join(query.split()).strip()

    return query, obj_type
