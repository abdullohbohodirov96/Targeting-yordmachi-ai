import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

import config
from services.report_builder import build_report

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=config.TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Assalomu alaykum! Men target reklama hisobotlari botiman.\n\n"
        "Quyidagi komandalarni ishlatishingiz mumkin:\n"
        "/today - Bugungi hisobot\n"
        "/week - Haftalik hisobot\n"
        "/analyze - AI tahlilini olish\n"
        "/help - Yordam menyusi"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🤖 Bot komandalari:\n"
        "/start - Botni ishga tushirish\n"
        "/today - Bugungi target hisobotini olish\n"
        "/week - Haftalik target hisobotini olish\n"
        "/analyze - Oxirgi ma'lumotlar bo'yicha AI tahlili\n"
        "/help - Shu yordam menyusi"
    )

@dp.message(Command("today"))
async def cmd_today(message: Message):
    report = await build_report("today")
    await message.answer(report)
    
    # Guruhga hisobot yuborish (agar config da GROUP_ID yozilgan bo'lsa)
    if config.GROUP_ID:
        try:
            await bot.send_message(chat_id=config.GROUP_ID, text=report)
        except Exception as e:
            logging.error(f"Guruhga yuborishda xatolik yuz berdi: {e}")

@dp.message(Command("week"))
async def cmd_week(message: Message):
    report = await build_report("week")
    await message.answer(report)
    
    # Haftalikni ham guruhga tashlash mumkin
    if config.GROUP_ID:
        try:
            await bot.send_message(chat_id=config.GROUP_ID, text=report)
        except Exception as e:
            logging.error(f"Guruhga yuborishda xatolik yuz berdi: {e}")

@dp.message(Command("analyze"))
async def cmd_analyze(message: Message):
    # Analyze komandasi uchun hozircha bugungi hisobot tahlil qilinadi
    report = await build_report("today")
    await message.answer(f"Analiz natijalari:\n\n{report}")

async def main():
    if not config.TOKEN or config.TOKEN == "your_telegram_bot_token_here":
        logging.error("Bot tokeni topilmadi yoki .env da to'g'ri kiritilmagan!")
        sys.exit(1)
        
    logging.info("Bot ishga tushirildi...")
    # Pollingni boshlash
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot to'xtatildi.")
