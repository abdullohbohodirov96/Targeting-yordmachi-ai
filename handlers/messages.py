from aiogram import Router, F, types
from services.ai_analyzer import AIAnalyzer
from services.report_builder import build_target_report
from services.meta_ads_service import MetaAdsService
from services.date_parser import is_date_request, parse_date_request
from handlers.actions import handle_action_request
from config.settings import ADMIN_ID
from utils.logger import logger

router = Router()


# === HELPERS ===

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

def is_private_chat(message: types.Message) -> bool:
    return message.chat.type == "private"

def is_group_chat(message: types.Message) -> bool:
    return message.chat.type in ["group", "supergroup"]


# === ADMIN-ONLY KEYWORDS ===
# Bu so'zlar ishlatilsa, faqat admin javob oladi

ADMIN_ONLY_KEYWORDS = [
    "analyze", "tahlil", "optimization", "optimizatsiya",
    "recommendation", "tavsiya", "eng yaxshi", "eng yomon",
    "o'chirish kerak", "scale qilish", "lead sifati", "quality",
    "campaign analysis", "maxfiy", "confidential",
    "qaysi kampaniya", "budget oshir", "budget kamayir",
    "target o'zgartir", "audience almashir", "creative fatigue",
]

# Oddiy user private chatda statistika so'raganda bloklash uchun
STATS_KEYWORDS = [
    "statistika", "hisobot", "report", "natija",
    "cpl", "spend", "xarajat", "lead", "ctr", "cpm",
    "campaign", "kampaniya", "analyze", "tahlil",
    "target natija", "reklama natija", "ads data",
]


@router.message(F.text)
async def handle_text_message(message: types.Message):
    text = message.text.strip()
    text_lower = text.lower()
    user_id = message.from_user.id
    user_admin = is_admin(user_id)
    private = is_private_chat(message)
    group = is_group_chat(message)

    # ============================================
    # 1. NATURAL LANGUAGE DATE REQUEST
    # ============================================
    if is_date_request(text_lower):
        date_data = parse_date_request(text_lower)
        if date_data:
            # Oddiy user private chatda — statistika taqiqlangan
            if private and not user_admin:
                await message.answer(
                    "❌ Uzr, private chatda bu ma'lumotlar faqat admin uchun mavjud.\n\n"
                    "📊 Statistikani guruhda olishingiz mumkin."
                )
                return

            await message.answer("⏳ Ma'lumot qidirilmoqda...")

            # Admin private: full report, guruh: public KPI
            admin_mode = user_admin and private

            if "period" in date_data:
                report = await build_target_report(
                    period=date_data["period"],
                    is_admin=admin_mode,
                    include_analysis=admin_mode
                )
            else:
                report = await build_target_report(
                    since=date_data["since"],
                    until=date_data["until"],
                    is_admin=admin_mode,
                    include_analysis=admin_mode
                )
            await message.answer(report)
            return

    # ============================================
    # 2. ODDIY USER PRIVATE CHATDA STATISTIKA SO'RASA — BLOKLASH
    # ============================================
    if private and not user_admin:
        is_stats_request = any(kw in text_lower for kw in STATS_KEYWORDS)
        if is_stats_request:
            await message.answer(
                "❌ Uzr, private chatda bu ma'lumotlar faqat admin uchun mavjud.\n\n"
                "📊 Statistikani guruhda olishingiz mumkin.\n"
                "🎬 Bu yerda kreativ, reels, caption, hook so'rashingiz mumkin."
            )
            return

    # ============================================
    # 3. ADMIN ACTION REQUESTS (pause/enable/budget)
    # ============================================
    if user_admin:
        handled = await handle_action_request(message)
        if handled:
            return

    # ============================================
    # 4. MAXFIY ADMIN-ONLY SAVOLLAR (private va guruhda)
    # ============================================
    is_confidential = any(kw in text_lower for kw in ADMIN_ONLY_KEYWORDS)
    if is_confidential and not user_admin:
        await message.answer("❌ Bu funksiya faqat admin uchun mavjud.")
        return

    # ============================================
    # 5. AI ASSISTANT
    # ============================================
    ai = AIAnalyzer()
    meta = MetaAdsService()

    # Admin uchun real data kontekstini beramiz
    account_data = None
    campaigns = None
    yesterday_data = None

    if user_admin:
        account_data = await meta.get_account_insights("today")
        campaigns = await meta.get_campaign_insights("today")
        yesterday_data = await meta.get_account_insights("yesterday")

    answer = await ai.answer_question(
        question=text,
        account_data=account_data,
        campaigns=campaigns,
        yesterday_data=yesterday_data,
        is_admin=user_admin
    )

    if answer and answer != "IGNORE":
        await message.answer(answer)
