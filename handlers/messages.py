from aiogram import Router, F, types
from services.ai_analyzer import AIAnalyzer
from services.meta_ads_service import MetaAdsService
from config.settings import ADMIN_ID
from utils.logger import logger

router = Router()

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

@router.message(F.text)
async def handle_text_questions(message: types.Message):
    """
    Foydalanuvchi erkin matnli savol berganida.
    Guruhda faqat "bot" so'zi qatnashsa yoki botga reply qilingan bo'lsa.
    Private chatda hamma yozuv.
    Faqat admin ruxsatga ega. Boshqalarga access denied.
    """
    is_group = message.chat.type in ["group", "supergroup"]
    text_lower = message.text.lower()
    
    # Trigger logikasi
    should_answer = False
    if not is_group:
        should_answer = True
    else:
        # Guruhda "bot" so'zi yoki bot xabariga reply qilingan bo'lsa
        is_reply_to_bot = (message.reply_to_message and 
                           message.reply_to_message.from_user.id == message.bot.id)
        if "bot" in text_lower or is_reply_to_bot:
            should_answer = True

    if not should_answer:
        return

    # Ruxsat tekshirish
    if not is_admin(message.from_user.id):
        if is_group:
            await message.reply("Uzr, sizga bu ma’lumotlarni tashlab bera olmayman.")
        else:
            await message.reply("Uzr, sizga bu ma’lumotlarni bera olmayman.")
        return

    # AI javob tayyorlash
    await message.chat.do("typing")
    try:
        meta = MetaAdsService()
        ai = AIAnalyzer()

        data = await meta.get_account_insights("today")
        campaigns = await meta.get_campaign_insights("today")
        yesterday_data = await meta.get_account_insights("yesterday")
            
        answer = await ai.answer_question(message.text, data, campaigns, yesterday_data)
        await message.reply(f"🤖 Assistant:\n\n{answer}")

    except Exception as e:
        logger.error(f"Savol-javob xatolik: {e}")
        await message.reply("⚠️ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
