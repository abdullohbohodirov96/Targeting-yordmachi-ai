from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from config.settings import GROUP_ID, TIMEZONE, REPORT_HOURS
from services.report_builder import build_target_report
from utils.logger import logger


async def send_scheduled_report(bot: Bot):
    """Avtomatik hisobot guruhga yuboradi (faqat oddiy report)."""
    if not GROUP_ID:
        logger.warning("GROUP_ID sozlanmagan. Avtomatik hisobot yuborilmadi.")
        return

    try:
        from datetime import datetime
        import pytz
        
        # Hozirgi soatni aniqlaymiz
        tz = pytz.timezone(TIMEZONE)
        current_hour = datetime.now(tz).hour
        
        # Agar ertalab 9:00 bo'lsa, kechagi kun hisobotini tashlaymiz
        period = "yesterday" if current_hour < 12 else "today"
        
        # Guruhga tashlanadigan reportda is_admin=False, include_analysis=False bo'ladi
        report = await build_target_report(period, is_admin=False, include_analysis=False)
        await bot.send_message(chat_id=GROUP_ID, text=report)
        logger.info(f"✅ Avtomatik oddiy hisobot guruhga yuborildi ({period}).")
    except Exception as e:
        logger.error(f"❌ Avtomatik hisobot yuborishda xatolik: {e}")


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

    scheduler.start()
    hours_str = ", ".join(f"{h}:00" for h in REPORT_HOURS)
    logger.info(f"📅 Scheduler ishga tushdi ({hours_str} {TIMEZONE})")
