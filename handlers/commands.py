from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from services.report_builder import build_target_report, build_campaigns_report
from config.settings import ADMIN_ID

router = Router()


# === HELPER FUNCTIONS ===

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

def is_private_chat(message: types.Message) -> bool:
    return message.chat.type == "private"

def is_group_chat(message: types.Message) -> bool:
    return message.chat.type in ["group", "supergroup"]


# === COMMANDS ===

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    if is_admin(message.from_user.id):
        text = (
            "🤖 *DUNYABUNYA AI TARGET ASSISTANT*\n\n"
            "Assalomu alaykum, Admin 👋\n\n"
            "Sizga to'liq access berilgan:\n"
            "📊 Real-time statistika\n"
            "🤖 AI tahlil va takliflar\n"
            "📋 Kampaniya tahlili\n"
            "🎬 Kreativ va strategiya\n\n"
            "👉 /help — barcha buyruqlar"
        )
    else:
        text = (
            "🤖 *DUNYABUNYA AI TARGET ASSISTANT*\n\n"
            "Assalomu alaykum 👋\n\n"
            "Men sizga marketing va kreativ bo'yicha yordam bera olaman:\n"
            "🎬 Reels ssenariy\n"
            "✍️ Caption, hook, ad copy\n"
            "🎯 Target maslahat\n"
            "💡 Marketing strategiya\n\n"
            "📊 *Statistika* guruhda mavjud.\n\n"
            "👉 /help — yordam"
        )
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    if is_admin(message.from_user.id):
        text = (
            "📌 *ADMIN BUYRUQLARI*\n\n"
            "📈 *Statistika:*\n"
            "/today — bugungi\n"
            "/yesterday — kechagi\n"
            "/week — haftalik\n"
            "/month — oylik\n"
            "/campaigns — kampaniyalar\n"
            "/analyze — AI tahlil\n\n"
            "🎬 *AI Assistant:*\n"
            "Kreativ, reels, strategiya, target — hamma narsani so'rang.\n"
        )
    else:
        text = (
            "📌 *BOT YORDAMI*\n\n"
            "🎬 *AI Assistant (private chatda):*\n"
            "• creative yozib ber\n"
            "• reels ssenariy\n"
            "• hook yoz\n"
            "• caption yoz\n"
            "• marketing maslahat\n\n"
            "📊 *Statistika (faqat guruhda):*\n"
            "/today, /yesterday, /week, /month\n"
            "Yoki: '1-may hisobot', 'haftalik statistika'\n\n"
            "⚠️ AI analiz va kampaniya tahlili faqat admin uchun."
        )
    await message.answer(text, parse_mode="Markdown")


# === REPORT COMMANDS ===

async def _send_report(message: types.Message, period: str):
    """
    Report yuborish logikasi:
    - Admin private: to'liq report + AI
    - Admin guruhda: public KPI
    - Oddiy user guruhda: public KPI
    - Oddiy user private: ❌ ruxsat yo'q
    """
    user_admin = is_admin(message.from_user.id)
    private = is_private_chat(message)

    # Oddiy user private chatda statistika so'rayapti — rad etamiz
    if private and not user_admin:
        await message.answer(
            "❌ Uzr, private chatda bu ma'lumotlar faqat admin uchun mavjud.\n\n"
            "📊 Statistikani guruhda olishingiz mumkin."
        )
        return

    await message.answer("⏳ Yuklanmoqda...")

    # Admin private chatda — to'liq report
    if private and user_admin:
        report = await build_target_report(
            period=period, is_admin=True, include_analysis=True
        )
    else:
        # Guruhda — hammaga faqat public KPI
        report = await build_target_report(
            period=period, is_admin=False, include_analysis=False
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


# === ADMIN-ONLY COMMANDS ===

@router.message(Command("campaigns"))
async def cmd_campaigns(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bu funksiya faqat admin uchun mavjud.")
        return
    if not is_private_chat(message):
        await message.answer("⚠️ Kampaniya ma'lumotlari faqat shaxsiy chatda ko'rsatiladi.")
        return

    await message.answer("⏳ Kampaniyalar yuklanmoqda...")
    report = await build_campaigns_report("today")
    await message.answer(report)

@router.message(Command("analyze"))
async def cmd_analyze(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bu funksiya faqat admin uchun mavjud.")
        return
    if not is_private_chat(message):
        await message.answer("⚠️ AI analiz faqat shaxsiy chatda ko'rsatiladi.")
        return

    await message.answer("🤖 AI tahlil qilinmoqda...")
    report = await build_target_report("today", is_admin=True, include_analysis=True)
    await message.answer(report)
