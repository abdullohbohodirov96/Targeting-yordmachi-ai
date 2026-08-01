"""
orchestrator.py — Targetolog + Marketolog ikki agentli tsiklni boshqaradi.

Oqim:
  1. Meta Marketing API'dan so'nggi ma'lumotlarni (insights + region breakdown) ol.
  2. Targetolog agent (Claude) shu ma'lumotni tahlil qilib, action_plan (JSON) beradi.
  3. Marketolog agent (Claude) action_plan'ni biznes qoidalariga solishtirib
     tekshiradi, har bir action uchun approved/rejected/edited qaror chiqaradi.
  4. Faqat tasdiqlangan action'lar meta_api.py orqali haqiqiy hisobda bajariladi.
  5. Har bir tsikl natijasi logs/run_<timestamp>.json fayliga yoziladi va
     Telegram uchun inson o'qiydigan hisobot qaytariladi.

ISHGA TUSHIRISH:
    pip install anthropic requests
    export ANTHROPIC_API_KEY=...
    export META_ACCESS_TOKEN=...
    export META_AD_ACCOUNT_ID=act_...
    python orchestrator.py          # bitta marta tahlil tsiklini ishga tushiradi
"""

import os
import re
import json
import logging
import concurrent.futures
from pathlib import Path
from datetime import datetime, timedelta

import anthropic
import requests

import meta_api
import budget_tracker
import kv_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

BASE_DIR = Path(__file__).parent
AGENTS_DIR = BASE_DIR / "agents"

# MUHIM (Vercel/serverless muhitlar uchun): loyiha papkasi (BASE_DIR) serverless
# funksiyada FAQAT O'QISH uchun ochiq — yozish (mkdir/write) imkonsiz bo'lishi
# mumkin ("Read-only file system" xatosi, bu butun modulni import qilishda
# ko'tarilib, HAR BIR so'rovni "FUNCTION_INVOCATION_FAILED" bilan buzadi).
# Shuning uchun avval BASE_DIR/logs'ga yozishga urinamiz (VPS/mahalliy uchun —
# haqiqiy, doimiy log), muvaffaqiyatsiz bo'lsa /tmp'ga qaytamiz (Vercel'da
# yagona yoziladigan joy — instance ichida vaqtinchalik, lekin dastur
# yiqilib qolmaydi).
import tempfile as _tempfile

LOGS_DIR = BASE_DIR / "logs"
try:
    LOGS_DIR.mkdir(exist_ok=True)
except OSError:
    LOGS_DIR = Path(_tempfile.gettempdir()) / "target_master_logs"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

KNOWLEDGE_BASE = (BASE_DIR / "target_master_agent.md").read_text(encoding="utf-8")
TARGETOLOG_ROLE = (AGENTS_DIR / "targetolog_system_prompt.md").read_text(encoding="utf-8")
MARKETOLOG_ROLE = (AGENTS_DIR / "marketolog_system_prompt.md").read_text(encoding="utf-8")
ACTION_SCHEMA = (AGENTS_DIR / "action_schema.md").read_text(encoding="utf-8")
BUSINESS_RULES = json.loads((BASE_DIR / "business_rules.json").read_text(encoding="utf-8"))

TARGETOLOG_SYSTEM = f"{TARGETOLOG_ROLE}\n\n---\n\n# BILIM BAZASI\n\n{KNOWLEDGE_BASE}\n\n---\n\n{ACTION_SCHEMA}"
MARKETOLOG_SYSTEM = f"{MARKETOLOG_ROLE}\n\n---\n\n{ACTION_SCHEMA}"

# MODEL TANLASH STRATEGIYASI (xarajatni balanslash uchun -- ataylab qilingan qaror):
#   - MODEL (Sonnet) -- FAQAT HAQIQIY vazifa/qaror yaratish uchun: Targetolog
#     action_plan tuzganda (yangi kampaniya, byudjet/auditoriya o'zgarishi,
#     murakkab tashxis) va Marketolog tekshiruvida. Bu joylarda chuqur
#     mulohaza va bilim bazasiga tayanish kerak -- shuning uchun Anthropic
#     ishlatiladi va FAQAT shu yerda ishlatiladi.
#   - Boshqa HAMMA narsa -- intent aniqlash, oddiy metrika savoliga real
#     raqamlar bilan javob berish (`answer_data_question`), davr/sana
#     aniqlash (`_resolve_query_period`), byudjet xabarini tushunish, kunlik
#     hisobotlar va oddiy erkin suhbat -- FAQAT OpenAI orqali ishlaydi
#     (`call_light`/`call_light_chat`). Bular "vazifa yaratish" emas, faqat
#     o'qish/tushuntirish -- Anthropic API xarajatini bu yerda umuman
#     sarflamaslik uchun Claude'ga fallback ATAYLAB OLIB TASHLANGAN: agar
#     `OPENAI_API_KEY` sozlanmagan yoki OpenAI so'rovi xato bersa, funksiya
#     xato qaytaradi (Claude Haiku'ga sirli tushib qolmaydi) -- chaqiruvchi
#     joy buni ushlab, foydalanuvchiga tushunarli xabar ko'rsatadi.
MODEL = "claude-sonnet-4-5"
LIGHT_MODEL = "claude-haiku-4-5-20251001"  # endi ishlatilmaydi -- moslik uchun saqlangan
INTENT_MODEL = LIGHT_MODEL  # eski nom -- moslik uchun saqlangan
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# OpenAI -- YENGIL so'rovlarning YAGONA manbasi (intent aniqlash, metrika
# savoliga javob, davr/sana aniqlash, oddiy suhbat, byudjet xabarini
# tushunish, kunlik hisobotlar). Fallback yo'q -- OPENAI_API_KEY majburiy
# sozlanishi kerak, aks holda shu yo'nalishdagi so'rovlar xato beradi.
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def call_light(system_prompt: str, user_content: str, max_tokens: int = 500) -> str:
    """Bitta-turli (single-turn) YENGIL chaqiruv: intent aniqlash, byudjet
    xabarini tushunish, metrika savoliga javob berish, kunlik hisobotlar --
    shularning barchasi FAQAT OpenAI orqali ishlaydi (Anthropic API
    xarajatini yengil/oddiy so'rovlarda sarflamaslik uchun, ataylab qilingan
    qaror). `OPENAI_API_KEY` sozlanmagan yoki OpenAI so'rovi xato bersa --
    Claude'ga tushib qolinmaydi, xato yuqoriga uzatiladi (chaqiruvchi
    funksiya buni ushlab, foydalanuvchiga tushunarli xabar ko'rsatadi)."""
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        raise RuntimeError(
            "OPENAI_API_KEY sozlanmagan -- yengil so'rovlar (metrika/intent/"
            "byudjet/hisobot) faqat OpenAI orqali ishlaydi, Anthropic'ga "
            "tushib qolinmaydi."
        )
    return _call_openai(openai_key, system_prompt, [{"role": "user", "content": user_content}], max_tokens)


def call_light_chat(system_prompt: str, messages: list[dict], max_tokens: int = 1000) -> str:
    """`call_light()`ga o'xshaydi, lekin ko'p-turli (multi-turn) suhbat
    tarixi (`messages`, {"role", "content"} ro'yxati) bilan ishlaydi --
    erkin/umumiy suhbat rejimida ishlatiladi. FAQAT OpenAI -- Claude'ga
    fallback yo'q (Anthropic API faqat haqiqiy qaror/tavsiya beradigan
    vazifalar -- Targetolog/Marketolog action_plan -- uchun saqlanadi)."""
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        raise RuntimeError(
            "OPENAI_API_KEY sozlanmagan -- erkin suhbat ham faqat OpenAI "
            "orqali ishlaydi."
        )
    return _call_openai(openai_key, system_prompt, messages, max_tokens)



