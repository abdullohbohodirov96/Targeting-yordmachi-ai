"""
Asosiy xabar router.
Tabiiy til intenti aniqlaydi va tegishli handlerga yo'naltiradi.
"""
from aiogram import Router, F, types
from services.ai_analyzer import AIAnalyzer
from services.report_builder import build_target_report
from services.meta_ads_service import MetaAdsService
from services.meta_actions_service import MetaActionsService
from services.date_parser import is_date_request, parse_date_request
from handlers.actions import handle_action_request
from utils.intent_classifier import detect_intent, extract_search_params
from utils.company_profile import is_profile_setup
from config.settings import ADMIN_ID
from utils.logger import logger

router = Router()


# ── Yordamchi funksiyalar ────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


def is_private_chat(message: types.Message) -> bool:
    return message.chat.type == "private"


def is_group_chat(message: types.Message) -> bool:
    return message.chat.type in ["group", "supergroup"]


ADMIN_ONLY_KW = [
    "analyze", "tahlil", "optimization", "optimizatsiya",
    "recommendation", "tavsiya", "eng yaxshi", "eng yomon",
    "o'chirish kerak", "scale qilish", "lead sifati", "quality",
    "campaign analysis", "qaysi kampaniya", "budget oshir",
    "target o'zgartir", "creative fatigue",
]

STATS_KW = [
    "statistika", "hisobot", "report", "natija",
    "cpl", "spend", "xarajat", "lead", "ctr", "cpm",
    "campaign", "kampaniya", "analyze", "tahlil",
    "target natija", "reklama natija", "ads data",
]


# ── Asosiy handler ──────────────────────────────────────────────────────────

@router.message(F.text)
async def handle_text_message(message: types.Message):
    text = message.text.strip()
    text_lower = text.lower()
    user_id = message.from_user.id
    user_admin = is_admin(user_id)
    private = is_private_chat(message)

    # Kompaniya profili sozlanmagan bo'lsa — admin'ga eslatma
    if user_admin and private and not is_profile_setup():
        # Faqat buyruq bo'lmasa eslatma chiqar
        if not text.startswith("/"):
            await message.answer(
                "⚠️ Kompaniya profili hali sozlanmagan.\n\n"
                "Menga kompaniyangiz haqida aytib bering — shunda men sizga aniqroq yordam bera olaman.\n\n"
                "👉 /setup — kompaniya profilini sozlash"
            )

    intent = detect_intent(text)
    logger.info(f"Intent: '{text[:50]}' → {intent}")

    # ── A) SEND_TO_GROUP ─────────────────────────────────────────────────
    if intent == "SEND_TO_GROUP":
        if not user_admin:
            await message.answer("❌ Bu amal faqat admin uchun.")
            return
        await _process_group_task(message, text)
        return

    # ── B) CREATIVE_TASK ─────────────────────────────────────────────────
    if intent == "CREATIVE_TASK":
        await _process_ai_chat(message, text, user_admin, user_id)
        return

    # ── C) META_STATS ────────────────────────────────────────────────────
    if intent == "META_STATS" or is_date_request(text_lower):
        if private and not user_admin:
            await message.answer(
                "❌ Private chatda statistika faqat admin uchun.\n\n"
                "📊 Statistikani guruhda ko'rish mumkin.\n"
                "🎬 Bu yerda kreativ, reels, caption so'rash mumkin."
            )
            return

        await message.answer("⏳ Ma'lumot qidirilmoqda...")
        admin_mode = user_admin and private
        date_data = parse_date_request(text_lower)

        if date_data:
            if "period" in date_data:
                report = await build_target_report(
                    period=date_data["period"],
                    is_admin=admin_mode,
                    include_analysis=admin_mode,
                )
            else:
                report = await build_target_report(
                    since=date_data["since"],
                    until=date_data["until"],
                    is_admin=admin_mode,
                    include_analysis=admin_mode,
                )
        else:
            report = await build_target_report(
                period="today",
                is_admin=admin_mode,
                include_analysis=admin_mode,
            )
        await message.answer(report)
        return

    # ── D) META_ACTION ───────────────────────────────────────────────────
    if intent == "META_ACTION":
        if not user_admin:
            await message.answer("❌ Bu amal faqat admin uchun.")
            return
        handled = await handle_action_request(message)
        if handled:
            return
        # Agar handle bo'lmasa AI ga o'tkazamiz
        await _process_ai_chat(message, text, user_admin, user_id)
        return

    # ── E) OBJECT_SEARCH ─────────────────────────────────────────────────
    if intent == "OBJECT_SEARCH":
        if not user_admin:
            await message.answer("❌ Bu amal faqat admin uchun.")
            return
        await _process_object_search(message, text)
        return

    # ── F) AI_CHAT (default) ─────────────────────────────────────────────
    if any(kw in text_lower for kw in ADMIN_ONLY_KW) and not user_admin:
        await message.answer("❌ Bu funksiya faqat admin uchun.")
        return

    await _process_ai_chat(message, text, user_admin, user_id)


