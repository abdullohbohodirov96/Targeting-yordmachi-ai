"""
Buyruq handlerlari: /start, /help, /today, /yesterday, /week, /month, /campaigns, /analyze.
"""
from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from services.report_builder import build_target_report, build_campaigns_report
from utils.company_profile import is_profile_setup, get_company_name
from config.settings import ADMIN_ID

router = Router()


def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


def is_private_chat(message: types.Message) -> bool:
    return message.chat.type == "private"


def is_group_chat(message: types.Message) -> bool:
    return message.chat.type in ["group", "supergroup"]


# ── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    from handlers.company_setup import begin_setup

    if is_admin(message.from_user.id) and is_private_chat(message):
        # Admin — profil sozlanganmi?
        if not is_profile_setup():
            await begin_setup(message, state)
            return

        company_name = get_company_name()
        text = (
            f"🤖 *AI TARGETING MUTAXASSISI*\n\n"
            f"Assalomu alaykum, Admin! 👋\n"
            f"Kompaniya: *{company_name}*\n\n"
            f"Sizga to'liq imkoniyatlar mavjud:\n"
            f"📊 Real-time statistika va AI tahlil\n"
            f"🎯 Kampaniya boshqaruvi (pause, enable, budget)\n"
            f"🔍 Kampaniya/adset qidirish\n"
            f"🎬 Kreativ va strategiya maslahat\n"
            f"🤖 Avtomatik monitoring va kritik CPL auto-pause\n\n"
            f"👉 /help — barcha buyruqlar\n"
            f"👉 /setup — kompaniya profilini yangilash"
        )
    else:
        text = (
            "🤖 *AI TARGETING MUTAXASSISI*\n\n"
            "Assalomu alaykum! 👋\n\n"
            "Men sizga quyidagilar bo'yicha yordam beraman:\n"
            "🎬 Reels ssenariy va kreativ g'oyalar\n"
            "✍️ Caption, hook, ad copy\n"
            "🎯 Target va auditoriya maslahat\n"
            "💡 Marketing strategiya\n\n"
            "📊 Statistika guruhda mavjud.\n\n"
            "👉 /help — yordam"
        )
    await message.answer(text, parse_mode="Markdown")


# ── /help ────────────────────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    if is_admin(message.from_user.id):
        text = (
            "📌 *BUYRUQLAR VA IMKONIYATLAR*\n\n"
            "📈 *Statistika:*\n"
            "/today — bugungi\n"
            "/yesterday — kechagi\n"
            "/week — haftalik\n"
            "/month — oylik\n"
            "/campaigns — kampaniyalar ro'yxati\n"
            "/analyze — AI tahlil\n\n"
            "🎯 *Kampaniya boshqaruvi:*\n"
            "• \"bazalt kampaniyani o'chir\"\n"
            "• \"remont adsetini yoq\"\n"
            "• \"20$ budget qo'y\"\n"
            "• \"bazaltni copy qil\"\n\n"
            "🔍 *Qidirish:*\n"
            "• \"bazaltni qidir\"\n"
            "• \"adset qidir: remont\"\n"
            "• \"reklamalarni ko'rsat\"\n\n"
            "🎬 *AI Kreativ:*\n"
            "• \"reels ssenariy yoz\"\n"
            "• \"hook ber\", \"caption yoz\"\n"
            "• \"target maslahat ber\"\n\n"
            "⚙️ *Sozlamalar:*\n"
            "/setup — kompaniya profilini yangilash\n\n"
            "🤖 *Avtomatik:*\n"
            "• Har soat monitoring\n"
            "• Kritik CPL (2x) → auto-pause"
        )
    else:
        text = (
            "📌 *BOT YORDAMI*\n\n"
            "🎬 *AI Kreativ (private chatda):*\n"
            "• creative yoz, reels ssenariy\n"
            "• hook yoz, caption yoz\n"
            "• marketing maslahat\n\n"
            "📊 *Statistika (guruhda):*\n"
            "/today, /yesterday, /week, /month\n"
            "Yoki: '1-may hisobot', 'haftalik statistika'\n\n"
            "⚠️ AI tahlil va kampaniya boshqaruvi faqat admin uchun."
        )
    await message.answer(text, parse_mode="Markdown")


# ── Hisobot buyruqlari ───────────────────────────────────────────────────────

async def _send_report(message: types.Message, period: str):
    user_admin = is_admin(message.from_user.id)
    private = is_private_chat(message)

    if private and not user_admin:
        await message.answer(
            "❌ Private chatda statistika faqat admin uchun.\n\n"
            "📊 Statistikani guruhda ko'ring."
        )
        return

    await message.answer("⏳ Yuklanmoqda...")

    if private and user_admin:
        report = await build_target_report(period=period, is_admin=True, include_analysis=True)
    else:
        report = await build_target_report(period=period, is_admin=False, include_analysis=False)

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


# ── Admin buyruqlari ─────────────────────────────────────────────────────────

@router.message(Command("campaigns"))
async def cmd_campaigns(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bu funksiya faqat admin uchun.")
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
        await message.answer("❌ Bu funksiya faqat admin uchun.")
        return
    if not is_private_chat(message):
        await message.answer("⚠️ AI analiz faqat shaxsiy chatda ko'rsatiladi.")
        return
    await message.answer("🤖 AI tahlil qilinmoqda...")
    report = await build_target_report("today", is_admin=True, include_analysis=True)
    await message.answer(report)
