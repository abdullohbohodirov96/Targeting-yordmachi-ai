"""
meta_api.py — Meta Marketing API (Facebook Graph API) bilan ishlash uchun
yengil wrapper. Tashqi og'ir SDK talab qilinmaydi, faqat `requests`.

KERAKLI RUXSATLAR (Meta tomonida):
- System User Access Token (Business Manager -> System Users), quyidagi
  permission'lar bilan: ads_management, ads_read, leads_retrieval (agar
  lead ma'lumotlarini olish kerak bo'lsa), pages_read_engagement (agar
  Instant Form yaratish/Page bilan ishlash kerak bo'lsa).
- Token shu Business Manager ostidagi O'ZINGIZNING reklama kabinetingiz va
  sahifangiz uchun to'liq ishlaydi — bu holatda Meta App Review shart emas.
  Agar boshqa birovning Page/Ad Account'iga ulanish kerak bo'lsa, Meta
  tomonidan qo'shimcha tekshiruv (App Review) talab qilinishi mumkin.
- Token muddati: uzoq muddatli System User token amalda muddatsiz ishlaydi
  (agar qo'lda bekor qilinmasa).

ESLATMA: Bu MVP kodi. Ishlab chiqarishga (production) chiqarishdan oldin:
  - Xatoliklarni qayta urinish (retry/backoff) mexanizmini kuchaytiring.
  - Rate limit (Meta har soatlik so'rov limiti bor) monitoringini qo'shing.
  - Har bir yozish amalini (pause/budget) alohida audit-log'ga yozing.
"""

import os
import json
import requests

GRAPH_API_VERSION = "v21.0"
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
AD_ACCOUNT_ID = os.environ.get("META_AD_ACCOUNT_ID", "")  # format: act_1234567890
PAGE_ID = os.environ.get("META_PAGE_ID", "")  # Facebook Page ID (ad creative uchun)


class MetaAPIError(Exception):
    pass


def _get(path: str, params: dict | None = None) -> dict:
    params = {
        k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
        for k, v in (params or {}).items()
    }
    params["access_token"] = ACCESS_TOKEN
    r = requests.get(f"{GRAPH_URL}/{path}", params=params, timeout=30)
    data = r.json()
    if "error" in data:
        raise MetaAPIError(data["error"])
    return data


def _post(path: str, data: dict) -> dict:
    # Graph API forma-encoded POST so'rovlarida object/array parametrlar
    # (targeting, creative, rename_options va h.k.) JSON-string ko'rinishida
    # yuborilishi kerak — shuning uchun dict/list qiymatlarni avtomatik
    # json.dumps() qilamiz.
    payload = {
        k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
        for k, v in data.items()
    }
    payload["access_token"] = ACCESS_TOKEN
    r = requests.post(f"{GRAPH_URL}/{path}", data=payload, timeout=30)
    result = r.json()
    if isinstance(result, dict) and "error" in result:
        raise MetaAPIError(result["error"])
    return result


# ---------------------------------------------------------------------------
# INSIGHTS (tahlil uchun ma'lumot olish)
# ---------------------------------------------------------------------------

DEFAULT_FIELDS = [
    "campaign_name", "adset_name", "ad_name",
    "spend", "cpm", "ctr", "cpc",
    "actions", "action_values", "cost_per_action_type",
    "reach", "frequency", "impressions",
]

# Video/kreativ engagement metrikalari — "video ko'rganlar soni", "necha foizi
# birinchi 15 soniyani ko'rdi" kabi savollarga javob berish uchun (4.12-bo'lim:
# Hook rate / Hold rate tashxisi shu metrikalarga asoslanadi).
VIDEO_FIELDS = [
    "video_play_actions",              # umumiy video play soni
    "video_avg_time_watched_actions",   # o'rtacha ko'rish davomiyligi (soniya)
    "video_p25_watched_actions",        # 25% ko'rganlar (taxminan Hook natijasi)
    "video_p50_watched_actions",
    "video_p75_watched_actions",
    "video_p95_watched_actions",
    "video_p100_watched_actions",       # oxirigacha ko'rganlar
    "video_thruplay_watched_actions",   # 15 soniya (yoki oxirigacha, qisqaroq bo'lsa) ko'rganlar — "Hold rate" uchun asosiy metrika
    "video_30_sec_watched_actions",
]

FULL_REPORTING_FIELDS = DEFAULT_FIELDS + VIDEO_FIELDS