def _call_openai(api_key: str, system_prompt: str, messages: list[dict], max_tokens: int) -> str:
    full_messages = [{"role": "system", "content": system_prompt}] + list(messages)
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json={"model": OPENAI_MODEL, "temperature": 0, "max_tokens": max_tokens, "messages": full_messages},
        # MUHIM: avval 20 soniya edi -- OpenAI ba'zan shundan sekinroq javob
        # berib, keraksiz "Read timed out" xatosiga olib kelardi (Claude'ga
        # fallback endi yo'qligi uchun bu to'g'ridan-to'g'ri foydalanuvchiga
        # ko'rinadi). 55ga oshirildi -- bu Vercel funksiyasining o'zi 60
        # soniyada MAJBURIY to'xtaydigan chegarasidan atigi 5 soniya kam
        # (Telegram xabar yuborish/o'chirish uchun ozgina joy qoldirish
        # uchun). Butunlay chegarasiz qilib bo'lmaydi -- Vercel baribir 60
        # soniyada funksiyani o'zi majburan to'xtatadi (504), shuning uchun
        # 55 -- amalda erishsa bo'ladigan ENG UZUN vaqt.
        timeout=55,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]

# Har bir action_plan tipi -> uni haqiqiy hisobda bajaradigan funksiya
ACTION_EXECUTORS = {
    "pause_ad": lambda a: _execute_and_verify_status(a["object_id"], "PAUSED"),
    "resume_ad": lambda a: _execute_and_verify_status(a["object_id"], "ACTIVE"),
    "archive_campaign": lambda a: _execute_and_verify_status(a["object_id"], "ARCHIVED"),
    "increase_budget": lambda a: meta_api.adjust_budget_by_percent(
        a["object_id"], a["params"]["current_daily_budget_cents"], abs(a["params"]["percent"])
    ),
    "decrease_budget": lambda a: meta_api.adjust_budget_by_percent(
        a["object_id"], a["params"]["current_daily_budget_cents"], -abs(a["params"]["percent"])
    ),
    "fix_region_targeting": lambda a: _execute_fix_region(a),
    "adjust_audience": lambda a: _execute_adjust_audience(a),
    "launch_campaign": lambda a: _execute_launch_campaign(a),
    "start_ab_test": lambda a: _execute_ab_test(a),
    "conclude_ab_test": lambda a: (
        meta_api.pause_object(a["params"]["losing_adset_id"])
        if a.get("params", {}).get("losing_adset_id")
        else {"status": "no_loser_specified"}
    ),
    # replace_creative va create_instant_form MVP bosqichida avtomatik ijro etilmaydi —
    # bular ijodiy/qo'lda tasdiqlash talab qiladigan qadamlar (AI video/rasm yarata
    # olmaydi), shuning uchun faqat taklif sifatida odamga (Telegram orqali) ko'rsatiladi.
}


def _execute_and_verify_status(object_id: str, expected_status: str) -> dict:
    """pause_ad/resume_ad uchun: Meta'ga status o'zgartirish so'rovini yuboradi,
    KEYIN qayta o'qib haqiqatan o'zgarganini tekshiradi. Meta ba'zan
    {"success": true} qaytaradi-yu, holat aslida o'zgarmagan bo'lishi mumkin
    (masalan yuqori darajadagi adset/kampaniya o'chiq bo'lsa) — bu holda
    "bajarildi" deb yolg'on hisobot berilmasligi uchun xato ko'taramiz."""
    meta_api.set_status(object_id, expected_status)

    info = meta_api.get_object_status(object_id)
    actual_status = info.get("status")
    if actual_status != expected_status:
        raise meta_api.MetaAPIError({
            "message": (
                f"Meta so'rovni qabul qildi, lekin qayta tekshirganda holat "
                f"hali ham '{actual_status}' (kutilgan: '{expected_status}'). "
                "Ehtimol yuqori darajadagi kampaniya/adset boshqa holatda "
                "(masalan o'zi PAUSED). Ads Manager'da qo'lda tekshiring."
            ),
            "expected_status": expected_status,
            "actual_status": actual_status,
        })
    return {"status": actual_status, "verified": True}


def _require(action: dict, *path: str):
    """`action["params"]["audience_change"]["city_key"]` kabi chuqur maydonlarga
    XAVFSIZ kirish uchun yordamchi. Agar Targetolog kutilgan strukturani
    bermagan bo'lsa (masalan schema'ga to'liq amal qilmasa), Python'ning xom
    KeyError'i o'rniga aniq, tushunarli MetaAPIError ko'taradi — shu tufayli
    butun so'rov "kutilmagan xatolik" bilan buzilib qolmaydi, foydalanuvchi
    Telegram'da aniq nima yetishmayotganini ko'radi."""
    node = action
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise meta_api.MetaAPIError({
                "message": (
                    f"Targetolog action'ida kerakli maydon topilmadi: "
                    f"{'.'.join(path)}. Model action_schema'ga to'liq amal "
                    "qilmagan bo'lishi mumkin. Qaytadan urinib ko'ring yoki "
                    "buyruqni boshqacharoq/aniqroq yozing."
                ),
                "missing_field": ".".join(path),
                "action_received": action,
            })
        node = node[key]
    return node


def _require_any(action: dict, *paths: tuple) -> object:
    """`_require()`ga o'xshaydi, lekin bir nechta mumkin bo'lgan joylashuvni
    sinab ko'radi va birinchi topilganini qaytaradi. MUHIM: Targetolog ba'zan
    `params.audience_change.targeting` o'rniga to'g'ridan-to'g'ri
    `params.targeting` deb yozib qo'yadi (schema'ga qat'iy amal qilmaydi) —
    bu real, tez-tez uchraydigan holat, shuning uchun kodni PROMPT'ga emas,
    shu moslashuvchanlikka tayanamiz."""
    for path in paths:
        node = action
        found = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                found = False
                break
        if found:
            return node
    raise meta_api.MetaAPIError({
        "message": (
            "Targetolog action'ida kerakli maydon topilmadi (sinab ko'rilgan "
            f"joylashuvlar: {[' > '.join(p) for p in paths]}). Qaytadan urinib "
            "ko'ring yoki buyruqni boshqacharoq/aniqroq yozing."
        ),
        "tried_paths": [".".join(p) for p in paths],
        "action_received": action,
    })


def _execute_fix_region(action: dict) -> dict:
    """4.11-bo'lim: 'faqat joriy shahar' sozlamasini qo'llaydi va qayta o'qib
    tasdiqlaydi."""
    adset_id = _require(action, "object_id")
    city_key = _require_any(
        action,
        ("params", "audience_change", "city_key"),
        ("params", "city_key"),
    )
    meta_api.set_location_current_city_only(adset_id, city_key)
    verified = meta_api.get_adset_details(adset_id)
    return {"verified": True, "current_targeting": verified.get("targeting", {})}


def _execute_adjust_audience(action: dict) -> dict:
    """`adjust_audience` (masalan hudud exclude qilish): targeting'ni yangilaydi,
    KEYIN adset'ni qayta o'qib, so'ralgan o'zgarish (masalan excluded_geo_locations)
    haqiqatan saqlanganini tasdiqlaydi. Tasdiqlanmasa — bajarilgan deb ko'rsatilmaydi,
    xato sifatida qaytariladi (foydalanuvchi buni Telegram'da ❌ bilan ko'radi)."""
    adset_id = _require(action, "object_id")
    new_targeting = _require_any(
        action,
        ("params", "audience_change", "targeting"),
        ("params", "targeting"),
    )
    meta_api.update_targeting(adset_id, new_targeting)

    verified = meta_api.get_adset_details(adset_id)
    actual_targeting = verified.get("targeting", {})

    expected_excluded = new_targeting.get("excluded_geo_locations")
    if expected_excluded:
        actual_excluded = actual_targeting.get("excluded_geo_locations")
        if not actual_excluded:
            raise meta_api.MetaAPIError({
                "message": (
                    "Meta so'rovni qabul qildi, lekin qayta tekshirganda "
                    "excluded_geo_locations bo'sh chiqdi — o'zgarish amalda "
                    "saqlanmagan. Ads Manager'da qo'lda tekshiring."
                ),
                "expected_excluded_geo_locations": expected_excluded,
                "actual_targeting": actual_targeting,
            })
    return {"verified": True, "current_targeting": actual_targeting}


