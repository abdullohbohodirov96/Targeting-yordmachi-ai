from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from services.ai_analyzer import AIAnalyzer
from services.report_builder import build_target_report
from services.meta_ads_service import MetaAdsService
from services.date_parser import is_date_request, parse_date_request
from services.cpl_limits import get_all_limits
from handlers.actions import handle_action_request
from utils.intent_classifier import detect_intent
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
ADMIN_ONLY_KEYWORDS = [
    "analyze", "tahlil", "optimization", "optimizatsiya",
    "recommendation", "tavsiya", "eng yaxshi", "eng yomon",
    "o'chirish kerak", "scale qilish", "lead sifati", "quality",
    "campaign analysis", "maxfiy", "confidential",
    "qaysi kampaniya", "budget oshir", "budget kamayir",
    "target o'zgartir", "audience almashir", "creative fatigue",
]

STATS_KEYWORDS = [
    "statistika", "hisobot", "report", "natija",
    "cpl", "spend", "xarajat", "lead", "ctr", "cpm",
    "campaign", "kampaniya", "analyze", "tahlil",
    "target natija", "reklama natija", "ads data",
]

@router.message(F.text)
async def handle_text_message(message: types.Message, state: FSMContext = None):
    text = message.text.strip()
    text_lower = text.lower()
    user_id = message.from_user.id
    user_admin = is_admin(user_id)
    private = is_private_chat(message)

    # 1. Intentni aniqlaymiz
    intent = detect_intent(text)
    logger.info(f"Detected intent for '{text}': {intent}")

    # ============================================
    # A) SEND_TO_GROUP (Guruhga xabar yuborish/Task) - HIGHEST PRIORITY
    # ============================================
    if intent == "SEND_TO_GROUP":
        if not user_admin:
            await message.answer("❌ Bu amal faqat admin uchun mavjud.")
            return
        await _process_group_task(message, text)
        return

    # ============================================
    # B) CREATIVE_TASK (Marketing AI Assistant)
    # ============================================
    if intent == "CREATIVE_TASK":
        # Hech qanday Meta object qidirilmaydi, to'g'ridan-to'g'ri AI ga
        await _process_ai_chat(message, text, user_admin)
        return

    # ============================================
    # C) META_STATS (Date/Statistika requests)
    # ============================================
    if intent == "META_STATS" or is_date_request(text_lower):
        if private and not user_admin:
            is_stats_request = any(kw in text_lower for kw in STATS_KEYWORDS)
            if is_stats_request or is_date_request(text_lower):
                await message.answer(
                    "❌ Uzr, private chatda bu ma'lumotlar faqat admin uchun mavjud.\n\n"
                    "📊 Statistikani guruhda olishingiz mumkin.\n"
                    "🎬 Bu yerda kreativ, reels, caption, hook so'rashingiz mumkin."
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
                    include_analysis=admin_mode
                )
            else:
                report = await build_target_report(
                    since=date_data["since"],
                    until=date_data["until"],
                    is_admin=admin_mode,
                    include_analysis=admin_mode
                )
        else:
            # Agar sana bo'lmasa lekin statistika so'ralsa, bugungini beramiz
            report = await build_target_report(
                period="today",
                is_admin=admin_mode,
                include_analysis=admin_mode
            )
            
        await message.answer(report)
        return

    # ============================================
    # D) CPL_LIMIT (Limit o'rnatish/ko'rish)
    # ============================================
    if intent == "CPL_LIMIT":
        if not user_admin:
            await message.answer("❌ Bu amal faqat admin uchun mavjud.")
            return

        # "ko'r", "kor", "ko'rsat", "qancha", "nechi" so'zlari bo'lsa - limitlarni ko'rsat
        view_keywords = ["ko'r", "kor", "ko'rsat", "korsat", "qancha", "nechi", "necha", "bor", "qaysi"]
        if any(kw in text_lower for kw in view_keywords):
            limits = get_all_limits()
            if not limits:
                await message.answer(
                    "📋 Hozircha hech qanday CPL limit o'rnatilmagan.\n\n"
                    "Limit o'rnatish uchun: /setlimit"
                )
            else:
                lines = ["📊 <b>CPL LIMITLAR</b>\n"]
                for cid, info in limits.items():
                    cname = info.get("campaign_name", "Noma'lum")
                    cpl_limit = info.get("cpl_limit", 0)
                    lines.append(f"🎯 {cname}\n   🚫 Max CPL: ${cpl_limit:.2f}")
                lines.append("\n📝 O'zgartirish: /setlimit")
                await message.answer("\n".join(lines), parse_mode="HTML")
        else:
            # Limit o'rnatish — setlimit flow ga yo'naltirish
            from handlers.commands import cmd_setlimit
            await cmd_setlimit(message, state)
        return

    # ============================================
    # E) META_ACTION (O'zgartirishlar, pause, budget)
    # ============================================
    if intent == "META_ACTION":
        if not user_admin:
            await message.answer("❌ Bu amal faqat admin uchun mavjud.")
            return
        
        handled = await handle_action_request(message)
        if handled:
            return

    # ============================================
    # F) OBJECT_SEARCH (Faqat aniq qidiruv buyruqlari)
    # ============================================
    if intent == "OBJECT_SEARCH":
        if not user_admin:
            await message.answer("❌ Bu amal faqat admin uchun mavjud.")
            return
            
        await _process_object_search(message, text_lower)
        return

    # ============================================
    # G) AI_CHAT / DEFAULT (Qolgan holatlar)
    # ============================================
    is_confidential = any(kw in text_lower for kw in ADMIN_ONLY_KEYWORDS)
    if is_confidential and not user_admin:
        await message.answer("❌ Bu funksiya faqat admin uchun mavjud.")
        return
        
    await _process_ai_chat(message, text, user_admin)


