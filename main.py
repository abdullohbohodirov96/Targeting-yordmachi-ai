import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramConflictError
from config.settings import (
    BOT_TOKEN, ADMIN_ID, OPENAI_API_KEY,
    META_ACCESS_TOKEN, META_AD_ACCOUNT_ID,
)
from utils.logger import logger
from handlers import commands, messages, actions
from handlers.company_setup import router as company_setup_router
from services.scheduler import setup_scheduler


async def main():
    logger.info("BOT_TOKEN loaded: YES")
    logger.info(f"ADMIN_ID loaded: {'YES' if ADMIN_ID else 'NO'}")
    logger.info(f"OPENAI_API_KEY loaded: {'YES' if OPENAI_API_KEY else 'NO'}")
    logger.info(f"META_ACCESS_TOKEN loaded: {'YES' if META_ACCESS_TOKEN else 'NO'}")
    logger.info(f"META_AD_ACCOUNT_ID loaded: {'YES' if META_AD_ACCOUNT_ID else 'NO'}")

    if not ADMIN_ID:
        logger.warning("ADMIN_ID sozlanmagan! Private chatlarda bot hech kimga access bermaydi.")
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY sozlanmagan! AI analiz ishlamaydi.")
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT_ID:
        logger.warning("Meta Ads credentials sozlanmagan! Hisobotlar ishlamaydi.")

    bot = Bot(token=BOT_TOKEN)
    # FSM storage — kompaniya setup wizardi uchun kerak
    dp = Dispatcher(storage=MemoryStorage())

    # Router tartib muhim: company_setup birinchi (FSM state'lari uchun)
    dp.include_router(company_setup_router)
    dp.include_router(commands.router)
    dp.include_router(messages.router)
    dp.include_router(actions.router)

    setup_scheduler(bot)

    logger.info("AI Target Assistant ishga tushdi")
    logger.info("Polling started.")

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot)
    except TelegramConflictError:
        logger.error("Boshqa bot instance ishlamoqda. Duplikatni to'xtating.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi")