def _execute_launch_campaign(action: dict) -> dict:
    """8-band (targetolog prompt): to'liq yangi campaign -> adset -> (ad) yaratadi."""
    params = action["params"]
    campaign = meta_api.create_campaign(**params["campaign"])
    campaign_id = campaign["id"]

    adset_params = dict(params["adset"])
    adset_params["campaign_id"] = campaign_id
    adset = meta_api.create_adset(**adset_params)

    result = {"campaign": campaign, "adset": adset}

    ad_spec = params.get("ad")
    if ad_spec and ad_spec.get("creative_id"):
        ad = meta_api.create_ad(
            adset_id=adset["id"],
            name=ad_spec.get("name", action.get("object_name", "Target Master ad")),
            creative_id=ad_spec["creative_id"],
            status=ad_spec.get("status", "PAUSED"),
        )
        result["ad"] = ad
    else:
        result["note"] = "creative_id berilmagan — reklama hali yaratilmadi, foydalanuvchi creative_id yuborishi kerak."
    return result


def _execute_ab_test(action: dict) -> dict:
    """9-band (targetolog prompt): mavjud adset'ni nusxalab, B variantni yaratadi,
    faqat bitta o'zgaruvchini (auditoriya YOKI kreativ) farqlantiradi."""
    params = action["params"]
    copy_result = meta_api.copy_adset(
        action["object_id"], rename_suffix=params.get("rename_suffix", " - B variant")
    )
    b_adset_id = copy_result.get("adset_id") or copy_result.get("id")

    variant_b = params.get("variant_b", {})
    if variant_b.get("targeting"):
        meta_api.update_targeting(b_adset_id, variant_b["targeting"])
    if variant_b.get("creative_id"):
        meta_api.create_ad(
            adset_id=b_adset_id,
            name=f"{action.get('object_name', 'Test')} - B",
            creative_id=variant_b["creative_id"],
            status="ACTIVE",
        )

    meta_api.activate_object(action["object_id"])
    meta_api.activate_object(b_adset_id)
    return {
        "variant_a_adset_id": action["object_id"],
        "variant_b_adset_id": b_adset_id,
        "test_duration_days": params.get("test_duration_days", 7),
        "decision_metric": params.get("decision_metric", "CPA"),
    }

AUTO_EXECUTABLE_TYPES = set(ACTION_EXECUTORS.keys())

# "Rejalashtirilgan/pauzadagi/hali yoqilmagan" target so'rovlarini aniqlash
# uchun -- bunday savolda PAUSED holatidagi kampaniya/adset/ad'lar
# (`meta_api.get_account_structure`dan, HAQIQIY status maydoni bo'yicha,
# LLM'siz -- oddiy filtrlash orqali) ro'yxati javobga qo'shib beriladi.
_PLANNED_KEYWORDS = re.compile(
    r"rejalashtirilgan|pauzada|to'xtatilgan|hali yoqilmagan|tayyor turgan|"
    r"tayyor holatda",
    re.IGNORECASE,
)


class TargetologFormatError(Exception):
    """Model kutilgan JSON o'rniga erkin matn qaytarganda ko'tariladi (masalan,
    unga kerakli ma'lumot — kampaniya/adset ID — yetishmasa)."""
    def __init__(self, raw_text: str):
        self.raw_text = raw_text
        super().__init__("Model JSON formatda javob bermadi")


