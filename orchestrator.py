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
from pathlib import Path
from datetime import datetime

import anthropic

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

# MODEL TANLASH STRATEGIYASI (xarajatni balanslash uchun):
#   - MODEL (Sonnet) — faqat HAQIQIY vazifa/qaror yaratish uchun: Targetolog
#     action_plan tuzganda (yangi kampaniya, byudjet/auditoriya o'zgarishi,
#     murakkab tashxis) va Marketolog tekshiruvida. Bu joylarda chuqur
#     mulohaza va bilim bazasiga tayanish kerak — arzon model xato qiladi.
#   - LIGHT_MODEL (Haiku) — intent aniqlash, oddiy metrika savoliga real
#     raqamlar bilan javob berish (`answer_data_question`), byudjet
#     deposit/savolini tushunish, va oddiy erkin suhbat (bilim bazasidan
#     maslahat, hisobga tegmaydigan). Bular "vazifa yaratish" emas, faqat
#     o'qish/tushuntirish — Haiku yetarli va bir necha barobar arzon.
MODEL = "claude-sonnet-4-5"
LIGHT_MODEL = "claude-haiku-4-5-20251001"
INTENT_MODEL = LIGHT_MODEL  # eski nom — moslik uchun saqlangan
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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

    previous_snapshot = kv_store.get_json(SNAPSHOT_KV_KEY, default=None)
    kv_store.set_json(SNAPSHOT_KV_KEY, {
        "date": datetime.utcnow().date().isoformat(),
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
    extraction = client.messages.create(
        model=LIGHT_MODEL,
        max_tokens=60,
        system=(
            "Foydalanuvchi reklama byudjeti/puli haqida yozmoqda. Faqat JSON "
            'qaytar: {"type": "deposit" yoki "query", "amount": <deposit bo\'lsa '
            "dollar miqdori (raqam), aks holda null>}. Masalan: "
            "'bugun 500$ tushdi' -> {\"type\":\"deposit\",\"amount\":500}. "
            "'gruppaga 200 dollar tashladim' -> {\"type\":\"deposit\",\"amount\":200}. "
            "'qancha qoldi', 'qachon tugaydi', '$100 qolganda ayt' -> "
            '{"type":"query","amount":null}. Faqat JSON qaytar, boshqa matn yo\'q.'
        ),
        messages=[{"role": "user", "content": user_text}],
    )
    text = extraction.content[0].text.strip()
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


def handle_chat_command(
    user_text: str, recent_history: list[dict] | None = None, chat_id: int | None = None
) -> str | None:
    """Foydalanuvchi Telegram'da erkin matn yozganda chaqiriladi. Avval bu matn
    haqiqiy amaliy buyruqmi (masalan 'yangi target yoq', 'X reklamani to'xtat',
    'abtest boshla') yoki oddiy savolmi — shuni aniqlaydi.

    `recent_history` — suhbatning so'nggi xabarlari (agar Targetolog oldin
    "byudjetingiz qancha?" deb so'ragan bo'lsa, keyingi "50000" degan javob
    shu kontekst bilan to'g'ri bog'lanishi uchun).

    - Agar amaliy buyruq (yoki oldingi so'rovga davom) bo'lsa: to'liq
      Targetolog -> Marketolog -> ijro zanjirini ishga tushirib, natija
      hisobotini qaytaradi.
    - Agar oddiy savol bo'lsa: `None` qaytaradi — telegram_bot.py bu holda
      o'zining oddiy (faqat maslahat beruvchi) suhbat rejimidan foydalanadi.
    """
    history_text = ""
    if recent_history:
        history_text = "\n\nSo'nggi suhbat konteksti:\n" + "\n".join(
            f"{m['role']}: {m['content']}" for m in recent_history[-6:]
        )

    intent_check = client.messages.create(
        model=INTENT_MODEL,
        max_tokens=20,
        system=(
            "Foydalanuvchi xabari qaysi turga kiradi? Faqat bitta so'z bilan javob ber:\n"
            "BUDGET — agar reklama HISOB BALANSI/PULI haqida bo'lsa: hisobga pul "
            "tushirilgani haqida xabar (masalan 'bugun 500$ tushdi', 'gruppaga 200 "
            "dollar tashladim'), yoki shu pul qancha qolgani/qачон tugashi haqidagi "
            "savol (masalan 'qancha qoldi', 'necha kunga yetadi', 'qachon tugaydi', "
            "'100$ qolganda ayt'). Bu ADS ACCOUNT balansi haqida, aniq bitta ad'ning "
            "CPA/CTR kabi ijro ko'rsatkichi haqida EMAS (u METRIC).\n"
            "ANALYSIS — agar foydalanuvchi BUTUN hisobni yoki bir nechta kampaniyani "
            "KENG QAMROVLI tahlil qilishni so'rasa (masalan: 'hisobimni tahlil qil', "
            "'targetni to'liq tekshir', 'nima muammo bor', 'umumiy holatni ko'rsat') — "
            "bitta aniq obyektga qaratilgan tor savol EMAS, balki to'liq audit so'ralganda.\n"
            "ACTION — agar amaliy buyruq bo'lsa: yangi target/kampaniya yoqish, mavjud "
            "reklamani to'xtatish/yoqish, byudjet o'zgartirish, abtest boshlash, auditoriya/"
            "hudud o'zgartirish (masalan biror viloyat/shaharni QO'SHISH yoki OLIB TASHLASH/"
            "EXCLUDE qilish, \"faqat X qolsin\", \"Y'ni chiqarib tashla\"), yoki shu buyruqqa "
            "javoban berilgan qo'shimcha ma'lumot (byudjet raqami, shahar nomi). Foydalanuvchi "
            "kampaniya/adset nomini o'z uslubida yozishi mumkin (masalan \"AB | Traffic | IG\", "
            "qisqartmalar, \" | \" bilan ajratilgan nomlar) — bu ham ACTION, GENERAL emas.\n"
            "METRIC — agar haqiqiy hisobdagi aniq raqam/metrika so'ralayotgan bo'lsa "
            "(masalan: 'video necha kishi ko'rgan', 'CPA qancha', 'necha % odam 15 "
            "soniyani ko'rgan', 'bugungi xarajat qancha').\n"
            "GENERAL — agar bu shunchaki umumiy savol/maslahat so'rovi bo'lsa (hisobga "
            "tegishli aniq raqam so'ralmagan)."
        ),
        messages=[{"role": "user", "content": f"{history_text}\n\nYangi xabar: {user_text}"}],
    )
    verdict = intent_check.content[0].text.strip().upper()

    if "BUDGET" in verdict:
        return handle_budget_message(user_text, chat_id) if chat_id is not None else None
    if "ANALYSIS" in verdict:
        return run_analysis_cycle(dry_run=False)
    if "ACTION" in verdict:
        return _run_pipeline_command(user_text, history_text)
    if "METRIC" in verdict:
        return answer_data_question(user_text, history_text)
    return None


def _run_pipeline_command(user_text: str, history_text: str) -> str:
    # MUHIM: foydalanuvchi kampaniya/adset'ni ko'pincha NOM bilan ataydi
    # (masalan "AB | Traffic | IG"), Meta ID bilan emas. Shuning uchun har bir
    # amaliy buyruqdan oldin joriy hisob strukturasini (nom + haqiqiy ID)
    # Targetologga beramiz — aks holda u ID'ni bila olmay, action_plan o'rniga
    # oddiy matnli tavsiya yozib qo'yadi (bajarilmagan bo'lib qoladi).
    try:
        account_structure = meta_api.get_account_structure()
        structure_json = json.dumps(account_structure, ensure_ascii=False, indent=2)
    except meta_api.MetaAPIError as e:
        return f"⚠️ Meta hisobi bilan bog'lanib bo'lmadi: {e}"

    # MUHIM: faqat nom+ID (account_structure) yetarli emas — Targetolog
    # pause/resume/byudjet kabi qarorlarni ham, oddiy "qancha xarajat bo'ldi"
    # kabi savolларни ham REAL ko'rsatkichlarsiz to'g'ri bera olmaydi va aks
    # holda foydalanuvchidan "raqamlarni o'zingiz Ads Manager'dan kiriting" deb
    # so'rab qo'yadi. Kampaniya darajasida (yengil, ko'p token yemaydi) so'nggi
    # 7 kunlik CPM/CTR/CPA/spend/reach/frequency shu yerda beriladi. Chuqurroq
    # (ad-darajasidagi) raqam kerak bo'lsa, foydalanuvchi buni aytadi va METRIC
    # intent orqali `answer_data_question` to'liq ad-level hisobotni oladi.
    try:
        campaign_insights = meta_api.get_insights(level="campaign", date_preset="last_7d")
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
            for place in geo_lookup_needed:
                try:
                    geo_candidates[place] = meta_api.search_geo_location(place)
                except meta_api.MetaAPIError as e:
                    geo_candidates[place] = {"error": str(e)}
            extra_parts.append(
                "Hudud nomlari uchun Meta'dan topilgan rasmiy geo-target "
                f"nomzodlari:\n{json.dumps(geo_candidates, ensure_ascii=False, indent=2)}"
            )

        if adset_details_needed:
            adset_details = {}
            for adset_id in adset_details_needed:
                try:
                    adset_details[adset_id] = meta_api.get_adset_details(adset_id)
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


def answer_data_question(user_text: str, history_text: str = "") -> str:
    """Foydalanuvchi hisobdagi aniq metrika/raqamni so'raganda (masalan: 'video
    necha kishi ko'rgan', 'necha % odam 15 soniyani ko'rgan', 'CPA qancha')
    chaqiriladi. Meta API'dan (video metrikalari bilan birga) real ma'lumotni
    tortib, Targetolog'ga faqat SHU raqamlar asosida — o'ylab topmasdan — javob
    berishni buyuradi. Bu action emas, faqat hisobot, shuning uchun Marketolog
    tekshiruvidan o'tmaydi (hisobga hech narsa o'zgartirilmaydi)."""
    try:
        report_data = meta_api.get_full_report(level="ad", date_preset="last_7d")
    except meta_api.MetaAPIError as e:
        return f"⚠️ Meta API'dan ma'lumot olishda xatolik: {e}"

    data_json = json.dumps(report_data, ensure_ascii=False, indent=2)
    data_qa_system = (
        f"{TARGETOLOG_ROLE}\n\n---\n\n# BILIM BAZASI\n\n{KNOWLEDGE_BASE}\n\n---\n\n"
        "MUHIM: Bu safar sendan action_plan JSON EMAS, oddiy o'zbekcha matn "
        "javob kutilyapti. Foydalanuvchi hisobdagi aniq metrika/raqamni "
        "so'ramoqda. Faqat senga berilgan haqiqiy `insights` ma'lumotlaridan "
        "foydalanib javob ber (masalan foiz hisoblash: "
        "video_thruplay_watched_actions / video_play_actions * 100). Agar "
        "kerakli maydon ma'lumotda yo'q bo'lsa, buni ochiq ayt, o'ylab topma. "
        "Javobni Telegram uchun qisqa va tushunarli qil, kerak bo'lsa ad/adset "
        "nomlari bo'yicha alohida ko'rsat."
    )
    response = client.messages.create(
        # MUHIM: bu yerda faqat berilgan raqamlarni o'qib, oddiy tilda
        # qaytarish kerak — real qaror/action_plan yaratilmaydi. Shuning
        # uchun qimmat Sonnet emas, arzon LIGHT_MODEL (Haiku) yetarli.
        model=LIGHT_MODEL,
        max_tokens=800,  # xarajatni cheklash uchun kamaytirildi
        # cache_control — xuddi _call_agent'dagi kabi, statik qismini keshlab
        # xarajatni kamaytiradi.
        system=[{"type": "text", "text": data_qa_system, "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": (
                f"{history_text}\n\nSavol: \"{user_text}\"\n\n"
                f"So'nggi 7 kunlik reklama ma'lumotlari (ad darajasida):\n{data_json}"
            ),
        }],
    )
    return response.content[0].text


if __name__ == "__main__":
    print(run_analysis_cycle(dry_run=False))
