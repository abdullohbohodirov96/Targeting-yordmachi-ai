import asyncio
from aiogram import Bot, Dispatcher
from config.settings import BOT_TOKEN, META_ACCESS_TOKEN, META_AD_ACCOUNT_ID
from utils.logger import logger
from handlers import commands, messages
from services.scheduler import setup_scheduler


async def main():
    logger.info("BOT_TOKEN loaded: YES")
    logger.info(f"META_ACCESS_TOKEN loaded: {'YES' if META_ACCESS_TOKEN else 'NO'}")
    logger.info(f"META_AD_ACCOUNT_ID loaded: {'YES' if META_AD_ACCOUNT_ID else 'NO'}")

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