def _call_agent(system_prompt: str, user_content: str) -> dict:
    # MUHIM (token/xarajatni kamaytirish uchun): TARGETOLOG_SYSTEM/MARKETOLOG_SYSTEM
    # bilim bazasi bilan birga juda katta (~3-4 ming token) va HAR BIR chaqiruvda
    # bir xil — shuning uchun uni "cache_control" bilan belgilaymiz. Anthropic API
    # shu bloqni keshlab, keyingi 5 daqiqa ichidagi chaqiruvlarda uni ~10% narxda
    # qayta ishlatadi (to'liq narx emas). Bitta foydalanuvchi buyrug'i uchun bir
    # nechta chaqiruv (masalan geo-lookup ikkinchi bosqichi) bo'lsa ham, faqat
    # birinchisi to'liq narxda hisoblanadi.
    response = client.messages.create(
        model=MODEL,
        # MUHIM: 2500 token bilan ba'zan (ayniqsa ikki bosqichli aniqlashtirish
        # so'rovida, xabar kattaroq bo'lganda) javob o'rtada kesilib qolib,
        # JSON buzilib, "Targetolog JSON qaytarmadi" xatosiga olib kelardi.
        # 4000ga oshirildi — bu MAX chegara, real xarajat qancha token
        # ishlatilganiga bog'liq (kesilib ketmasa, ko'pincha ancha kamroq
        # ishlatiladi), shuning uchun xarajatni sezilarli oshirmaydi, lekin
        # muvaffaqiyatsiz/qayta urinishlarni oldini oladi.
        max_tokens=4000,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    text = response.content[0].text
    # Model ba'zan JSON'ni ```json ... ``` bloki ichida qaytarishi mumkin
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise TargetologFormatError(text) from e


SNAPSHOT_KV_KEY = "orchestrator_daily_snapshot"


def gather_data() -> dict:
    """Meta API'dan tahlil uchun kerakli barcha ma'lumotni yig'adi.

    Shuningdek, KECHAGI (oldingi chaqiruvdagi) kampaniya darajasidagi
    statistikani ham qo'shib beradi ("previous_snapshot") — shu orqali
    Targetolog "kecha CPA $9 edi, bugun $14 ga chiqdi" kabi HAQIQIY
    solishtirishga asoslanib xulosa chiqara oladi, taxmin qilmaydi. Joriy
    holat esa ertangi solishtirish uchun KV'ga saqlanadi."""
    account_structure = meta_api.get_account_structure()
    ad_insights = meta_api.get_insights(level="ad", date_preset="last_7d")
    region_breakdown = meta_api.get_insights(
        level="ad", date_preset="last_7d", breakdowns=["region"]
    )
    campaign_insights_today = meta_api.get_insights(level="campaign", date_preset="yesterday")

    # MUHIM: bu funksiya endi FAQAT kunlik cron'dan emas, tez-tez (masalan
    # har 30-60 daqiqada) ishlaydigan "kuzatuv" cron'idan ham chaqirilishi
    # mumkin. Agar har chaqiruvda snapshot'ni qayta yozsak, "kecha bilan
    # solishtirish" buzilib, "bir necha soat oldin bilan solishtirish"ga
    # aylanib qolardi. Shuning uchun snapshot FAQAT kunda BIR MARTA (sana
    # o'zgarganda) yangilanadi -- shu kunning ichidagi barcha keyingi
    # chaqiruvlar (kuzatuv cron ham, /analyze ham) hammasi bir xil "kecha"
    # ma'lumotini ko'radi.
    previous_snapshot = kv_store.get_json(SNAPSHOT_KV_KEY, default=None)
    today_str = datetime.utcnow().date().isoformat()
    if previous_snapshot is None or previous_snapshot.get("date") != today_str:
        kv_store.set_json(SNAPSHOT_KV_KEY, {
            "date": today_str,
            "campaign_insights": campaign_insights_today,
        })

    return {
        "account_structure": account_structure,
        "ad_insights": ad_insights,
        "region_breakdown": region_breakdown,
        "business_rules": BUSINESS_RULES,
        "generated_at": datetime.utcnow().isoformat(),
        "yesterday_campaign_insights": campaign_insights_today,
        "previous_day_snapshot_for_comparison": previous_snapshot,
        "comparison_instruction": (
            "'previous_day_snapshot_for_comparison' — avvalgi marta saqlangan "
            "kunlik holat (agar mavjud bo'lsa). Shu bilan 'yesterday_campaign_insights'ni "
            "solishtirib, narx/CPA/CPL keskin o'zgargan joylarni summary'da aniq ayting "
            "(masalan 'CPA kecha $9 edi, bugun $14 — 55% oshdi')."
        ),
    }


def _format_json_error(e: "TargetologFormatError", stage: str = "Targetolog") -> str:
    """Xato yuz berganda foydalanuvchiga ODDIY, QISQA matn ko'rsatiladi —
    xom JSON/model javobi hech qachon ko'rsatilmaydi (bu "kod"dek ko'rinib,
    tushunarsiz bo'ladi). To'liq texnik tafsilot faqat server logiga yoziladi
    (debug uchun), Telegram'ga chiqmaydi."""
    logger.error("%s JSON qaytarmadi. Xom javob: %s", stage, e.raw_text[:1000])
    return (
        "⚠️ Buni to'liq bajara olmadim — kerakli ma'lumot yetarli emas edi "
        "(masalan aniq qaysi reklama/kampaniya haqida ekani noaniq bo'ldi) "
        "yoki so'rov juda murakkab bo'ldi.\n\n"
        "Iltimos, aniqroq yozib qayta yuboring (masalan kampaniya nomini "
        "to'liq ko'rsating)."
    )


_EMPTY_STATS = {"succeeded": 0, "failed": 0, "skipped": 0, "manual_suggestions": 0}


def _run_pipeline(targetolog_user_message: str, dry_run: bool = False) -> tuple[str, dict]:
    """Targetolog -> Marketolog -> ijro zanjirining umumiy o'zagi. Buni ham
    to'liq hisob tahlili (`run_analysis_cycle`), ham Telegram'dagi erkin
    buyruqlar (`handle_chat_command`) chaqiradi — ikkalasi ham xuddi shu
    ikki bosqichli nazoratdan o'tadi. `(matn, statistika)` qaytaradi —
    statistika kunlik cron hisobotida "diqqatga loyiqmi" degan qarorni
    matnni regex bilan tahlil qilmasdan, to'g'ridan-to'g'ri aniqlash uchun."""
    logger.info("Targetolog agentga so'rov yuborilmoqda...")
    try:
        targetolog_plan = _call_agent(TARGETOLOG_SYSTEM, targetolog_user_message)
    except TargetologFormatError as e:
        return _format_json_error(e, "Targetolog"), dict(_EMPTY_STATS)
    return _finish_pipeline(targetolog_plan, dry_run)


def _finish_pipeline(targetolog_plan: dict, dry_run: bool = False) -> tuple[str, dict]:
    """Targetolog allaqachon tuzgan action_plan'ni Marketolog'ga tekshirtiradi
    va tasdiqlangan action'larni ijro etadi. `_run_pipeline` va geo-lookup
    ikki bosqichli oqimi (`_run_pipeline_command`) ikkalasi ham shu yerga kelib
    tugaydi.

    `business_rules.json` dagi `skip_marketolog: true` bo'lsa, Marketolog
    bosqichi butunlay o'tkazib yuboriladi — Targetolog taklif qilgan HAMMA
    action to'g'ridan-to'g'ri ijroga yuboriladi (tezroq, lekin ikkinchi nazorat
    qatlamisiz)."""
    skip_marketolog = bool(BUSINESS_RULES.get("skip_marketolog"))

    if skip_marketolog:
        logger.info("skip_marketolog=true — Marketolog bosqichi o'tkazib yuborildi.")
        marketolog_review = {
            "review_summary": "(Marketolog o'tkazib yuborildi — business_rules.json: skip_marketolog=true)",
            "decisions": [
                {"action_index": i, "type": a["type"], "decision": "approved", "comment": "auto (skip_marketolog)"}
                for i, a in enumerate(targetolog_plan.get("actions", []))
            ],
        }
    else:
        logger.info("Marketolog agent tekshirmoqda...")
        try:
            marketolog_review = _call_agent(
                MARKETOLOG_SYSTEM,
                "Targetolog taklif qilgan action_plan:\n\n"
                f"{json.dumps(targetolog_plan, ensure_ascii=False, indent=2)}\n\n"
                "Biznes qoidalari:\n"
                f"{json.dumps(BUSINESS_RULES, ensure_ascii=False, indent=2)}",
            )
        except TargetologFormatError as e:
            logger.error("Marketolog JSON qaytarmadi. Xom javob: %s", e.raw_text[:1000])
            text = (
                "⚠️ Ichki tekshiruvda xatolik chiqdi, qaytadan urinib ko'ring.\n\n"
                f"{targetolog_plan.get('summary', '')}"
            )
            return text, dict(_EMPTY_STATS)

    succeeded, failed, skipped = [], [], []
    if not dry_run:
        for decision in marketolog_review.get("decisions", []):
            idx = decision["action_index"]
            action = targetolog_plan["actions"][idx]
            action_type = action["type"]

            if action_type == "no_action":
                # "Hech narsa qilmaslik" — bu XATO yoki KUTILMAGAN holat emas,
                # aksincha hammasi joyida degani. Statistikaga (succeeded/
                # failed/skipped) kirmaydi — aks holda kunlik cron "hammasi
                # yaxshi bo'lsa xabar yubormaslik" mantig'i ishlamay qolardi.
                continue

            if decision["decision"] not in ("approved", "approved_with_edit"):
                skipped.append({"action": action, "decision": decision})
                continue

            if action_type not in AUTO_EXECUTABLE_TYPES:
                # replace_creative / create_instant_form — inson tasdig'i kerak
                skipped.append({"action": action, "decision": decision, "reason": "manual_step_required"})
                continue

            final_action = dict(action)
            if decision.get("final_params"):
                final_action["params"] = {**final_action.get("params", {}), **decision["final_params"]}

            try:
                result = ACTION_EXECUTORS[action_type](final_action)
                succeeded.append({"action": final_action, "result": result})
            except meta_api.MetaAPIError as e:
                logger.exception("Action bajarishda Meta API xatoligi: %s", action_type)
                failed.append({"action": final_action, "error": str(e)})
            except Exception as e:
                # MUHIM: MetaAPIError'dan tashqari HAR QANDAY xato (masalan
                # Targetolog kutilgan schema'ga to'liq amal qilmasa — KeyError/
                # TypeError) ham shu yerda tutiladi. Aks holda bitta action'dagi
                # kichik nuqson butun so'rovni "kutilmagan xatolik" bilan
                # buzib, foydalanuvchiga hech narsa tushunarli bo'lmagan xabar
                # ko'rsatib qo'yardi.
                logger.exception("Action bajarishda kutilmagan xato: %s", action_type)
                failed.append({"action": final_action, "error": f"{type(e).__name__}: {e}"})

    run_log = {
        "timestamp": datetime.utcnow().isoformat(),
        "targetolog_plan": targetolog_plan,
        "marketolog_review": marketolog_review,
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "dry_run": dry_run,
    }
    log_path = LOGS_DIR / f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    log_path.write_text(json.dumps(run_log, ensure_ascii=False, indent=2), encoding="utf-8")

    # ODDIY, QISQA hisobot — texnik hisob-kitob emas, oddiy odamga
    # tushunarli xabar. Targetolog'ning o'z xulosasi (`summary`) allaqachon
    # oddiy tilda yozilgan bo'lishi kerak (system prompt shuni talab qiladi);
    # bu yerda faqat qisqa amaliy qo'shimcha qilinadi.
    creative_or_form_actions = [
        a for a in targetolog_plan.get("actions", [])
        if a["type"] in ("replace_creative", "create_instant_form")
    ]

    report_lines = [targetolog_plan.get("summary", "").strip()]

    if succeeded:
        report_lines.append(f"\n✅ {len(succeeded)} ta o'zgarish qildim.")
    if failed:
        names = ", ".join(
            f["action"].get("object_name", f["action"].get("object_id", "?"))
            for f in failed[:5]
        )
        extra = f" va yana {len(failed) - 5} tasi" if len(failed) > 5 else ""
        report_lines.append(f"\n⚠️ {len(failed)} tasida xatolik chiqdi ({names}{extra}) — hisobda hech narsa o'zgarmadi.")
    if creative_or_form_actions:
        names = ", ".join(a.get("object_name", "?") for a in creative_or_form_actions[:5])
        report_lines.append(f"\n🎨 Bularga sizning tasdig'ingiz kerak: {names}.")

    text = "\n".join(line for line in report_lines if line).strip()
    stats = {
        "succeeded": len(succeeded),
        "failed": len(failed),
        "skipped": len(skipped),
        "manual_suggestions": len(creative_or_form_actions),
    }
    return text, stats


def run_analysis_cycle_with_stats(dry_run: bool = False) -> tuple[str, dict]:
    """`run_analysis_cycle()` bilan bir xil, lekin matn bilan birga aniq
    statistikani (`{"succeeded", "failed", "skipped", "manual_suggestions"}`)
    ham qaytaradi — matnni regex bilan "tahlil qilish" shart emas."""
    data = gather_data()
    data_json = json.dumps(data, ensure_ascii=False, indent=2)
    return _run_pipeline(
        f"Quyidagi ma'lumotlar asosida to'liq hisobni tahlil qilib action_plan tuzing:\n\n{data_json}",
        dry_run=dry_run,
    )


def run_analysis_cycle(dry_run: bool = False) -> str:
    """To'liq hisobni tahlil qiladi (barcha kampaniya/adset/ad + region breakdown).
    Telegram bot `/analyze` buyrug'i shu funksiyani chaqiradi."""
    text, _stats = run_analysis_cycle_with_stats(dry_run=dry_run)
    return text


def run_daily_cron_report(dry_run: bool = False) -> str | None:
    """VERCEL CRON UCHUN: `run_analysis_cycle()` bilan bir xil to'liq tahlilni
    ishga tushiradi, lekin foydalanuvchiga faqat DIQQATGA LOYIQ narsa bo'lsa
    (biror action bajarildi/xato berdi/qo'lda ko'rib chiqish kerak bo'lsa)
    xabar qaytaradi. Agar hisobda hech narsa o'zgarmagan va hammasi joyida
    bo'lsa — `None` qaytaradi, ya'ni kunlik "hammasi joyida" degan bo'sh
    xabar bilan bezovta qilinmaydi."""
    text, stats = run_analysis_cycle_with_stats(dry_run=dry_run)

    if not any(stats.values()):
        return None
    return text


def handle_budget_message(user_text: str, chat_id: int) -> str:
    """Foydalanuvchi byudjet/pul haqida yozganda chaqiriladi (masalan 'bugun
    500$ tushdi', 'qancha qoldi', 'qachon tugaydi'). Arzon model (LIGHT_MODEL)
    bilan bu deposit xabarimi yoki savolmi va agar deposit bo'lsa qancha
    summa ekanini aniqlaydi, keyin haqiqiy hisob-kitobni `budget_tracker.py`
    (Meta'dan olingan REAL xarajat asosida) bajaradi — model o'zi raqam
    o'ylab topmaydi, faqat matnni tushunadi."""
    text = call_light(
        "Foydalanuvchi reklama byudjeti/puli haqida yozmoqda. Faqat JSON "
        'qaytar: {"type": "deposit" yoki "query", "amount": <deposit bo\'lsa '
        "dollar miqdori (raqam), aks holda null>}. Masalan: "
        "'bugun 500$ tushdi' -> {\"type\":\"deposit\",\"amount\":500}. "
        "'gruppaga 200 dollar tashladim' -> {\"type\":\"deposit\",\"amount\":200}. "
        "'qancha qoldi', 'qachon tugaydi', '$100 qolganda ayt' -> "
        '{"type":"query","amount":null}. Faqat JSON qaytar, boshqa matn yo\'q.',
        user_text,
        max_tokens=60,
    ).strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {"type": "query", "amount": None}

    if parsed.get("type") == "deposit" and parsed.get("amount"):
        amount = float(parsed["amount"])
        status = budget_tracker.record_deposit(amount, chat_id)
        header = f"✅ ${amount:.0f} balansga qo'shildi.\n\n"
        return header + budget_tracker.format_status_message(status)

    budget_tracker.set_notify_chat_id(chat_id)
    status = budget_tracker.get_status()
    return budget_tracker.format_status_message(status)


def classify_intent(
    user_text: str, recent_history: list[dict] | None = None
) -> tuple[str, str]:
    """Foydalanuvchi Telegram'da erkin matn yozganda chaqiriladi. Bu matn
    haqiqiy amaliy buyruqmi (masalan 'yangi target yoq', 'X reklamani to'xtat',
    'abtest boshla') yoki oddiy savolmi -- shuni ARZON model (Haiku) bilan tez
    aniqlaydi. Og'ir ishning o'zini BAJARMAYDI -- buni ataylab `execute_intent()`
    ga ajratib qo'ydik, chunki Vercel webhook OG'IR (ACTION/ANALYSIS) va
    YENGIL (BUDGET/METRIC/GENERAL) turlarni turlicha ishlatishi kerak (og'irini
    fon so'rovga uzatib, Vercel'ning 60 soniyalik timeout'idan qochish uchun).

    `recent_history` -- suhbatning so'nggi xabarlari (agar Targetolog oldin
    "byudjetingiz qancha?" deb so'ragan bo'lsa, keyingi "50000" degan javob
    shu kontekst bilan to'g'ri bog'lanishi uchun).

    Qaytaradi: `(verdict, history_text)` -- `history_text` ham qaytariladi,
    chunki `execute_intent()` uni qayta hisoblamasligi kerak.
    """
    history_text = ""
    if recent_history:
        history_text = "\n\nSo'nggi suhbat konteksti:\n" + "\n".join(
            f"{m['role']}: {m['content']}" for m in recent_history[-6:]
        )

    verdict = call_light(
        (
            "Foydalanuvchi xabari qaysi turga kiradi? Faqat bitta so'z bilan javob ber:\n"
            "BUDGET -- agar reklama HISOB BALANSI/PULI haqida bo'lsa: hisobga pul "
            "tushirilgani haqida xabar (masalan 'bugun 500$ tushdi', 'gruppaga 200 "
            "dollar tashladim'), yoki shu pul qancha qolgani/qachon tugashi haqidagi "
            "savol (masalan 'qancha qoldi', 'necha kunga yetadi', 'qachon tugaydi', "
            "'100$ qolganda ayt'). Bu ADS ACCOUNT balansi haqida, aniq bitta ad'ning "
            "CPA/CTR kabi ijro ko'rsatkichi haqida EMAS (u METRIC).\n"
            "ANALYSIS -- agar foydalanuvchi BUTUN hisobni yoki bir nechta kampaniyani "
            "KENG QAMROVLI tahlil qilishni so'rasa (masalan: 'hisobimni tahlil qil', "
            "'targetni to'liq tekshir', 'nima muammo bor', 'umumiy holatni ko'rsat') -- "
            "bitta aniq obyektga qaratilgan tor savol EMAS, balki to'liq audit so'ralganda.\n"
            "ACTION -- agar amaliy buyruq bo'lsa: yangi target/kampaniya yoqish, mavjud "
            "reklamani to'xtatish/yoqish, byudjet o'zgartirish, abtest boshlash, auditoriya/"
            "hudud o'zgartirish (masalan biror viloyat/shaharni QO'SHISH yoki OLIB TASHLASH/"
            "EXCLUDE qilish, \"faqat X qolsin\", \"Y'ni chiqarib tashla\"), yoki shu buyruqqa "
            "javoban berilgan qo'shimcha ma'lumot (byudjet raqami, shahar nomi). Foydalanuvchi "
            "kampaniya/adset nomini o'z uslubida yozishi mumkin (masalan \"AB | Traffic | IG\", "
            "qisqartmalar, \" | \" bilan ajratilgan nomlar) -- bu ham ACTION, GENERAL emas.\n"
            "METRIC -- agar haqiqiy hisobdagi JORIY raqam/statistika so'ralayotgan bo'lsa. "
            "Bunga ikki xil so'rov kiradi: (1) ANIQ bitta ko'rsatkich (masalan 'video necha "
            "kishi ko'rgan', 'CPA qancha', 'necha % odam 15 soniyani ko'rgan'), VA (2) "
            "aniq ko'rsatkich nomi aytilmagan, lekin foydalanuvchi hisobning JORIY holati/"
            "raqamlarini so'rayotgan umumiy so'rovlar -- masalan 'target ma'lumot ber', "
            "'bugungi ma'lumotlarni ber', 'hisobot ber', 'statistika ko'rsat', 'necha lead "
            "keldi', 'bugun qanday ketyapti' kabi. Bunday umumiy so'rovlarda ham javob "
            "REAL Meta ma'lumotidan (lead soni, xarajat, CPL va h.k.) tuzilishi kerak -- "
            "GENERAL emas, chunki foydalanuvchi maslahat emas, HAQIQIY raqam kutmoqda.\n"
            "(3) foydalanuvchi ANIQ bir kun/sana yoki oraliq haqida so'raganda (masalan '20 iyulni bergin', '1-10 avgust qancha ketdi') -- bu ham METRIC, javob shu ANIQ davr uchun bo'lishi kerak, standart 7 kun EMAS. VA (4) foydalanuvchi 'rejalashtirilgan', 'tayyor turgan', 'pauzadagi', 'hali yoqilmagan', 'to'xtatilgan' targetlar/kampaniyalar haqida so'raganda (masalan 'rejalashtirilgan targetlar bormi', 'qaysi target pauzada') -- bu ham METRIC (hisob tuzilmasi/status ma'lumotidan javob beriladi), ACTION yoki GENERAL EMAS.\n"
            "GENERAL -- FAQAT hisobning joriy holati/raqamlari SO'RALMAGAN, sof bilim/"
            "maslahat savoli bo'lsa (masalan 'CBO nima', 'byudjetni qachon oshirish kerak', "
            "'yaxshi kreativ qanday bo'ladi'). Agar xabarda 'ma'lumot', 'hisobot', 'statistika', "
            "'bugungi holat' kabi so'zlar hisobga nisbatan ishlatilgan bo'lsa -- bu GENERAL "
            "EMAS, METRIC (yuqoriga qarang)."
        ),
        f"{history_text}\n\nYangi xabar: {user_text}",
        max_tokens=20,
    ).strip().upper()
    return verdict, history_text


def is_heavy_intent(verdict: str) -> bool:
    """ACTION va ANALYSIS -- Meta API'dan bir necha marta o'qish + Claude
    Sonnet chaqiruv(lar)i + ijro/tekshirish zanjirini talab qiladi, ba'zan
    bir necha o'n soniya davom etadi. Vercel'ning 60 soniyalik funksiya
    limitiga urilib qolmasligi uchun webhook bularni FON (background)
    so'rovga uzatadi; BUDGET/METRIC/GENERAL yengil va darhol bajariladi."""
    return "ACTION" in verdict or "ANALYSIS" in verdict


def execute_intent(
    verdict: str, user_text: str, history_text: str = "", chat_id: int | None = None
) -> str | None:
    """`classify_intent()` aniqlagan turga qarab tegishli ishni bajaradi va
    natija matnini (yoki oddiy savol bo'lsa `None`) qaytaradi."""
    if "BUDGET" in verdict:
        return handle_budget_message(user_text, chat_id) if chat_id is not None else None
    if "ANALYSIS" in verdict:
        return run_analysis_cycle(dry_run=False)
    if "ACTION" in verdict:
        return _run_pipeline_command(user_text, history_text)
    if "METRIC" in verdict:
        return answer_data_question(user_text, history_text)
    return None


def handle_chat_command(
    user_text: str, recent_history: list[dict] | None = None, chat_id: int | None = None
) -> str | None:
    """Eski nom, moslik uchun saqlangan: `classify_intent()` + `execute_intent()`ni
    ketma-ket, BITTA chaqiruv ichida (fon so'rovga ajratmasdan) bajaradi.
    VPS/mahalliy rejim (`telegram_bot.py`, uzoq-polling) shuni ishlatadi --
    u yerda Vercel'ning 60 soniyalik cheklovi yo'q, shuning uchun fon
    so'rovga ehtiyoj ham yo'q. Vercel webhook (`api/index.py`) endi
    `classify_intent`/`is_heavy_intent`/`execute_intent`ni to'g'ridan-to'g'ri,
    alohida-alohida ishlatadi."""
    verdict, history_text = classify_intent(user_text, recent_history)
    return execute_intent(verdict, user_text, history_text, chat_id)


def _run_pipeline_command(user_text: str, history_text: str) -> str:
    # MUHIM: foydalanuvchi kampaniya/adset'ni ko'pincha NOM bilan ataydi
    # (masalan "AB | Traffic | IG"), Meta ID bilan emas. Shuning uchun har bir
    # amaliy buyruqdan oldin joriy hisob strukturasini (nom + haqiqiy ID)
    # Targetologga beramiz — aks holda u ID'ni bila olmay, action_plan o'rniga
    # oddiy matnli tavsiya yozib qo'yadi (bajarilmagan bo'lib qoladi).
    # Ikkalasi ham bir-biriga bog'liq emas -- parallel (bir vaqtda) so'rab,
    # ketma-ket kutishning o'rniga umumiy kutish vaqtini taxminan yarmiga
    # tushiramiz (Vercel'ning 60 soniyalik funksiya limitiga urilib qolish
    # xavfini kamaytirish uchun muhim).
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        structure_future = pool.submit(meta_api.get_account_structure)
        insights_future = pool.submit(meta_api.get_insights, level="campaign", date_preset="last_7d")

        try:
            account_structure = structure_future.result()
            structure_json = json.dumps(account_structure, ensure_ascii=False, indent=2)
        except meta_api.MetaAPIError as e:
            return f"⚠️ Meta hisobi bilan bog'lanib bo'lmadi: {e}"

        try:
            campaign_insights = insights_future.result()
            insights_json = json.dumps(campaign_insights, ensure_ascii=False, indent=2)
        except meta_api.MetaAPIError as e:
            insights_json = f"(statistika olinmadi: {e})"

    message = (
        "Foydalanuvchi Telegram orqali quyidagi amaliy buyruqni berdi (kerak bo'lsa "
        f"suhbat konteksti bilan birga):{history_text}\n\n"
        f"Yangi xabar: \"{user_text}\"\n\n"
        "Joriy hisobdagi kampaniya/adset/ad nomlari va ID'lari (targeting "
        f"tafsilotlarisiz — kerak bo'lsa alohida so'rang):\n{structure_json}\n\n"
        f"So'nggi 7 kunlik kampaniya darajasidagi statistika (CPM/CTR/CPC/spend/"
        f"reach/frequency/actions):\n{insights_json}\n\n"
        "Agar buyruqda hudud/shahar/tuman nomi (masalan \"Chirchiq\", \"Zangiota\") "
        "qo'shish yoki chiqarib tashlash (exclude) kerak bo'lsa-yu, lekin sizda "
        "ularning Meta rasmiy geo-target kaliti (key) yo'q bo'lsa — `no_action` "
        "qaytarib, `actions[0].params.geo_lookup_needed` ro'yxatida shu joy "
        "nomlarini bering.\n"
        "Agar `adjust_audience` uchun biror adset'ning JORIY to'liq targeting'ini "
        "bilish kerak bo'lsa — `no_action` qaytarib, `actions[0].params."
        "adset_details_needed` ro'yxatida o'sha adset'ning (account_structure'dan "
        "topilgan) ID'sini bering.\n"
        "Ikkalasini ham bir vaqtda so'rashingiz mumkin — sizga natijalar birga "
        "qaytariladi va qayta so'ralasiz.\n"
        "Agar buyruqdagi nomga mos kampaniya/adset topilmasa YOKI yangi targeting "
        "uchun ma'lumot (soha, maqsad, byudjet, hudud) yetarli bo'lmasa — `no_action` "
        "qaytarib aniq nima yetishmayotganini `summary`da so'rang. Aks holda to'liq "
        "action_plan tuzing (haqiqiy ID va to'liq targeting obyekti bilan)."
    )

    try:
        targetolog_plan = _call_agent(TARGETOLOG_SYSTEM, message)
    except TargetologFormatError as e:
        return _format_json_error(e, "Targetolog")

    # Ikkinchi bosqich: agar Targetolog hudud kaliti va/yoki adset'ning to'liq
    # targeting'ini so'ragan bo'lsa, ularni haqiqatan Meta'dan olib, qayta so'raymiz.
    first_action = (targetolog_plan.get("actions") or [{}])[0]
    params = first_action.get("params") or {}
    geo_lookup_needed = params.get("geo_lookup_needed")
    adset_details_needed = params.get("adset_details_needed")

    if first_action.get("type") == "no_action" and (geo_lookup_needed or adset_details_needed):
        extra_parts = []

        if geo_lookup_needed:
            geo_candidates = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(geo_lookup_needed))) as pool:
                futures = {pool.submit(meta_api.search_geo_location, place): place for place in geo_lookup_needed}
                for future in concurrent.futures.as_completed(futures):
                    place = futures[future]
                    try:
                        geo_candidates[place] = future.result()
                    except meta_api.MetaAPIError as e:
                        geo_candidates[place] = {"error": str(e)}
            extra_parts.append(
                "Hudud nomlari uchun Meta'dan topilgan rasmiy geo-target "
                f"nomzodlari:\n{json.dumps(geo_candidates, ensure_ascii=False, indent=2)}"
            )

        if adset_details_needed:
            adset_details = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(adset_details_needed))) as pool:
                futures = {pool.submit(meta_api.get_adset_details, aid): aid for aid in adset_details_needed}
                for future in concurrent.futures.as_completed(futures):
                    adset_id = futures[future]
                    try:
                        adset_details[adset_id] = future.result()
                    except meta_api.MetaAPIError as e:
                        adset_details[adset_id] = {"error": str(e)}
            extra_parts.append(
                "So'ralgan adset(lar)ning to'liq joriy sozlamalari:\n"
                f"{json.dumps(adset_details, ensure_ascii=False, indent=2)}"
            )

        followup_message = (
            message + "\n\n---\n\n" + "\n\n".join(extra_parts) + "\n\n"
            "Endi shu ma'lumotlar bilan to'liq action_plan tuzing. Agar hali ham "
            "biror narsa yetishmasa, `no_action` qaytarib buni ochiq ayting."
        )
        try:
            targetolog_plan = _call_agent(TARGETOLOG_SYSTEM, followup_message)
        except TargetologFormatError as e:
            return _format_json_error(e, "Targetolog (aniqlashtirish)")

    text, _stats = _finish_pipeline(targetolog_plan, dry_run=False)
    return text


