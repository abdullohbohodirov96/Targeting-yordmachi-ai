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
    "pause_ad": lambda a: meta_api.pause_object(a["object_id"]),
    "resume_ad": lambda a: meta_api.activate_object(a["object_id"]),
    "increase_budget": lambda a: meta_api.adjust_budget_by_percent(
        a["object_id"], a["params"]["current_daily_budget_cents"], abs(a["params"]["percent"])
    ),
    "decrease_budget": lambda a: meta_api.adjust_budget_by_percent(
        a["object_id"], a["params"]["current_daily_budget_cents"], -abs(a["params"]["percent"])
    ),
    "fix_region_targeting": lambda a: meta_api.set_location_current_city_only(
        a["object_id"], a["params"]["audience_change"]["city_key"]
    ),
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


def _call_agent(system_prompt: str, user_content: str) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    text = response.content[0].text
    # Model ba'zan JSON'ni ```json ... ``` bloki ichida qaytarishi mumkin
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def gather_data() -> dict:
    """Meta API'dan tahlil uchun kerakli barcha ma'lumotni yig'adi."""
    ad_insights = meta_api.get_insights(level="ad", date_preset="last_7d")
    region_breakdown = meta_api.get_insights(
        level="ad", date_preset="last_7d", breakdowns=["region"]
    )
    return {
        "ad_insights": ad_insights,
        "region_breakdown": region_breakdown,
        "business_rules": BUSINESS_RULES,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _run_pipeline(targetolog_user_message: str, dry_run: bool = False) -> str:
    """Targetolog -> Marketolog -> ijro zanjirining umumiy o'zagi. Buni ham
    to'liq hisob tahlili (`run_analysis_cycle`), ham Telegram'dagi erkin
    buyruqlar (`handle_chat_command`) chaqiradi — ikkalasi ham xuddi shu
    ikki bosqichli nazoratdan o'tadi."""

    logger.info("Targetolog agentga so'rov yuborilmoqda...")
    targetolog_plan = _call_agent(TARGETOLOG_SYSTEM, targetolog_user_message)

    logger.info("Marketolog agent tekshirmoqda...")
    marketolog_review = _call_agent(
        MARKETOLOG_SYSTEM,
        "Targetolog taklif qilgan action_plan:\n\n"
        f"{json.dumps(targetolog_plan, ensure_ascii=False, indent=2)}\n\n"
        "Biznes qoidalari:\n"
        f"{json.dumps(BUSINESS_RULES, ensure_ascii=False, indent=2)}",
    )

    executed, skipped = [], []
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
                executed.append({"action": final_action, "result": result})
            except meta_api.MetaAPIError as e:
                logger.exception("Action bajarishda xatolik: %s", action_type)
                executed.append({"action": final_action, "error": str(e)})

    run_log = {
        "timestamp": datetime.utcnow().isoformat(),
        "targetolog_plan": targetolog_plan,
        "marketolog_review": marketolog_review,
        "executed": executed,
        "skipped": skipped,
        "dry_run": dry_run,
    }
    log_path = LOGS_DIR / f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    log_path.write_text(json.dumps(run_log, ensure_ascii=False, indent=2), encoding="utf-8")

    report_lines = [
        "📊 *Target Master — tahlil hisoboti*",
        "",
        f"🎯 Targetolog: {targetolog_plan.get('summary', '')}",
        f"✅ Marketolog: {marketolog_review.get('review_summary', '')}",
        "",
        f"Bajarilgan action'lar: {len(executed)}",
        f"Qo'lda ko'rib chiqish/rad etilgan: {len(skipped)}",
    ]
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
            "ACTION — agar amaliy buyruq bo'lsa (yangi target/kampaniya yoqish, mavjud "
            "reklamani to'xtatish/yoqish, byudjet o'zgartirish, abtest boshlash) yoki shu "
            "buyruqqa javoban berilgan qo'shimcha ma'lumot (byudjet raqami, shahar nomi).\n"
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
    return _run_pipeline(
        "Foydalanuvchi Telegram orqali quyidagi amaliy buyruqni berdi (kerak bo'lsa "
        f"suhbat konteksti bilan birga):{history_text}\n\n"
        f"Yangi xabar: \"{user_text}\"\n\n"
        "Agar bu yangi targeting ishga tushirish bo'lsa, lekin kerakli ma'lumotlar "
        "(soha, maqsad, kunlik byudjet, hudud) yetarli bo'lmasa — `no_action` qaytarib, "
        "`summary` maydonida foydalanuvchidan aynan qaysi ma'lumot yetishmayotganini so'rang. "
        "Yetarli bo'lsa, to'liq action_plan tuzing.",
        dry_run=False,
    )


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
    response = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system=(
            f"{TARGETOLOG_ROLE}\n\n---\n\n# BILIM BAZASI\n\n{KNOWLEDGE_BASE}\n\n---\n\n"
            "MUHIM: Bu safar sendan action_plan JSON EMAS, oddiy o'zbekcha matn "
            "javob kutilyapti. Foydalanuvchi hisobdagi aniq metrika/raqamni "
            "so'ramoqda. Faqat senga berilgan haqiqiy `insights` ma'lumotlaridan "
            "foydalanib javob ber (masalan foiz hisoblash: "
            "video_thruplay_watched_actions / video_play_actions * 100). Agar "
            "kerakli maydon ma'lumotda yo'q bo'lsa, buni ochiq ayt, o'ylab topma. "
            "Javobni Telegram uchun qisqa va tushunarli qil, kerak bo'lsa ad/adset "
            "nomlari bo'yicha alohida ko'rsat."
        ),
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
