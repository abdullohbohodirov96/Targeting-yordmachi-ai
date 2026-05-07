from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from services.report_builder import build_target_report

router = Router()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Assalomu alaykum! Men professional AI Target Analytics botiman.\n\n"
        "Quyidagi komandalarni ishlating:\n"
        "/today - Bugungi hisobot\n"
        "/yesterday - Kechagi hisobot\n"
        "/week - Haftalik hisobot\n"
        "/month - Oylik hisobot\n"
        "/campaigns - Kampaniyalar holati\n"
        "/analyze - AI analiz olish\n"
        "/help - Yordam menyusi\n\n"
        "Shuningdek, menga xohlagan savolingizni yozishingiz mumkin. "
        "Masalan: 'Nega CPL oshdi?'"
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "🛠 Yordam Menyusi:\n"
        "/today - Bugungi hisobot\n"
        "/yesterday - Kechagi hisobot\n"
        "/week - Haftalik hisobot\n"
        "/month - Oylik hisobot\n"
        "/campaigns - Eng yaxshi va eng yomon kampaniyalar\n"
        "/analyze - Umumiy AI analizi\n"
        "Matnli savollar berishingiz ham mumkin (Masalan: 'Qaysi reklamani o'chirish kerak?')"
    )

@router.message(Command("today"))
async def cmd_today(message: types.Message):
    await message.answer(await build_target_report("today"))

@router.message(Command("yesterday"))
async def cmd_yesterday(message: types.Message):
    await message.answer(await build_target_report("yesterday"))

@router.message(Command("week"))
async def cmd_week(message: types.Message):
    await message.answer(await build_target_report("week"))

@router.message(Command("month"))
async def cmd_month(message: types.Message):
    await message.answer(await build_target_report("month"))

@router.message(Command("campaigns"))
async def cmd_campaigns(message: types.Message):
    report = await build_target_report("today")
    # Biz hozircha qisqa qilib ajratib bermadik, ammo report_builder dan faqat shu qismini ham ajratib olish mumkin.
    # Test uchun to'liq reportni jo'natamiz yoki shu yerdan kesib olishimiz mumkin
    await message.answer("Kampaniyalar hisoboti:\n" + report.split("🔥")[1] if "🔥" in report else report)

@router.message(Command("analyze"))
async def cmd_analyze(message: types.Message):
    report = await build_target_report("today")
    await message.answer("Tahlil natijalari:\n\n" + report)
