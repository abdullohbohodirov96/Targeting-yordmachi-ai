from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from datetime import datetime, timedelta
import pytz
from config.settings import (
    GROUP_ID, ADMIN_ID, TIMEZONE, REPORT_HOURS,
    ADMIN_REPORT_TIMES,
    CPL_MULTIPLIER_ALERT, CTR_MIN_ALERT, 
    FREQUENCY_MAX_ALERT, CPM_INCREASE_ALERT,
    ALERT_COOLDOWN_HOURS
)
from services.meta_ads_service import MetaAdsService
from services.report_builder import build_target_report, build_admin_full_report
from services.ai_analyzer import AIAnalyzer
from utils.logger import logger

# Alert spam himoyasi uchun oxirgi alert vaqtini saqlash
last_alert_time = None


async def send_admin_full_report(bot: Bot, report_time: str):
    """
    Admin uchun to'liq target hisobot + AI tahlil + takliflar.
    Faqat ADMIN_ID ga private yuboriladi.
    """
    if not ADMIN_ID:
        return

    try:
        report = await build_admin_full_report(report_time)
        await bot.send_message(chat_id=ADMIN_ID, text=report)
        logger.info(f"✅ Admin full report yuborildi ({report_time}).")
    except Exception as e:
        logger.error(f"❌ Admin full report yuborishda xato: {e}")
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=f"❌ {report_time} hisobot yuborishda xatolik:\n{e}"
            )
        except Exception:
            pass


async def monitor_ad_performance(bot: Bot):
    """
    Har 1 soatda Meta Ads ma'lumotlarini tekshiradi.
    Natija yomonlashsa ADMIN_ID ga alert yuboradi.
    """
    global last_alert_time
    
    if not ADMIN_ID:
        return

    try:
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        
        if last_alert_time and (now - last_alert_time) < timedelta(hours=ALERT_COOLDOWN_HOURS):
            return

        meta = MetaAdsService()
        data = await meta.get_account_insights("today")
        yesterday_data = await meta.get_account_insights("yesterday")

        if not data or data.get('spend', 0) == 0:
            return

        issues = []
        
        if yesterday_data and yesterday_data.get('cpl', 0) > 0:
            if data['cpl'] >= yesterday_data['cpl'] * CPL_MULTIPLIER_ALERT:
                issues.append(f"CPL qimmatlashgan: ${data['cpl']} (Kechagi: ${yesterday_data['cpl']})")

        if data['ctr'] < CTR_MIN_ALERT:
            issues.append(f"CTR juda past: {data['ctr']}% (Min: {CTR_MIN_ALERT}%)")

        if data['frequency'] > FREQUENCY_MAX_ALERT:
            issues.append(f"Frequency yuqori: {data['frequency']} (Max: {FREQUENCY_MAX_ALERT})")

        if data['spend'] > 10 and data['leads'] == 0:
            issues.append(f"Spend bor (${data['spend']}), lekin lead yo'q (0 lead)")

        if issues:
            ai = AIAnalyzer()
            ai_recommendations = await ai.generate_monitoring_alert(data, yesterday_data, issues)
            
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




async def send_scheduled_report(bot: Bot):
    """Guruhga avtomatik oddiy KPI report."""
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

    # 1. Guruhga oddiy KPI hisobotlar (09:00, 15:00, 21:00)
    for hour in REPORT_HOURS:
        scheduler.add_job(
            send_scheduled_report, "cron",
            hour=hour, minute=0, args=[bot],
            id=f"group_report_{hour}", replace_existing=True
        )

    # 2. Admin uchun to'liq report + AI tahlil (09:00, 13:00, 18:00)
    for time_cfg in ADMIN_REPORT_TIMES:
        h = time_cfg["hour"]
        m = time_cfg["minute"]
        time_label = f"{h:02d}:{m:02d}"
        scheduler.add_job(
            send_admin_full_report, "cron",
            hour=h, minute=m, args=[bot, time_label],
            id=f"admin_report_{h}_{m}", replace_existing=True
        )

    # 3. Har 1 soatda performance monitoring
    scheduler.add_job(
        monitor_ad_performance, "interval",
        hours=1, args=[bot],
        id="hourly_monitoring", replace_existing=True
    )

    scheduler.start()

    # Startup log
    admin_times_str = ", ".join(
        f"{t['hour']:02d}:{t['minute']:02d}" for t in ADMIN_REPORT_TIMES
    )
    group_times_str = ", ".join(f"{h}:00" for h in REPORT_HOURS)
    logger.info(f"📅 Scheduler ishga tushdi ({TIMEZONE})")
    logger.info(f"📊 Guruh report: {group_times_str}")
    logger.info(f"🔐 Admin report scheduler started: {admin_times_str}")
    logger.info(f"🔍 Hourly monitoring: har 1 soatda")
