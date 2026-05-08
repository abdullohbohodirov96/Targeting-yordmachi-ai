from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from services.report_builder import build_target_report, build_campaigns_report
from config.settings import ADMIN_ID

router = Router()

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    text = (
        "🤖 *DUNYABUNYA AI TARGET ASSISTANT*\n\n"
        "Assalomu alaykum 👋\n\n"
        "Men orqali Meta Ads hisobotlarini olishingiz va marketing bo'yicha maslahat olishingiz mumkin.\n\n"
        "📊 *Statistika buyruqlari:*\n"
        "/today — bugungi\n"
        "/yesterday — kechagi\n"
        "/week — haftalik (oxirgi 7 kun)\n"
        "/month — oylik (oy boshidan)\n\n"
        "💡 *Natural Language:* Shunchaki '1 may statistika' deb yozishingiz ham mumkin.\n\n"
        "⚠️ *Eslatma:* AI analiz va kampaniyalar tahlili faqat admin uchun."
    )
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    is_user_admin = is_admin(message.from_user.id)
    
    if is_user_admin:
        text = (
            "📌 *ADMIN BUYRUQLARI*\n\n"
            "📈 *Statistika:*\n"
            "/today, /yesterday, /week, /month\n"
            "/analyze — AI tahlil\n"
            "/campaigns — kampaniyalar\n\n"
            "🎬 *AI Assistant:* Kreativ, reels, strategiya haqida so'rang.\n"
        )
    else:
        text = (
            "📌 *FOYDALANUVCHI BUYRUQLARI*\n\n"
            "📈 *Statistika:*\n"
            "/today, /yesterday, /week, /month\n"
            "Yoki: '1-may hisobot', 'haftalik statistika'\n\n"
            "🎬 *AI Assistant:* Kreativ yoki reels ssenariy so'rang.\n"
        )
    await message.answer(text, parse_mode="Markdown")

async def _send_report(message: types.Message, period: str):
    """Umumiy report yuborish logikasi."""
    await message.answer("⏳ Yuklanmoqda...")
    is_user_admin = is_admin(message.from_user.id)
    is_private = message.chat.type == "private"
    
    # Faqat private chatda va admin bo'lsa - to'liq report, aks holda public
    admin_mode = is_user_admin and is_private
    
    report = await build_target_report(
        period=period, 
        is_admin=admin_mode, 
        include_analysis=admin_mode
    )
    await message.answer(report)

@router.message(Command("today"))
async def cmd_today(message: types.Message):
    await _send_report(message, "today")

@router.message(Command("yesterday"))
async def cmd_yesterday(message: types.Message):
    await _send_report(message, "yesterday")

@router.message(Command("week"))
async def cmd_week(message: types.Message):
    await _send_report(message, "week")

@router.message(Command("month"))
async def cmd_month(message: types.Message):
    await _send_report(message, "month")

@router.message(Command("campaigns"))
async def cmd_campaigns(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Uzr, bu ma'lumot faqat admin uchun.")
        return
    if message.chat.type != "private":
        await message.answer("⚠️ Maxfiy ma'lumotlar faqat shaxsiy chatda ko'rsatiladi.")
        return
    
    await message.answer("⏳ Kampaniyalar yuklanmoqda...")
    report = await build_campaigns_report("today")
    await message.answer(report)

@router.message(Command("analyze"))
async def cmd_analyze(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Uzr, bu ma'lumot faqat admin uchun.")
        return
    if message.chat.type != "private":
        await message.answer("⚠️ AI analiz faqat shaxsiy chatda ko'rsatiladi.")
        return
        
    await message.answer("🤖 AI tahlil qilinmoqda...")
    report = await build_target_report("today", is_admin=True, include_analysis=True)
    await message.answer(report)