def get_insights(
    level: str = "ad",              # "campaign" | "adset" | "ad"
    date_preset: str = "last_7d",
    breakdowns: list[str] | None = None,   # masalan ["region"]
    fields: list[str] | None = None,
) -> list[dict]:
    """Kampaniya/adset/ad darajasidagi statistikani qaytaradi.

    `breakdowns=["region"]` bersangiz — lidlar/xarajat qaysi hududdan
    kelayotganini ko'rish mumkin (4.11-bo'lim: hudud muammosini aniqlash uchun).
    """
    params = {
        "level": level,
        "date_preset": date_preset,
        "fields": ",".join(fields or DEFAULT_FIELDS),
        "limit": 200,
    }
    if breakdowns:
        params["breakdowns"] = ",".join(breakdowns)
    data = _get(f"{AD_ACCOUNT_ID}/insights", params)
    return data.get("data", [])


def get_full_report(
    level: str = "ad",
    date_preset: str = "last_7d",
    breakdowns: list[str] | None = None,
) -> list[dict]:
    """`get_insights()` bilan bir xil, lekin video/engagement metrikalarini ham
    qo'shib qaytaradi. Foydalanuvchi "video necha % odam ko'rgan", "hook rate
    qancha" kabi aniq metrika so'raganda ishlatiladi (orchestrator.answer_data_question)."""
    return get_insights(level=level, date_preset=date_preset, breakdowns=breakdowns, fields=FULL_REPORTING_FIELDS)


def get_active_ads(adset_id: str | None = None) -> list[dict]:
    path = f"{adset_id}/ads" if adset_id else f"{AD_ACCOUNT_ID}/ads"
    data = _get(path, {"fields": "id,name,status,adset_id,campaign_id", "limit": 200})
    return data.get("data", [])


def get_account_structure(active_only: bool = True) -> dict:
    """Kampaniya -> Adset -> Ad daraxtini FAQAT NOM va ID bilan qaytaradi (yengil).

    Bu funksiya juda muhim: foydalanuvchi Telegramda "AB | Traffic | IG" kabi
    o'ziga tanish NOM bilan buyruq beradi (hech kim Meta ID'ni yodlab yurmaydi).
    Targetolog action yaratishdan oldin shu ro'yxatdan mos nomni topib, haqiqiy
    `id`ni ishlatishi kerak — aks holda action bajarilmaydi.

    MUHIM: bu yerda ataylab `targeting` maydoni SO'RALMAYDI — ko'p sonli
    kampaniya/adset bo'lgan hisoblarda to'liq targeting'larni qo'shib yuborish
    Claude'ning kontekst limitidan (200k token) oshib ketishiga sabab bo'lgan.
    Bitta adset'ning to'liq targeting'i kerak bo'lsa, `get_adset_details()`ni
    faqat O'SHA BITTA adset uchun alohida chaqiring.

    `active_only=True` bo'lsa, arxivlangan/o'chirilgan (ARCHIVED/DELETED)
    obyektlar chiqarib tashlanadi — bu ham hajmni sezilarli kamaytiradi."""
    status_filter = {"effective_status": ["ACTIVE", "PAUSED"]} if active_only else None

    campaign_params = {"fields": "id,name,status,objective", "limit": 100}
    adset_params = {"fields": "id,name,status,campaign_id", "limit": 200}
    ad_params = {"fields": "id,name,status,adset_id,campaign_id", "limit": 200}
    if status_filter:
        campaign_params["filtering"] = [{"field": "effective_status", "operator": "IN", "value": status_filter["effective_status"]}]
        adset_params["filtering"] = campaign_params["filtering"]
        ad_params["filtering"] = campaign_params["filtering"]

    campaigns = _get(f"{AD_ACCOUNT_ID}/campaigns", campaign_params).get("data", [])
    adsets = _get(f"{AD_ACCOUNT_ID}/adsets", adset_params).get("data", [])
    ads = _get(f"{AD_ACCOUNT_ID}/ads", ad_params).get("data", [])
    return {"campaigns": campaigns, "adsets": adsets, "ads": ads}


def get_object_status(object_id: str) -> dict:
    """Ad/AdSet/Campaign'ning joriy holatini (status) qaytaradi. pause_object()/
    activate_object() dan keyin haqiqatan o'zgarganini TASDIQLASH uchun ishlatiladi
    — Meta ba'zan {"success": true} qaytarsa ham, holat kutilganidek o'zgarmagan
    bo'lishi mumkin (masalan yuqori darajadagi kampaniya/adset o'chiq bo'lsa)."""
    return _get(object_id, {"fields": "id,name,status,effective_status"})


def get_adset_details(adset_id: str) -> dict:
    """Bitta adset'ning to'liq sozlamalarini (targeting, byudjet va h.k.) qaytaradi.
    Targetolog `account_structure`dan kerakli adset'ni nom bo'yicha topgach, aynan
    o'sha bitta adset uchun bu funksiya chaqiriladi — barcha adsetlarning
    targeting'ini birdaniga yubormaslik uchun (token limitidan oshib ketmasligi uchun)."""
    return _get(adset_id, {"fields": "id,name,status,campaign_id,daily_budget,targeting,optimization_goal"})


