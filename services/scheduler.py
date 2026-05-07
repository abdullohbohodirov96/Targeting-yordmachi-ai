from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from config.settings import GROUP_ID, TIMEZONE, REPORT_HOURS
from services.report_builder import build_target_report
from utils.logger import logger


async def send_scheduled_report(bot: Bot):
    """Avtomatik hisobot guruhga yuboradi."""
    if not GROUP_ID:
        logger.warning("GROUP_ID sozlanmagan. Avtomatik hisobot yuborilmadi.")
        return

    try:
        # Tahlilsiz (AI siz) sof hisobot tashlaymiz va faqat "yesterday"
        report = await build_target_report("yesterday", include_analysis=False)
        await bot.send_message(chat_id=GROUP_ID, text=report)
        logger.info("✅ Avtomatik hisobot guruhga yuborildi.")
    except Exception as e:
        logger.error(f"❌ Avtomatik hisobot yuborishda xatolik: {e}")


def setup_scheduler(bot: Bot):
    """Scheduler ni sozlash — har kuni belgilangan vaqtlarda avtomatik hisobot."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

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
