from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from services.report_builder import build_target_report, build_campaigns_report
from config.settings import ADMIN_ID

router = Router()

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer("👋 Assalomu alaykum! Men AI Target Assistant man.")

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("Buyruqlar:\n/today\n/analyze\n/campaigns")

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