def _resolve_query_period(user_text: str) -> tuple[dict, str]:
    """Foydalanuvchi so'ragan davrni aniqlaydi -- "bugun", "20 iyul", "1-10
    avgust" kabi ANIQ sana/oraliq aytilgan bo'lsa, arzon model orqali shuni
    ANIQ time_range (since/until)ga o'giradi. Hech qanday davr aytilmagan
    bo'lsa, standart so'nggi 7 kunga tushadi.

    Qaytaradi: `(meta_api.get_insights ga beriladigan kwargs, odam o'qiydigan
    davr nomi)` -- masalan `({"date_preset": "today"}, "bugungi kun")` yoki
    `({"time_range": {"since": "2026-07-20", "until": "2026-07-20"}}, "20.07.2026")`."""
    today_iso = datetime.utcnow().date().isoformat()
    extraction = call_light(
        f"Bugungi sana: {today_iso} (YYYY-MM-DD). Foydalanuvchi xabaridan aniq QAYSI "
        "SANA yoki DAVR haqida so'rayotganini aniqla. Faqat JSON qaytar: "
        '{"since": "YYYY-MM-DD" yoki null, "until": "YYYY-MM-DD" yoki null, '
        '"label": "odam o\'qiydigan qisqa nom (masalan \'20.07.2026\' yoki \'bugungi kun\')"}'
        '. Agar xabarda "bugun"/"hozir" bo\'lsa: since=until=bugungi sana. Agar aniq bitta '
        'sana aytilgan bo\'lsa (masalan "20 iyul"), yil ko\'rsatilmagan bo\'lsa joriy yildan '
        'hisobla (agar shu sana kelajakda chiqib qolsa, o\'tgan yildan ol); since=until=o\'sha '
        'sana. Agar oraliq aytilgan bo\'lsa ("1-10 avgust"), since/until shunga mos. Agar '
        'hech qanday aniq sana/davr aytilmagan bo\'lsa, since=null, until=null, '
        'label="so\'nggi 7 kun" qaytar. Faqat JSON, boshqa matn yo\'q.',
        user_text,
        max_tokens=80,
    )
    text = extraction.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {}

    since = parsed.get("since")
    until = parsed.get("until")
    label = parsed.get("label") or "so'nggi 7 kun"
    if since and until:
        return {"time_range": {"since": since, "until": until}}, label
    return {"date_preset": "last_7d"}, label