# ---------------------------------------------------------------------------
# ON/OFF VA BYUDJET BOSHQARUVI
# ---------------------------------------------------------------------------

def pause_object(object_id: str) -> dict:
    """Ad, AdSet yoki Campaign'ni pauza qiladi."""
    return _post(object_id, {"status": "PAUSED"})


def activate_object(object_id: str) -> dict:
    """Ad, AdSet yoki Campaign'ni qayta ishga tushiradi."""
    return _post(object_id, {"status": "ACTIVE"})


def update_daily_budget(adset_id: str, new_daily_budget_cents: int) -> dict:
    """Byudjet Meta API'da eng kichik valyuta birligida (masalan tiyin/cent)
    beriladi. Masalan $10.00 -> 1000."""
    return _post(adset_id, {"daily_budget": new_daily_budget_cents})


def adjust_budget_by_percent(adset_id: str, current_daily_budget_cents: int, percent: float) -> dict:
    """4.4-bo'lim qoidasiga ko'ra: bir martada 10-20% oralig'ida o'zgartirish
    tavsiya etiladi. `percent` musbat (oshirish) yoki manfiy (kamaytirish)."""
    new_budget = int(current_daily_budget_cents * (1 + percent / 100))
    return update_daily_budget(adset_id, new_budget)


# ---------------------------------------------------------------------------
# AUDITORIYA / HUDUD SOZLAMALARI (4.11-bo'lim)
# ---------------------------------------------------------------------------

def _sanitize_targeting_for_write(targeting: dict) -> dict:
    """Meta Graph API'dan GET orqali o'qilgan targeting obyektida ba'zan
    yozib bo'lmaydigan/normalizatsiya qilinmaydigan qiymatlar uchraydi
    (masalan `targeting_automation.individual_setting` ichida kutilmagan
    kalit/qiymat, "Normalization does not allow the value ..." xatosi).
    Bunday obyektni o'zgarishsiz qaytarib yuborish Meta'dan "Invalid
    parameter" xatosiga olib keladi.

    Bu funksiya `targeting_automation.individual_setting`da FAQAT ma'lum,
    xavfsiz deb bilingan kalitlarni (age/gender/geo, qiymati 0 yoki 1)
    qoldiradi, qolganini olib tashlaydi. Original `targeting` obyekti
    o'zgartirilmaydi (nusxa qaytariladi)."""
    targeting = dict(targeting)
    automation = targeting.get("targeting_automation")
    if isinstance(automation, dict) and isinstance(automation.get("individual_setting"), dict):
        automation = dict(automation)
        safe_individual = {
            k: v for k, v in automation["individual_setting"].items()
            if k in ("age", "gender", "geo") and v in (0, 1)
        }
        if safe_individual:
            automation["individual_setting"] = safe_individual
        else:
            automation.pop("individual_setting", None)
        targeting["targeting_automation"] = automation
    return targeting


def set_location_current_city_only(adset_id: str, city_key: str) -> dict:
    """Ad Set targeting'ini faqat joriy shaharga cheklaydi va avtokengaytirishni
    o'chiradi ("Reach more people likely to respond" -> off)."""
    targeting = {
        "geo_locations": {
            "cities": [{"key": city_key, "radius": 0, "distance_unit": "kilometer"}],
            "location_types": ["home"],  # faqat shu shaharda yashovchilar
        },
        "targeting_automation": {"advantage_audience": 0},  # auto-expansion off
    }
    return _post(adset_id, {"targeting": _sanitize_targeting_for_write(targeting)})


def update_targeting(adset_id: str, targeting: dict) -> dict:
    """Ad Set auditoriyasini to'liq yangi targeting spec bilan almashtiradi.
    Yozishdan oldin avtomatik ravishda xavfsizlashtiriladi (`_sanitize_targeting_for_write`)."""
    return _post(adset_id, {"targeting": _sanitize_targeting_for_write(targeting)})


def search_geo_location(query: str, location_types: list[str] | None = None) -> list[dict]:
    """Erkin matndagi joy nomini (masalan 'Chirchiq', 'Zangiota tumani') Meta'ning
    rasmiy geo-target kaliti va turiga bog'laydi. Bir nechta nomzod qaytishi mumkin
    (bir xil nomli joylar turli davlatlarda bo'lishi mumkin) — Targetolog davlat/
    kontekstga qarab eng mosini tanlashi kerak. Natija elementlari odatda:
    {"key": "...", "name": "...", "type": "city"|"region"|"country"|..., "country_code": "UZ", ...}
    Bu funksiyasiz shahar/tuman nomlarini exclude/include qilib bo'lmaydi — Meta
    faqat raqamli `key` bilan ishlaydi, nom bilan emas."""
    params = {"type": "adgeolocation", "q": query}
    if location_types:
        params["location_types"] = location_types
    data = _get("search", params)
    return data.get("data", [])


