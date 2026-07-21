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
import json
import logging
from pathlib import Path
from datetime import datetime

import anthropic

import meta_api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

BASE_DIR = Path(__file__).parent
AGENTS_DIR = BASE_DIR / "agents"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

KNOWLEDGE_BASE = (BASE_DIR / "target_master_agent.md").read_text(encoding="utf-8")
TARGETOLOG_ROLE = (AGENTS_DIR / "targetolog_system_prompt.md").read_text(encoding="utf-8")
MARKETOLOG_ROLE = (AGENTS_DIR / "marketolog_system_prompt.md").read_text(encoding="utf-8")
ACTION_SCHEMA = (AGENTS_DIR / "action_schema.md").read_text(encoding="utf-8")
BUSINESS_RULES = json.loads((BASE_DIR / "business_rules.json").read_text(encoding="utf-8"))

TARGETOLOG_SYSTEM = f"{TARGETOLOG_ROLE}\n\n---\n\n# BILIM BAZASI\n\n{KNOWLEDGE_BASE}\n\n---\n\n{ACTION_SCHEMA}"
MARKETOLOG_SYSTEM = f"{MARKETOLOG_ROLE}\n\n---\n\n{ACTION_SCHEMA}"

MODEL = "claude-sonnet-4-5"
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Har bir action_plan tipi -> uni haqiqiy hisobda bajaradigan funksiya
ACTION_EXECUTORS = {
    "pause_ad": lambda a: _execute_and_verify_status(a["object_id"], "PAUSED"),
    "resume_ad": lambda a: _execute_and_verify_status(a["object_id"], "ACTIVE"),
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
    if expected_status == "PAUSED":
        meta_api.pause_object(object_id)
    else:
        meta_api.activate_object(object_id)

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


def _execute_fix_region(action: dict) -> dict:
    """4.11-bo'lim: 'faqat joriy shahar' sozlamasini qo'llaydi va qayta o'qib
    tasdiqlaydi."""
    adset_id = _require(action, "object_id")
    city_key = _require(action, "params", "audience_change", "city_key")
    meta_api.set_location_current_city_only(adset_id, city_key)
    verified = meta_api.get_adset_details(adset_id)
    return {"verified": True, "current_targeting": verified.get("targeting", {})}


def _execute_adjust_audience(action: dict) -> dict:
    """`adjust_audience` (masalan hudud exclude qilish): targeting'ni yangilaydi,
    KEYIN adset'ni qayta o'qib, so'ralgan o'zgarish (masalan excluded_geo_locations)
    haqiqatan saqlanganini tasdiqlaydi. Tasdiqlanmasa — bajarilgan deb ko'rsatilmaydi,
    xato sifatida qaytariladi (foydalanuvchi buni Telegram'da ❌ bilan ko'radi)."""
    adset_id = _require(action, "object_id")
    new_targeting = _require(action, "params", "audience_change", "targeting")
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


def gather_data() -> dict:
    """Meta API'dan tahlil uchun kerakli barcha ma'lumotni yig'adi."""
    account_structure = meta_api.get_account_structure()
    ad_insights = meta_api.get_insights(level="ad", date_preset="last_7d")
    region_breakdown = meta_api.get_insights(
        level="ad", date_preset="last_7d", breakdowns=["region"]
    )
    return {
        "account_structure": account_structure,
        "ad_insights": ad_insights,
        "region_breakdown": region_breakdown,
        "business_rules": BUSINESS_RULES,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _format_json_error(e: "TargetologFormatError", stage: str = "Targetolog") -> str:
    logger.error("%s JSON qaytarmadi. Xom javob: %s", stage, e.raw_text[:1000])
    return (
        f"⚠️ Buyruqni to'liq amalga oshira olmadim ({stage} bosqichida) — kerakli "
        "ma'lumot (masalan aniq kampaniya/adset nomi yoki ID) yetarli emas edi, "
        "yoki so'rov juda murakkab bo'ldi.\n\n"
        "Model qanday javob berganini ko'rsataman (bu bajarilmadi, faqat matn):\n\n"
        f"{e.raw_text[:1200]}"
    )


def _run_pipeline(targetolog_user_message: str, dry_run: bool = False) -> str:
    """Targetolog -> Marketolog -> ijro zanjirining umumiy o'zagi. Buni ham
    to'liq hisob tahlili (`run_analysis_cycle`), ham Telegram'dagi erkin
    buyruqlar (`handle_chat_command`) chaqiradi — ikkalasi ham xuddi shu
    ikki bosqichli nazoratdan o'tadi."""
    logger.info("Targetolog agentga so'rov yuborilmoqda...")
    try:
        targetolog_plan = _call_agent(TARGETOLOG_SYSTEM, targetolog_user_message)
    except TargetologFormatError as e:
        return _format_json_error(e, "Targetolog")
    return _finish_pipeline(targetolog_plan, dry_run)


def _finish_pipeline(targetolog_plan: dict, dry_run: bool = False) -> str:
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
            return (
                "⚠️ Targetolog taklif berdi, lekin Marketolog tekshiruvida ichki xatolik "
                "yuz berdi. Qaytadan urinib ko'ring.\n\n"
                f"Targetolog taklifi: {targetolog_plan.get('summary', '')}"
            )

    succeeded, failed, skipped = [], [], []
    if not dry_run:
        for decision in marketolog_review.get("decisions", []):
            idx = decision["action_index"]
            action = targetolog_plan["actions"][idx]
            action_type = action["type"]

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

    report_lines = [
        "📊 Target Master — hisobot",
        "",
        f"🎯 Targetolog: {targetolog_plan.get('summary', '')}",
    ]
    if not skip_marketolog:
        report_lines.append(f"✅ Marketolog: {marketolog_review.get('review_summary', '')}")
    report_lines += [
        "",
        f"✅ Muvaffaqiyatli bajarildi: {len(succeeded)}",
        f"❌ Xato bilan tugadi: {len(failed)}",
        f"⏭ Qo'lda ko'rib chiqish/rad etilgan: {len(skipped)}",
    ]
    if failed:
        report_lines.append("")
        report_lines.append("❌ Xatolar (Meta hisobda hech narsa o'zgarmadi):")
        for f in failed:
            obj_name = f["action"].get("object_name", f["action"].get("object_id", "?"))
            report_lines.append(f"  • {obj_name}: {f['error']}")
    creative_or_form_actions = [
        a for a in targetolog_plan.get("actions", [])
        if a["type"] in ("replace_creative", "create_instant_form")
    ]
    if creative_or_form_actions:
        report_lines.append("")
        report_lines.append("🎨 Qo'lda bajarish kerak bo'lgan takliflar:")
        for a in creative_or_form_actions:
            report_lines.append(f"  • {a['object_name']}: {a['reason']}")

    return "\n".join(report_lines)


def run_analysis_cycle(dry_run: bool = False) -> str:
    """To'liq hisobni tahlil qiladi (barcha kampaniya/adset/ad + region breakdown).
    Telegram bot `/analyze` buyrug'i shu funksiyani chaqiradi."""
    data = gather_data()
    data_json = json.dumps(data, ensure_ascii=False, indent=2)
    return _run_pipeline(
        f"Quyidagi ma'lumotlar asosida to'liq hisobni tahlil qilib action_plan tuzing:\n\n{data_json}",
        dry_run=dry_run,
    )


def handle_chat_command(user_text: str, recent_history: list[dict] | None = None) -> str | None:
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
        model=MODEL,
        max_tokens=20,
        system=(
            "Foydalanuvchi xabari qaysi turga kiradi? Faqat bitta so'z bilan javob ber:\n"
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

    message = (
        "Foydalanuvchi Telegram orqali quyidagi amaliy buyruqni berdi (kerak bo'lsa "
        f"suhbat konteksti bilan birga):{history_text}\n\n"
        f"Yangi xabar: \"{user_text}\"\n\n"
        "Joriy hisobdagi kampaniya/adset/ad nomlari va ID'lari (targeting "
        f"tafsilotlarisiz — kerak bo'lsa alohida so'rang):\n{structure_json}\n\n"
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

    return _finish_pipeline(targetolog_plan, dry_run=False)


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
        model=MODEL,
        max_tokens=1200,
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
