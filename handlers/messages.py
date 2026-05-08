from aiogram import Router, F, types
from services.ai_analyzer import AIAnalyzer
from services.report_builder import build_target_report
from services.meta_ads_service import MetaAdsService
from services.date_parser import is_date_request, parse_date_request
from config.settings import ADMIN_ID
from utils.logger import logger

router = Router()

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

# Optimization/Secret keywords (admin only)
ADMIN_ONLY_KEYWORDS = [
    "analyze", "tahlil", "optimization", "optimizatsiya", 
    "recommendation", "tavsiya", "yaxshi", "yomon", "eng yaxshi",
    "eng yomon", "o'chirish", "yoqish", "lead sifati", "quality",
    "campaign analysis", "maxfiy", "confidential"
]

@router.message(F.text)
async def handle_text_message(message: types.Message):
    text = message.text.lower()
    user_id = message.from_user.id
    is_user_admin = is_admin(user_id)
    is_private = message.chat.type == "private"

    # 1. Sana bo'yicha statistika so'rovi (Natural Language)
    if is_date_request(text):
        date_data = parse_date_request(text)
        if date_data:
            await message.answer("⏳ Ma'lumot qidirilmoqda...")
            
            # Admin mode: faqat private chatda va admin bo'lsa
            admin_mode = is_user_admin and is_private
            
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

    # 2. Maxfiy/Optimization savollar (Faqat admin uchun)
    is_confidential = any(kw in text for kw in ADMIN_ONLY_KEYWORDS)
    if is_confidential and not is_user_admin:
        await message.answer("Uzr, bu ma'lumot va tahlillar faqat admin uchun mavjud.")
        return

    # 3. AI Assistant bilan muloqot
    # Faqat savolga o'xshash yoki marketing mavzusidagi xabarlarga javob beradi
    # (AIAnalyzer ichida IGNORE logikasi bor)
    ai = AIAnalyzer()
    meta = MetaAdsService()
    
    # Kontekst uchun bugungi data (admin bo'lsa)
    account_data = None
    campaigns = None
    yesterday_data = None
    
    if is_user_admin:
        account_data = await meta.get_account_insights("today")
        campaigns = await meta.get_campaign_insights("today")
        yesterday_data = await meta.get_account_insights("yesterday")

    answer = await ai.answer_question(
        question=message.text,
        account_data=account_data,
        campaigns=campaigns,
        yesterday_data=yesterday_data,
        is_admin=is_user_admin
    )
    
    if answer and answer != "IGNORE":
        await message.answer(answer)
