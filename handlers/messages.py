from aiogram import Router, F, types
from services.ai_analyzer import AIAnalyzer
from services.meta_ads_service import MetaAdsService
from config.settings import OPENAI_API_KEY, META_ACCESS_TOKEN, META_AD_ACCOUNT_ID

router = Router()

@router.message(F.text)
async def handle_text_messages(message: types.Message):
    ai_service = AIAnalyzer(OPENAI_API_KEY)
    meta_service = MetaAdsService(META_ACCESS_TOKEN, META_AD_ACCOUNT_ID)
    
    # Ma'lumot olish
    data = await meta_service.get_insights("today")
    
    # Savolga javob olish
    answer = await ai_service.answer_question(message.text, data)
    
    await message.reply(f"🤖 AI Javobi:\n\n{answer}")
