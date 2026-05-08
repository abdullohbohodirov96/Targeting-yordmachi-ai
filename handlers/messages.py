from aiogram import Router, F, types
from services.ai_analyzer import AIAnalyzer
from services.meta_ads_service import MetaAdsService
from config.settings import ADMIN_ID
from utils.logger import logger

router = Router()

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

def is_marketing_topic(text: str) -> bool:
    """Marketing/target mavzusiga tegishli kalit so'zlarni tekshiradi."""
    keywords = [
        # Target & Ads
        "target", "reklama", "kreativ", "creative", "cpl", "ctr", "cpm", "cpc",
        "budget", "byudjet", "lead", "lid", "audience", "kampaniya", "campaign",
        "roas", "pixel", "conversion", "konversiya",
        # Creative & Content
        "reels", "ssenariy", "hook", "caption", "oferta", "offer",
        "ad copy", "content plan", "kontent", "post", "story", "stories",
        # Sales & Strategy
        "dm", "script", "strategiya", "strategy", "sales", "sotish", "savdo",
        "marketing", "funnel", "voronka",
        # Products
        "gipsokarton", "linoleum", "kafel", "oboy", "santexnika",
        "plitka", "eshik", "lyustra", "tarkett",
        # Bot
        "bot", "hisobot", "report",
    ]
    text_lower = text.lower()
    for kw in keywords:
        if kw in text_lower:
            return True
    return False

@router.message(F.text)
async def handle_text_questions(message: types.Message):
    """
    Foydalanuvchi erkin matnli savol berganida.
    Admin — barcha marketing vazifalarni bajaradi + real data konteksti.
    Oddiy user — faqat umumiy marketing/creative yordam, maxfiy raqamlar yo'q.
    """
    is_group = message.chat.type in ["group", "supergroup"]

    is_reply_to_bot = (message.reply_to_message and 
                       message.reply_to_message.from_user.id == message.bot.id)

    # Topic detection
    should_answer = False
    if not is_group:
        should_answer = True  # Private chatda doim harakat qiladi, AI "IGNORE" qaytarishi mumkin
    else:
        if is_reply_to_bot or is_marketing_topic(message.text):
            should_answer = True

    if not should_answer:
        return

    admin_status = is_admin(message.from_user.id)
    await message.chat.do("typing")

    try:
        ai = AIAnalyzer()

        # Maxfiy ma'lumotlarni faqat admin uchun olamiz
        data = {}
        campaigns = []
        yesterday_data = {}

        if admin_status:
            meta = MetaAdsService()
            data = await meta.get_account_insights("today")
            campaigns_result = await meta.get_campaign_insights("today")
            campaigns = campaigns_result if campaigns_result is not None else []
            yesterday_result = await meta.get_account_insights("yesterday")
            yesterday_data = yesterday_result if yesterday_result is not None else {}

        answer = await ai.answer_question(
            message.text, data, campaigns, yesterday_data, is_admin=admin_status
        )

        # Agar bot mavzudan tashqari deb topsa, indamaydi
        if answer and answer.strip() != "IGNORE":
            await message.reply(f"🤖 Assistant:\n\n{answer}")

    except Exception as e:
        logger.error(f"Savol-javob xatolik: {e}")
