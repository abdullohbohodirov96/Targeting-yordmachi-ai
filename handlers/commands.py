from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from services.report_builder import build_target_report, build_campaigns_report

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Assalomu alaykum!\n"
        "Men — AI Target Analytics Bot.\n\n"
        "Meta Ads reklamalaringizni avtomatik tahlil qilaman, "
        "hisobot beraman va AI tavsiyalar chiqaraman.\n\n"
        "📌 Komandalar:\n"
        "/today — Bugungi hisobot\n"
        "/yesterday — Kechagi hisobot\n"
        "/week — Haftalik hisobot\n"
        "/month — Oylik hisobot\n"
        "/campaigns — Kampaniyalar tahlili\n"
        "/analyze — Chuqur AI analiz\n"
        "/help — Yordam\n\n"
        "💬 Menga savol ham berishingiz mumkin:\n"
        "• Nega CPL oshdi?\n"
        "• Qaysi kampaniya yaxshi?\n"
        "• Qaysi reklamani o'chirish kerak?"
    )


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "🛠 Yordam\n\n"
        "/today — Bugungi statistika + AI tahlil\n"
        "/yesterday — Kechagi statistika\n"
        "/week — Haftalik umumiy hisobot\n"
        "/month — Oylik umumiy hisobot\n"
        "/campaigns — Har bir kampaniya alohida\n"
        "/analyze — AI chuqur tahlil\n\n"
        "💬 Matnli savollar ham qo'llab-quvvatlanadi:\n"
        "• Nega CPL oshdi?\n"
        "• Qaysi kampaniya yaxshi?\n"
        "• Bugungi natija qanday?\n"
        "• Qaysi reklamani scale qilish kerak?"
    )


@router.message(Command("today"))
async def cmd_today(message: types.Message):
    await message.answer("⏳ Ma'lumotlar yuklanmoqda...")
    report = await build_target_report("today")
    await message.answer(report)


@router.message(Command("yesterday"))
async def cmd_yesterday(message: types.Message):
    await message.answer("⏳ Ma'lumotlar yuklanmoqda...")
    report = await build_target_report("yesterday")
    await message.answer(report)


@router.message(Command("week"))
async def cmd_week(message: types.Message):
    await message.answer("⏳ Ma'lumotlar yuklanmoqda...")
    report = await build_target_report("week")
    await message.answer(report)


@router.message(Command("month"))
async def cmd_month(message: types.Message):
    await message.answer("⏳ Ma'lumotlar yuklanmoqda...")
    report = await build_target_report("month")
    await message.answer(report)


@router.message(Command("campaigns"))
async def cmd_campaigns(message: types.Message):
    await message.answer("⏳ Kampaniyalar yuklanmoqda...")
    report = await build_campaigns_report("today")
    await message.answer(report)


@router.message(Command("analyze"))
async def cmd_analyze(message: types.Message):
    await message.answer("🤖 AI tahlil qilinmoqda...")
    report = await build_target_report("today", include_analysis=True)
    await message.answer(report)