# ── Yordamchi handlerlar ─────────────────────────────────────────────────────

async def _process_ai_chat(
    message: types.Message, text: str, user_admin: bool, user_id: int = 0
):
    """AI savol-javob — suhbat tarixini saqlaydi."""
    ai = AIAnalyzer()
    meta = MetaAdsService()

    account_data = campaigns = yesterday_data = None
    if user_admin:
        account_data = await meta.get_account_insights("today")
        campaigns = await meta.get_campaign_insights("today")
        yesterday_data = await meta.get_account_insights("yesterday")

    answer = await ai.answer_question(
        question=text,
        account_data=account_data,
        campaigns=campaigns,
        yesterday_data=yesterday_data,
        is_admin=user_admin,
        user_id=user_id,
    )

    if answer and answer.upper() != "IGNORE":
        await message.answer(answer)


async def _process_group_task(message: types.Message, text: str):
    """Guruhga xabar yuborish."""
    from config.settings import GROUP_ID

    ai = AIAnalyzer()
    await message.answer("🤖 Vazifa tahlil qilinmoqda...")
    result = await ai.analyze_task(text)

    if result.get("can_do"):
        if result.get("action") == "send_to_group":
            if not GROUP_ID:
                await message.answer("❌ GROUP_ID sozlanmagan.")
                return
            formatted = result.get("formatted_text", "")
            try:
                await message.bot.send_message(chat_id=GROUP_ID, text=formatted)
                await message.answer(f"✅ Guruhga yuborildi:\n\n{formatted}")
            except Exception as e:
                logger.error(f"Group send xato: {e}")
                await message.answer(f"❌ Yuborishda xatolik: {e}")
        else:
            await message.answer(f"🤖 {result.get('message', '')}")
    else:
        reason = result.get("message") or "Noma'lum sabab"
        await message.answer(f"❌ Kechirasiz, bu vazifani bajara olmayman: {reason}")


async def _process_object_search(message: types.Message, text: str):
    """
    Tabiiy tildan kampaniya/adset/reklama qidiradi.
    Ham aniq prefikslarni, ham oddiy so'zlashuvni tushunadi.
    """
    meta = MetaActionsService()

    query, obj_type = extract_search_params(text)

    if not query:
        await message.answer(
            "🔍 Qidiruv uchun nom kiriting.\n\n"
            "Misol:\n"
            "• bazaltni qidir\n"
            "• campaign qidir: remont\n"
            "• adset qidir: uy\n"
            "• reklamalarni ko'rsat"
        )
        return

    await message.answer(f"🔍 {obj_type} bo'yicha qidirilmoqda: «{query}»...")
    matches = await meta.search_objects(query, obj_type)

    if not matches:
        await message.answer(
            f"❌ «{query}» bo'yicha {obj_type} topilmadi.\n\n"
            "Nom to'g'rimi? Boshqa so'z bilan sinab ko'ring."
        )
        return

    result_text = f"✅ Topildi: {len(matches)} ta {obj_type}\n\n"
    for obj in matches[:10]:
        status = obj.get("status", "?")
        status_emoji = "🟢" if status == "ACTIVE" else "🔴" if status == "PAUSED" else "⚪️"
        result_text += (
            f"{status_emoji} *{obj.get('name', '?')}*\n"
            f"   ID: `{obj.get('id', '?')}` | Status: {status}\n\n"
        )

    if len(matches) > 10:
        result_text += f"_... va yana {len(matches) - 10} ta_"

    await message.answer(result_text, parse_mode="Markdown")
