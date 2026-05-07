from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from config.settings import GROUP_ID, TIMEZONE, REPORT_HOURS
from services.report_builder import build_target_report
from services.sheets_service import SheetsService
from utils.logger import logger


async def send_scheduled_report(bot: Bot):
    """Avtomatik hisobot guruhga yuboradi (faqat oddiy report)."""
    if not GROUP_ID:
        logger.warning("GROUP_ID sozlanmagan. Avtomatik hisobot yuborilmadi.")
        return

    try:
        # Guruhga tashlanadigan reportda is_admin=False, include_analysis=False bo'ladi
        report = await build_target_report("today", is_admin=False, include_analysis=False)
        await bot.send_message(chat_id=GROUP_ID, text=report)
        logger.info("✅ Avtomatik oddiy hisobot guruhga yuborildi.")
    except Exception as e:
        logger.error(f"❌ Avtomatik hisobot yuborishda xatolik: {e}")

async def sync_daily_sheets():
    """Har kuni kun oxirida ma'lumotlarni Sheetsga yozib qo'yish."""
    try:
        sheets = SheetsService()
        await sheets.sync_today_data()
        logger.info("✅ Google Sheets data saqlandi.")
    except Exception as e:
        logger.error(f"❌ Sheets sync xatolik: {e}")


def setup_scheduler(bot: Bot):
    """Scheduler ni sozlash — har kuni belgilangan vaqtlarda avtomatik hisobot."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # 09:00, 15:00, 21:00 uchun
    for hour in REPORT_HOURS:
        scheduler.add_job(
            send_scheduled_report,
            "cron",
            hour=hour,
            minute=0,
            args=[bot],
            id=f"daily_report_{hour}",
            replace_existing=True,
        )
        
    # Har kuni kechasi 23:50 da sheetsga log qilish
    scheduler.add_job(
        sync_daily_sheets,
        "cron",
        hour=23,
        minute=50,
        id="sheets_sync",
        replace_existing=True,
    )

    scheduler.start()
    hours_str = ", ".join(f"{h}:00" for h in REPORT_HOURS)
    logger.info(f"📅 Scheduler ishga tushdi ({hours_str} {TIMEZONE})")