async def _process_ai_chat(message: types.Message, text: str, user_admin: bool):
    ai = AIAnalyzer()
    meta = MetaAdsService()

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


async def _process_group_task(message: types.Message, text: str):
    from config.settings import GROUP_ID
    
    ai = AIAnalyzer()
    # Taskni analiz qilish va guruhga mos formatga keltirish
    await message.answer("🤖 Vazifa tahlil qilinmoqda...")
    result = await ai.analyze_task(text)
    
    if result.get("can_do"):
        if result.get("action") == "send_to_group":
            if not GROUP_ID:
                await message.answer("❌ GROUP_ID sozlanmagan. Xabar yubora olmayman.")
                return
            
            formatted_text = result.get("formatted_text")
            try:
                await message.bot.send_message(chat_id=GROUP_ID, text=formatted_text)
                await message.answer(f"✅ Guruhga yuborildi:\n\n{formatted_text}")
            except Exception as e:
                logger.error(f"Group send error: {e}")
                await message.answer(f"❌ Xatolik yuz berdi: {e}")
        else:
            await message.answer(f"🤖 Task tahlili: {result.get('message')}")
    else:
        error_msg = result.get('message', 'Nomalum sabab')
        await message.answer(f"❌ Kechirasiz, bu vazifani bajara olmayman: {error_msg}")


async def _process_object_search(message: types.Message, text_lower: str):
    meta = MetaActionsService()
    
    obj_type = "campaigns"
    query = ""
    
    if text_lower.startswith("adset qidir:"):
        obj_type = "adsets"
        query = text_lower.replace("adset qidir:", "").strip()
    elif text_lower.startswith("campaign qidir:"):
        obj_type = "campaigns"
        query = text_lower.replace("campaign qidir:", "").strip()
    elif text_lower.startswith("ads qidir:") or text_lower.startswith("reklamani top:"):
        obj_type = "ads"
        query = text_lower.replace("ads qidir:", "").replace("reklamani top:", "").strip()
        
    if not query:
        await message.answer("⚠️ Qidiruv so'zini kiriting.")
        return
        
    await message.answer(f"🔍 {obj_type} bo'yicha qidirilmoqda: '{query}'...")
    matches = await meta.search_objects(query, obj_type)
    
    if not matches:
        await message.answer(f"❌ '{query}' bo'yicha hech qanday {obj_type} topilmadi.")
        return
        
    result_text = f"✅ Topildi ({len(matches)} ta):\n\n"
    for obj in matches[:10]:
        result_text += f"📋 Nomi: {obj.get('name')}\n"
        result_text += f"🔢 ID: {obj.get('id')}\n"
        result_text += f"📊 Status: {obj.get('status')}\n\n"
        
    await message.answer(result_text)
