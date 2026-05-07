from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from config.settings import GROUP_ID
from services.report_builder import build_target_report
from utils.logger import logger

async def send_scheduled_report(bot: Bot):
    if not GROUP_ID:
        logger.warning("GROUP_ID topilmadi. Avtomatik hisobot yuborilmadi.")
        return
        
    try:
        report = await build_target_report("today")
        await bot.send_message(chat_id=GROUP_ID, text=report)
        logger.info("Avtomatik hisobot guruhga yuborildi.")
    except Exception as e:
        logger.error(f"Avtomatik hisobot yuborishda xatolik: {e}")

def setup_scheduler(bot: Bot):
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    
    # Har kuni 09:00, 15:00, 21:00 da
    scheduler.add_job(send_scheduled_report, 'cron', hour=9, minute=0, args=[bot])
    scheduler.add_job(send_scheduled_report, 'cron', hour=15, minute=0, args=[bot])
    scheduler.add_job(send_scheduled_report, 'cron', hour=21, minute=0, args=[bot])
    
    scheduler.start()
    logger.info("Scheduler ishga tushirildi (09:00, 15:00, 21:00)")