ADMIN_REPORT_BODY_TEMPLATE = (
    "\U0001F4B0 Xarajat: $<son>\n"
    "\U0001F4E9 Leadlar: <son>\n"
    "\U0001F4AC Xabarlar: <son>\n"
    "\U0001F3AF CPL: $<son>\n"
    "\U0001F4C8 CTR: <son>%\n"
    "\U0001F4F1 CPC: $<son>\n"
    "\U0001F4F6 CPM: $<son>\n"
    "\U0001F441 Impressions: <son>\n"
    "\U0001F4CD Reach: <son>\n"
    "\U0001F504 Frequency: <son>\n\n"
    "\U0001F525 Eng yaxshi kampaniya:\n<nom>\n"
    "\u26A0\uFE0F Eng yomon kampaniya:\n<nom>"
)


def _admin_report_header(period_label: str, hisobot_vaqti: str, subtitle: str) -> str:
    return (
        "\U0001F4CA ADMIN TARGET HISOBOTI\n\n"
        f"\U0001F4C5 Davr: {period_label}\n"
        f"\U0001F553 Hisobot vaqti: {hisobot_vaqti}\n"
        f"\U0001F4DD {subtitle}\n"
        "\U0001F7E2 Real Data\n\n"
    )


def build_admin_report(
    period_label: str,
    hisobot_vaqti: str,
    subtitle: str = "Joriy holat",
    insight_kwargs: dict | None = None,
) -> str:
    """"ADMIN TARGET HISOBOTI" qat'iy formatidagi hisobotni quradi (kunlik
    09:00 cron VA oddiy "ma'lumot/hisobot ber" so'rovlari -- IKKALASI HAM shu
    bir xil ko'rinishda javob berishi uchun, foydalanuvchi so'ragan tarzda).
    Sarlavha/sana/vaqt qismini biz o'zimiz (deterministik, LLM'siz) yozamiz --
    faqat sonli ko'rsatkichlar (xarajat/lead/CPL va h.k.) va eng yaxshi/yomon
    kampaniya nomi OpenAI orqali, FAQAT haqiqiy Meta ma'lumotidan hisoblanadi."""
    insight_kwargs = insight_kwargs or {"date_preset": "today"}
    header = _admin_report_header(period_label, hisobot_vaqti, subtitle)
    try:
        account_rows = meta_api.get_insights(level="account", fields=meta_api.DEFAULT_FIELDS, **insight_kwargs)
        campaign_rows = meta_api.get_full_report(level="campaign", **insight_kwargs)
    except meta_api.MetaAPIError as e:
        return header + f"\u26A0\uFE0F Meta API'dan ma'lumot olishda xatolik: {e}"

    account_json = json.dumps(account_rows, ensure_ascii=False, indent=2)
    campaign_json = json.dumps(campaign_rows, ensure_ascii=False, indent=2)

    system_prompt = (
        "Senga hisobning HAQIQIY Meta Ads statistikasi beriladi (account "
        "darajasida umumiy va har bir kampaniya darajasida alohida). Vazifang: "
        "FAQAT quyidagi qatorlarni, AYNAN shu tartibda va shu formatda "
        "to'ldirib qaytarish -- boshqa hech qanday so'z, izoh, sarlavha "
        "QO'SHMA (sarlavhani men o'zim qo'shaman):\n\n"
        + ADMIN_REPORT_BODY_TEMPLATE +
        "\n\nQoidalar: barcha sonlar FAQAT pastda berilgan HAQIQIY "
        "ma'lumotdan hisoblanishi kerak, hech narsani o'ylab topma. Xarajat = "
        "account darajasidagi 'spend'.\n\n"
        "MUHIM (Leadlar) -- Meta ko'pincha BITTA XIL lead voqeasini "
        "actions ichida BIR NECHTA turli action_type nomi bilan qayta-qayta "
        "ko'rsatadi (masalan 'lead', 'onsite_conversion.lead_grouped', "
        "'offsite_conversion.fb_pixel_lead' -- bular ko'pincha BIR XIL "
        "leadni anglatadi, HAR XILI EMAS). SHUNING UCHUN ularning "
        "'value'larini HECH QACHON bir-biriga QO'SHMA (qo'shsang lead soni "
        "sun'iy ravishda 2-3 baravar oshib ketadi). Buning o'rniga FAQAT "
        "BITTA action_type'dan foydalan -- quyidagi tartib bo'yicha ro'yxatda "
        "birinchi UCHRAGANINI tanla va shuning 'value'sini Leadlar sifatida "
        "ol: 1) 'onsite_conversion.lead_grouped', 2) 'lead', "
        "3) 'offsite_conversion.fb_pixel_lead', 4) nomida 'lead' so'zi bor "
        "boshqa istalgan yozuv. Qolgan lead-o'xshash yozuvlarni butunlay "
        "e'tiborsiz qoldir.\n\n"
        "Xabarlar uchun ham XUDDI SHU qoida -- action_type nomida 'messag' "
        "so'zi bor yozuvlar orasidan HAM faqat BITTASINI (eng mosini, "
        "masalan 'onsite_conversion.messaging_conversation_started_7d') "
        "tanla, bir-biriga qo'shma.\n\n"
        "CPL = Xarajat / Leadlar (Leadlar 0 bo'lsa, CPL o'rniga '-' yoz). "
        "CTR/CPC/CPM/Impressions/Reach/Frequency = account darajasidagi mos "
        "maydonlar ('ctr','cpc','cpm','impressions','reach','frequency'). "
        "Biror maydon topilmasa/bo'sh bo'lsa, 0 yoz (o'ylab topma). Eng "
        "yaxshi kampaniya = ENG KO'P lead keltirgan (lead bo'lmasa, ENG KAM "
        "CPM/eng ko'p natija bergan) kampaniya nomi. Eng yomon kampaniya = "
        "ENG KO'P xarajat qilib ENG KAM/0 lead keltirgan kampaniya nomi. "
        "Atigi bitta yoki hech qanday faol kampaniya bo'lmasa, shu joyga '-' "
        "yoz. Pul miqdorini '$' bilan ikkita kasr xonagacha (masalan $4.35), "
        "foizni bitta kasr xonagacha (masalan 1.34%), Impressions/Reach'ni "
        "minglik ajratkich bilan (masalan 4 786) yoz."
    )

    body = call_light(
        system_prompt,
        f"account darajasida umumiy statistika ({period_label}):\n{account_json}\n\n"
        f"kampaniya darajasida ({period_label}):\n{campaign_json}",
        max_tokens=350,
    ).strip()

    return header + body