# ---------------------------------------------------------------------------
# YANGI KAMPANIYA/ADSET/AD YARATISH (targetni "o'zi to'liq yoqishi" uchun)
# ---------------------------------------------------------------------------

def create_campaign(
    name: str,
    objective: str = "OUTCOME_LEADS",   # OUTCOME_LEADS | OUTCOME_SALES | OUTCOME_ENGAGEMENT | OUTCOME_TRAFFIC
    status: str = "PAUSED",
    special_ad_categories: list | None = None,
) -> dict:
    return _post(f"{AD_ACCOUNT_ID}/campaigns", {
        "name": name,
        "objective": objective,
        "status": status,
        "special_ad_categories": special_ad_categories or [],
    })


def create_adset(
    campaign_id: str,
    name: str,
    daily_budget_cents: int,
    targeting: dict,
    optimization_goal: str = "OFFSITE_CONVERSIONS",
    billing_event: str = "IMPRESSIONS",
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP",
    status: str = "PAUSED",
    promoted_object: dict | None = None,
) -> dict:
    """Bo'lim 4.2-4.3 qoidalariga mos targeting spec bilan yangi Ad Set yaratadi.

    `targeting` namunasi (broad, faqat yosh/jins/hudud — 4.2-bo'lim tavsiyasiga ko'ra):
    {
        "geo_locations": {"cities": [{"key": "2430536", "radius": 0, "distance_unit": "kilometer"}]},
        "age_min": 18, "age_max": 65,
        "targeting_automation": {"advantage_audience": 1}
    }
    """
    payload = {
        "name": name,
        "campaign_id": campaign_id,
        "daily_budget": daily_budget_cents,
        "targeting": targeting,
        "optimization_goal": optimization_goal,
        "billing_event": billing_event,
        "bid_strategy": bid_strategy,
        "status": status,
    }
    if promoted_object:
        payload["promoted_object"] = promoted_object
    return _post(f"{AD_ACCOUNT_ID}/adsets", payload)


def create_ad(adset_id: str, name: str, creative_id: str, status: str = "PAUSED") -> dict:
    """Mavjud creative_id'dan foydalanib reklama yaratadi. AI video/rasm generatsiya
    qila olmaydi — creative_id avvaldan Ads Manager'da yuklangan bo'lishi kerak."""
    return _post(f"{AD_ACCOUNT_ID}/ads", {
        "name": name,
        "adset_id": adset_id,
        "creative": {"creative_id": creative_id},
        "status": status,
    })


# ---------------------------------------------------------------------------
# A/B TEST (Meta'ning native "copies" funksiyasi orqali)
# ---------------------------------------------------------------------------

def copy_adset(adset_id: str, rename_suffix: str = " - B variant", status_option: str = "PAUSED") -> dict:
    """Ad Set'ni nusxalaydi — A/B test uchun B variantini yaratish uchun ishlatiladi.
    Nusxalangach, `update_targeting()` yoki yangi creative bilan `create_ad()`
    orqali B variantda faqat BITTA o'zgaruvchini (masalan auditoriya turi yoki
    kreativ) farqlantiring — qolgan hammasi bir xil bo'lishi kerak (toza test)."""
    return _post(f"{adset_id}/copies", {
        "rename_options": {
            "rename_suffix": rename_suffix,
            "rename_strategy": "ONLY_TOP_LEVEL_RENAME",
        },
        "status_option": status_option,
    })


# ---------------------------------------------------------------------------
# INSTANT FORMS / LEAD ADS (4.9-bo'lim)
# ---------------------------------------------------------------------------

def create_lead_form(page_id: str, form_config: dict) -> dict:
    """Instant Form (Lead Ads) yaratadi.

    form_config namunasi:
    {
        "name": "Kurs uchun lid formasi",
        "intro": {"headline": "IELTS 7+ bo'lishni xohlaysizmi?", "description": "..."},
        "questions": [
            {"type": "FULL_NAME"},
            {"type": "PHONE"},
            {"type": "CUSTOM", "key": "hudud", "label": "Qaysi shahardansiz?"},
        ],
        "privacy_policy": {"url": "https://example.com/privacy"},
        "thank_you_page": {"title": "Rahmat!", "body": "Tez orada bog'lanamiz."},
    }
    """
    return _post(f"{page_id}/leadgen_forms", form_config)


def get_leads(form_id: str) -> list[dict]:
    """Formadan tushgan lidlarni qaytaradi (leads_retrieval permission talab
    qilinadi). Lead sifatini tahlil qilish (4.10-bo'lim) uchun ishlatiladi."""
    data = _get(f"{form_id}/leads", {"fields": "field_data,created_time"})
    return data.get("data", [])
