from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from config.settings import GROUP_ID, ADMIN_ID, TIMEZONE, REPORT_HOURS
from services.meta_ads_service import MetaAdsService
from services.report_builder import build_target_report
from utils.logger import logger


async def send_scheduled_report(bot: Bot):
    """
    Avtomatik hisobot:
    - Real data bo'lsa → guruhga oddiy report yuboradi
    - Real data bo'lmasa → guruhga HECH NARSA yubormasin
    - Real data bo'lmasa → admin private chatga warning yuboradi
    """
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

        # Avval real data borligini tekshiramiz
        meta = MetaAdsService()
        data = await meta.get_account_insights(period)

        if data is None:
            # Real data olinmadi — guruhga HECH NARSA yubormaymiz
            logger.warning(f"⚠️ Avtomatik hisobot: Real data olinmadi ({period}). Guruhga yuborilmadi.")

            # Faqat admin private chatga warning yuboramiz
            if ADMIN_ID:
                warning_msg = (
                    f"⚠️ Avtomatik hisobot ogohlantirishi\n\n"
                    f"📅 Vaqt: {datetime.now(tz).strftime('%d.%m.%Y %H:%M')}\n"
                    f"📊 Davr: {period}\n\n"
                    f"❌ Real Meta Ads data olinmadi.\n"
                    f"Guruhga hisobot yuborilmadi.\n\n"
                    f"Tekshiring:\n"
                    f"• META_ACCESS_TOKEN\n"
                    f"• META_AD_ACCOUNT_ID\n"
                    f"• Meta API holati"
                )
                try:
                    await bot.send_message(chat_id=ADMIN_ID, text=warning_msg)
                    logger.info("Admin'ga warning xabari yuborildi.")
                except Exception as admin_err:
                    logger.error(f"Admin'ga warning yuborishda xato: {admin_err}")
            return

        # Real data bor — guruhga oddiy report yuboramiz
        report = await build_target_report(period, is_admin=False, include_analysis=False)
        await bot.send_message(chat_id=GROUP_ID, text=report)
        logger.info(f"✅ Avtomatik oddiy hisobot guruhga yuborildi ({period}).")

    except Exception as e:
        logger.error(f"❌ Avtomatik hisobot yuborishda xatolik: {e}")

        # Xatolik bo'lsa ham admin'ga xabar beramiz
        if ADMIN_ID:
            try:
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"❌ Avtomatik hisobot xatoligi:\n{e}"
                )
            except Exception:
                pass


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