def _current_tashkent_time() -> tuple[str, str]:
    now = datetime.utcnow() + timedelta(hours=5)  # O'zbekiston vaqti (UTC+5)
    return now.strftime("%d.%m.%Y"), now.strftime("%H:%M")


def answer_data_question(user_text: str, history_text: str = "") -> str:
    """Foydalanuvchi hisobdagi aniq metrika/raqamni, umumiy joriy holatni,
    yoki REJALASHTIRILGAN/PAUZADAGI (hali yoqilmagan/o'chirilgan) targetlar
    haqida so'raganda (masalan: 'CPA qancha', 'bugungi ma'lumotlarni ber',
    '20 iyulni bergin', 'rejalashtirilgan targetlar bormi') chaqiriladi.

    Foydalanuvchining aniq talabiga ko'ra: javob HAR DOIM kunlik 09:00
    "ADMIN TARGET HISOBOTI" bilan BIR XIL qat'iy formatda beriladi
    (`build_admin_report`), farqi faqat davr (`_resolve_query_period`
    orqali aniqlanadi) va sarlavhadagi vaqt/izoh. Agar savol aynan
    rejalashtirilgan/pauzadagi targetlar haqida bo'lsa, pastiga
    `account_structure`dan (HAQIQIY `status` maydoni, LLM'siz oddiy
    filtrlash orqali) PAUSED ro'yxati ham qo'shiladi."""
    insight_kwargs, period_label = _resolve_query_period(user_text)
    _, hisobot_vaqti = _current_tashkent_time()
    report = build_admin_report(period_label, hisobot_vaqti, "So'ralgan ma'lumot", insight_kwargs)

    if _PLANNED_KEYWORDS.search(user_text):
        try:
            structure = meta_api.get_account_structure(active_only=False)
        except meta_api.MetaAPIError as e:
            report += f"\n\n\u26A0\uFE0F Hisob tuzilmasini olishda xatolik: {e}"
        else:
            paused_names = []
            for obj_type in ("campaigns", "adsets", "ads"):
                for obj in structure.get(obj_type, []):
                    if str(obj.get("status", "")).upper() == "PAUSED":
                        paused_names.append(f"{obj.get('name', obj.get('id'))} ({obj_type[:-1]})")
            if paused_names:
                report += "\n\n\u23F8 Rejalashtirilgan/pauzadagi targetlar:\n" + "\n".join(
                    f"- {name}" for name in paused_names
                )
            else:
                report += "\n\n\u23F8 Hozircha rejalashtirilgan/pauzadagi target yo'q."

    return report


if __name__ == "__main__":
    print(run_analysis_cycle(dry_run=False))
