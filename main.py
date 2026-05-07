import asyncio
from aiogram import Bot, Dispatcher
from config.settings import BOT_TOKEN
from utils.logger import logger
from handlers import commands, messages
from services.scheduler import setup_scheduler


async def main():
    logger.info("BOT_TOKEN loaded: YES")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Routerlarni ulash (commands birinchi, messages oxirida — catchall)
    dp.include_router(commands.router)
    dp.include_router(messages.router)

    # Scheduler
    setup_scheduler(bot)

    # Start
    logger.info("Bot started successfully")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi")
