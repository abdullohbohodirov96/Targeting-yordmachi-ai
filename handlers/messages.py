from aiogram import Router, F, types
from services.ai_analyzer import AIAnalyzer
from services.meta_ads_service import MetaAdsService
from utils.logger import logger

router = Router()


@router.message(F.text)
async def handle_text_questions(message: types.Message):
    """
    Foydalanuvchi erkin matnli savol berganida AI javob qaytaradi.
    Real ma'lumotlar asosida javob beradi.
    """
    try:
        meta = MetaAdsService()
        ai = AIAnalyzer()

        # Real data olish
        data = await meta.get_account_insights("today")
        campaigns = await meta.get_campaign_insights("today")

        # AI javob
        answer = await ai.answer_question(message.text, data, campaigns)
        await message.reply(f"🤖 AI Javobi:\n\n{answer}")

    except Exception as e:
        logger.error(f"Savol-javob xatolik: {e}")
        await message.reply("⚠️ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
