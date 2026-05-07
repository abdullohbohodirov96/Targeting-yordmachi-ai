import asyncio
from aiogram import Bot, Dispatcher
from config.settings import BOT_TOKEN, ADMIN_ID
from utils.logger import logger
from handlers import commands, messages
from services.scheduler import setup_scheduler


async def main():
    logger.info("BOT_TOKEN loaded: YES")

    if not ADMIN_ID:
        logger.warning("⚠️ ADMIN_ID sozlanmagan! Private chatlarda bot hech kimga access bermaydi.")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(commands.router)
    dp.include_router(messages.router)

    setup_scheduler(bot)

    logger.info("AI Target Assistant Started Successfully")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi")
