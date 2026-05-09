from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from datetime import datetime, timedelta
import pytz
from config.settings import (
    GROUP_ID, ADMIN_ID, TIMEZONE, REPORT_HOURS,
    CPL_MULTIPLIER_ALERT, CTR_MIN_ALERT, 
    FREQUENCY_MAX_ALERT, CPM_INCREASE_ALERT,
    ALERT_COOLDOWN_HOURS
)
from services.meta_ads_service import MetaAdsService
from services.report_builder import build_target_report
from services.ai_analyzer import AIAnalyzer
from utils.logger import logger

# Alert spam himoyasi uchun oxirgi alert vaqtini saqlash
last_alert_time = None

async def monitor_ad_performance(bot: Bot):
    """
    Har 1 soatda Meta Ads ma'lumotlarini tekshiradi.
    Natija yomonlashsa ADMIN_ID ga alert yuboradi.
    """
    global last_alert_time
    
    if not ADMIN_ID:
        return

    try:
        # Spam protection check
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        
        if last_alert_time and (now - last_alert_time) < timedelta(hours=ALERT_COOLDOWN_HOURS):
            # Cooldown tugamagan bo'lsa tekshirib o'tirmaymiz
            return

        meta = MetaAdsService()
        data = await meta.get_account_insights("today")
        yesterday_data = await meta.get_account_insights("yesterday")

        if not data or data.get('spend', 0) == 0:
            # Bugun xarajat yo'q bo'lsa yoki API ishlamasa alert bermaymiz
            return

        issues = []
        
        # 1. CPL check (kechagiga nisbatan 2 baravar oshgan bo'lsa)
        if yesterday_data and yesterday_data.get('cpl', 0) > 0:
            if data['cpl'] >= yesterday_data['cpl'] * CPL_MULTIPLIER_ALERT:
                issues.append(f"CPL qimmatlashgan: ${data['cpl']} (Kechagi: ${yesterday_data['cpl']})")

        # 2. CTR check (threshold dan past bo'lsa)
        if data['ctr'] < CTR_MIN_ALERT:
            issues.append(f"CTR juda past: {data['ctr']}% (Min: {CTR_MIN_ALERT}%)")

        # 3. Frequency check (threshold dan oshsa)
        if data['frequency'] > FREQUENCY_MAX_ALERT:
            issues.append(f"Frequency yuqori: {data['frequency']} (Max: {FREQUENCY_MAX_ALERT})")

        # 4. Spend bor, lekin lead yo'q
        if data['spend'] > 10 and data['leads'] == 0:
            issues.append(f"Spend bor (${data['spend']}), lekin lead yo'q (0 lead)")

        # Agar muammolar bo'lsa - AI dan tahlil va tavsiya olamiz
        if issues:
            ai = AIAnalyzer()
            ai_recommendations = await ai.generate_monitoring_alert(data, yesterday_data, issues)
            
            # Raqamlarni formatlash
            impressions_fmt = f"{data['impressions']:,}".replace(",", " ")
            reach_fmt = f"{data['reach']:,}".replace(",", " ")

            alert_msg = (
                f"⚠️ TARGET OGOHLANTIRISH\n\n"
                f"📅 Davr: Bugun\n"
                f"💰 Xarajat: ${data['spend']:.2f}\n"
                f"📩 Leadlar: {data['leads']}\n"
                f"🎯 CPL: ${data['cpl']:.2f}\n"
                f"📈 CTR: {data['ctr']}%\n"
                f"📉 CPM: ${data['cpm']:.2f}\n"
                f"📍 Reach: {reach_fmt}\n"
                f"🔄 Frequency: {data['frequency']}\n\n"
                f"{ai_recommendations}"
            )
            
            await bot.send_message(chat_id=ADMIN_ID, text=alert_msg)
            last_alert_time = now
            logger.info("Admin'ga target alert yuborildi.")

    except Exception as e:
        logger.error(f"Monitoring xatoligi: {e}")


async def send_daily_summary(bot: Bot):
    """
    Har kuni 21:00 da admin uchun kunlik yakuniy xulosa yuboradi.
    Agar natijalar yaxshi bo'lsa ham xabar beradi.
    """
    if not ADMIN_ID:
        return

    try:
        meta = MetaAdsService()
        data = await meta.get_account_insights("today")
        
        if not data or data.get('spend', 0) == 0:
            return

        # Agar muammolar yo'q bo'lsa (yaxshi natija)
        # Soddaroq summary
        if data['ctr'] >= CTR_MIN_ALERT and data['leads'] > 0:
            summary = (
                f"✅ TARGET HOLATI YAXSHI\n\n"
                f"Bugungi reklama natijalari normal.\n"
                f"CPL nazoratda (${data['cpl']:.2f}), CTR yomon emas ({data['ctr']}%).\n\n"
                f"💰 Spend: ${data['spend']:.2f}\n"
                f"📩 Leads: {data['leads']}\n"
                f"🎯 CPL: ${data['cpl']:.2f}"
            )
            await bot.send_message(chat_id=ADMIN_ID, text=summary)
            logger.info("Admin'ga daily success summary yuborildi.")
            
    except Exception as e:
        logger.error(f"Daily summary xatoligi: {e}")


async def send_scheduled_report(bot: Bot):
    """Eski avtomatik hisobot logikasi (guruhga)."""
    if not GROUP_ID: return

    try:
        tz = pytz.timezone(TIMEZONE)
        current_hour = datetime.now(tz).hour
        period = "yesterday" if current_hour < 12 else "today"

        meta = MetaAdsService()
        data = await meta.get_account_insights(period)

        if data is None:
            logger.warning(f"⚠️ Real data olinmadi ({period}). Guruhga yuborilmadi.")
            return

        report = await build_target_report(period, is_admin=False, include_analysis=False)
        await bot.send_message(chat_id=GROUP_ID, text=report)
        logger.info(f"✅ Avtomatik oddiy hisobot guruhga yuborildi ({period}).")

    except Exception as e:
        logger.error(f"❌ Avtomatik hisobot xatoligi: {e}")


def setup_scheduler(bot: Bot):
    """Scheduler ni sozlash."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # 1. Guruhga hisobotlar (09:00, 15:00, 21:00)
    for hour in REPORT_HOURS:
        scheduler.add_job(
            send_scheduled_report, "cron", hour=hour, minute=0, args=[bot], id=f"group_report_{hour}"
        )

    # 2. Har 1 soatda performance monitoring (admin uchun)
    scheduler.add_job(
        monitor_ad_performance, "interval", hours=1, args=[bot], id="hourly_monitoring"
    )

    # 3. Kunlik yakuniy summary (21:00)
    scheduler.add_job(
        send_daily_summary, "cron", hour=21, minute=5, args=[bot], id="daily_admin_summary"
    )

    scheduler.start()
    logger.info(f"📅 Monitoring Scheduler ishga tushdi ({TIMEZONE})")
