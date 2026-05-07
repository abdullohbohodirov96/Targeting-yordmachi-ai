from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from services.report_builder import build_target_report, build_campaigns_report
from config.settings import ADMIN_ID

router = Router()

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Uzr, sizda access mavjud emas.")
        return

    text = (
        "🤖 DUNYABUNYA AI TARGET ASSISTANT\n\n"
        "Assalomu alaykum, Abdulloh 👋\n\n"
        "Men sizning shaxsiy AI marketing va target assistantingizman.\n\n"
        "Men quyidagilarni qila olaman:\n\n"
        "📊 Meta Ads analiz\n"
        "📈 CPL / CTR / CPM monitoring\n"
        "🎯 Target tavsiyalar\n"
        "🎬 Creative va reels ssenariylar\n"
        "🧠 AI marketing analiz\n"
        "💡 Scale va optimization tavsiyalar\n"
        "⚠️ Avtomatik ogohlantirishlar\n\n"
        "Buyruqlarni ko‘rish:\n"
        "👉 /help"
    )
    await message.answer(text)

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Uzr, sizda access mavjud emas.")
        return

    text = (
        "📌 TARGET AI ASSISTANT BUYRUQLARI\n\n"
        "📊 HISOBOTLAR\n"
        "/today — bugungi hisobot\n"
        "/yesterday — kechagi hisobot\n"
        "/week — haftalik hisobot\n"
        "/month — oylik hisobot\n"
        "/campaigns — kampaniyalar\n"
        "/analyze — AI analiz\n\n"
        "🤖 AI ASSISTANT\n\n"
        "* nega CPL oshdi\n"
        "* creative yozib ber\n"
        "* reels ssenariy ber\n"
        "* target setting ber\n"
        "* audience ber\n"
        "* budgetni oshiraymi\n"
        "* qaysi kampaniya yaxshi\n"
        "* lead sifati qanday\n\n"
        "🏗 Qurilish sohasi:\n\n"
        "* gipsokarton\n"
        "* profil\n"
        "* linoleum\n"
        "* oboy\n"
        "* kafel\n"
        "* santexnika\n"
        "* bazalt\n"
        "* penoplex\n\n"
        "📞 Bog‘lanish:\n"
        "+998 (50) 999-97-33"
    )
    await message.answer(text)

@router.message(Command("today"))
async def cmd_today(message: types.Message):
    await message.answer("⏳ Yuklanmoqda...")
    is_group = message.chat.type in ["group", "supergroup"]
    
    if is_group:
        # Guruhda har doim faqat oddiy hisobot
        report = await build_target_report("today", is_admin=False, include_analysis=False)
        await message.answer(report)
    else:
        # Private chat
        if is_admin(message.from_user.id):
            report = await build_target_report("today", is_admin=True, include_analysis=True)
            await message.answer(report)
        else:
            await message.answer("Uzr, sizga bu ma’lumotlarni bera olmayman.")

@router.message(Command("yesterday"))
async def cmd_yesterday(message: types.Message):
    if is_admin(message.from_user.id):
        report = await build_target_report("yesterday", is_admin=True, include_analysis=True)
        await message.answer(report)
    else:
        await message.answer("Uzr, sizga bu ma’lumotlarni bera olmayman.")

@router.message(Command("week"))
async def cmd_week(message: types.Message):
    if is_admin(message.from_user.id):
        report = await build_target_report("week", is_admin=True, include_analysis=True)
        await message.answer(report)
    else:
        await message.answer("Uzr, sizga bu ma’lumotlarni bera olmayman.")

@router.message(Command("month"))
async def cmd_month(message: types.Message):
    if is_admin(message.from_user.id):
        report = await build_target_report("month", is_admin=True, include_analysis=True)
        await message.answer(report)
    else:
        await message.answer("Uzr, sizga bu ma’lumotlarni bera olmayman.")

@router.message(Command("campaigns"))
async def cmd_campaigns(message: types.Message):
    if is_admin(message.from_user.id):
        await message.answer("⏳ Kampaniyalar yuklanmoqda...")
        report = await build_campaigns_report("today")
        await message.answer(report)
    else:
        await message.answer("Uzr, sizga bu ma’lumotlarni bera olmayman.")

@router.message(Command("analyze"))
async def cmd_analyze(message: types.Message):
    if is_admin(message.from_user.id):
        await message.answer("🤖 AI tahlil qilinmoqda...")
        report = await build_target_report("today", is_admin=True, include_analysis=True)
        await message.answer(report)
    else:
        await message.answer("Uzr, sizga bu ma’lumotlarni bera olmayman.")
