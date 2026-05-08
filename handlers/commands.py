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
        "Bu bot Dunyabunya uchun yaratilgan AI marketing va target assistant hisoblanadi.\n\n"
        "Bot imkoniyatlari:\n"
        "📊 Meta Ads hisobotlari (faqat real data)\n"
        "📈 CPL / CTR / CPM monitoring\n"
        "🎯 Target analiz va tavsiyalar\n"
        "🎬 Creative va reels ssenariylar\n"
        "🧠 AI marketing assistant\n"
        "📝 Content plan va ad copy\n"
        "💡 Marketing strategiya\n"
        "🎯 Target setting va audience\n"
        "📞 DM script va sales script\n\n"
        "Buyruqlarni ko'rish:\n"
        "👉 /help\n\n"
        "⚠️ *Eslatma:*\n"
        "Ba'zi professional funksiyalar faqat admin uchun mavjud.\n"
        "Bot faqat real Meta Ads data asosida ishlaydi."
    )
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    if is_admin(message.from_user.id):
        text = (
            "📌 *BOT YORDAMI — ADMIN*\n\n"
            "📊 *HISOBOTLAR*\n"
            "/today — bugungi hisobot\n"
            "/yesterday — kechagi hisobot\n"
            "/week — haftalik hisobot\n"
            "/month — oylik hisobot\n"
            "/campaigns — kampaniyalar\n"
            "/analyze — AI analiz\n\n"
            "🤖 *AI ASSISTANT MISOLLARI*\n\n"
            "📈 *Statistika savollari:*\n"
            "• nega CPL oshdi\n"
            "• budgetni oshiraymi\n"
            "• qaysi kampaniya yaxshi\n"
            "• qaysi kampaniya yomon\n"
            "• lead sifati qanday\n"
            "• CPM nega oshdi\n"
            "• CTR nega tushdi\n"
            "• qaysi reklamani o'chirish kerak\n\n"
            "🎬 *Creative vazifalar:*\n"
            "• creative yozib ber\n"
            "• reels ssenariy ber\n"
            "• hook yoz\n"
            "• caption yoz\n"
            "• ad copy yoz\n"
            "• DM script yoz\n"
            "• sales script yoz\n"
            "• offer yaratib ber\n"
            "• content plan tuz\n\n"
            "🎯 *Strategiya:*\n"
            "• target setting ber\n"
            "• audience ber\n"
            "• budget tavsiya ber\n"
            "• marketing strategiya ber\n"
            "• campaign analysis qil\n\n"
            "📞 *Bog'lanish:*\n"
            "+998 (50) 999-97-33"
        )
    else:
        text = (
            "📌 *BOT YORDAMI*\n\n"
            "🤖 *AI ASSISTANT MISOLLARI*\n\n"
            "• creative yozib ber\n"
            "• reels ssenariy ber\n"
            "• hook yoz\n"
            "• caption yoz\n"
            "• target setting ber\n"
            "• audience ber\n"
            "• content plan tuz\n"
            "• marketing maslahat ber\n\n"
            "⚠️ Statistika va kampaniya ma'lumotlari faqat admin uchun.\n\n"
            "📞 *Bog'lanish:*\n"
            "+998 (50) 999-97-33"
        )
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("today"))
async def cmd_today(message: types.Message):
    await message.answer("⏳ Yuklanmoqda...")
    is_group = message.chat.type in ["group", "supergroup"]

    if is_group:
        # Guruhda faqat oddiy KPI report
        report = await build_target_report("today", is_admin=False, include_analysis=False)
        await message.answer(report)
    else:
        # Private chat
        if is_admin(message.from_user.id):
            report = await build_target_report("today", is_admin=True, include_analysis=True)
            await message.answer(report)
        else:
            await message.answer("Uzr, sizga bu ma'lumotlarni bera olmayman.")

@router.message(Command("yesterday"))
async def cmd_yesterday(message: types.Message):
    is_group = message.chat.type in ["group", "supergroup"]

    if is_group:
        # Guruhda faqat oddiy KPI report
        await message.answer("⏳ Yuklanmoqda...")
        report = await build_target_report("yesterday", is_admin=False, include_analysis=False)
        await message.answer(report)
    else:
        if is_admin(message.from_user.id):
            await message.answer("⏳ Yuklanmoqda...")
            report = await build_target_report("yesterday", is_admin=True, include_analysis=True)
            await message.answer(report)
        else:
            await message.answer("Uzr, sizga bu ma'lumotlarni bera olmayman.")

@router.message(Command("week"))
async def cmd_week(message: types.Message):
    is_group = message.chat.type in ["group", "supergroup"]

    if is_group:
        # Guruhda faqat oddiy KPI report
        await message.answer("⏳ Yuklanmoqda...")
        report = await build_target_report("week", is_admin=False, include_analysis=False)
        await message.answer(report)
    else:
        if is_admin(message.from_user.id):
            await message.answer("⏳ Yuklanmoqda...")
            report = await build_target_report("week", is_admin=True, include_analysis=True)
            await message.answer(report)
        else:
            await message.answer("Uzr, sizga bu ma'lumotlarni bera olmayman.")

@router.message(Command("month"))
async def cmd_month(message: types.Message):
    is_group = message.chat.type in ["group", "supergroup"]

    if is_group:
        # Guruhda faqat oddiy KPI report
        await message.answer("⏳ Yuklanmoqda...")
        report = await build_target_report("month", is_admin=False, include_analysis=False)
        await message.answer(report)
    else:
        if is_admin(message.from_user.id):
            await message.answer("⏳ Yuklanmoqda...")
            report = await build_target_report("month", is_admin=True, include_analysis=True)
            await message.answer(report)
        else:
            await message.answer("Uzr, sizga bu ma'lumotlarni bera olmayman.")

@router.message(Command("campaigns"))
async def cmd_campaigns(message: types.Message):
    is_group = message.chat.type in ["group", "supergroup"]

    if is_group:
        await message.answer("⚠️ Kampaniya ma'lumotlari faqat admin private chatda ko'rsatiladi.")
        return

    if is_admin(message.from_user.id):
        await message.answer("⏳ Kampaniyalar yuklanmoqda...")
        report = await build_campaigns_report("today")
        await message.answer(report)
    else:
        await message.answer("Uzr, sizga bu ma'lumotlarni bera olmayman.")

@router.message(Command("analyze"))
async def cmd_analyze(message: types.Message):
    is_group = message.chat.type in ["group", "supergroup"]

    if is_group:
        await message.answer("⚠️ AI analiz faqat admin private chatda ko'rsatiladi.")
        return

    if is_admin(message.from_user.id):
        await message.answer("🤖 AI tahlil qilinmoqda...")
        report = await build_target_report("today", is_admin=True, include_analysis=True)
        await message.answer(report)
    else:
        await message.answer("Uzr, sizga bu ma'lumotlarni bera olmayman.")
