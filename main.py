import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramConflictError
from config.settings import (
    BOT_TOKEN, ADMIN_ID, OPENAI_API_KEY,
    META_ACCESS_TOKEN, META_AD_ACCOUNT_ID
)
from utils.logger import logger
from handlers import commands, messages, actions
from services.scheduler import setup_scheduler


async def main():
    # Startup diagnostika — keylarni to'liq print qilmaymiz
    logger.info(f"BOT_TOKEN loaded: YES")
    logger.info(f"ADMIN_ID loaded: {'YES' if ADMIN_ID else 'NO'}")
    logger.info(f"OPENAI_API_KEY loaded: {'YES' if OPENAI_API_KEY else 'NO'}")
    logger.info(f"META_ACCESS_TOKEN loaded: {'YES' if META_ACCESS_TOKEN else 'NO'}")
    logger.info(f"META_AD_ACCOUNT_ID loaded: {'YES' if META_AD_ACCOUNT_ID else 'NO'}")

    if not ADMIN_ID:
        logger.warning("⚠️ ADMIN_ID sozlanmagan! Private chatlarda bot hech kimga access bermaydi.")

    if not OPENAI_API_KEY:
        logger.warning("⚠️ OPENAI_API_KEY sozlanmagan! AI analiz va savol-javob ishlamaydi.")

    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT_ID:
        logger.warning("⚠️ Meta Ads credentials sozlanmagan! Hisobotlar ishlamaydi.")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(commands.router)
    dp.include_router(messages.router)
    dp.include_router(actions.router)

    setup_scheduler(bot)

    logger.info("✅ AI Target Assistant Started Successfully")
    logger.info("🚀 Polling started. Make sure only one instance is running.")
    logger.info("⚠️ RENDER NOTE: Ensure you only have 1 active worker/process to avoid polling conflicts.")
    
    # Eski webhookni o'chirish (Polling muammosini oldini olish uchun)
    await bot.delete_webhook(drop_pending_updates=True)
    
    try:
        await dp.start_polling(bot)
    except TelegramConflictError:
        logger.error("❌ Another bot instance is running. Stop duplicate Render/Railway/local service.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi")
