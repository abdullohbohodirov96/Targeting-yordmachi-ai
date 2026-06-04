"""
Avtomatik hisobotlar va monitoring.
Kritik CPL (2x) holatlarda kampaniyalarni avtomatik pauza qiladi.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from datetime import datetime, timedelta
import pytz
from config.settings import (
    GROUP_ID, ADMIN_ID, TIMEZONE, REPORT_HOURS,
    ADMIN_REPORT_TIMES,
    CPL_MULTIPLIER_ALERT, CTR_MIN_ALERT,
    FREQUENCY_MAX_ALERT, CPM_INCREASE_ALERT,
    ALERT_COOLDOWN_HOURS,
)
from services.meta_ads_service import MetaAdsService
from services.meta_actions_service import MetaActionsService
from services.report_builder import build_target_report, build_admin_full_report
from services.ai_analyzer import AIAnalyzer
from utils.logger import logger

# Alert spam himoyasi
last_alert_time = None

# Auto-pause qilingan kampaniyalar (spam oldini olish)
_auto_paused_today: set = set()


async def send_admin_full_report(bot: Bot, report_time: str):
    """Admin uchun to'liq hisobot + AI tahlil."""
    if not ADMIN_ID:
        return
    try:
        report = await build_admin_full_report(report_time)
        await bot.send_message(chat_id=ADMIN_ID, text=report)
        logger.info(f"Admin full report yuborildi ({report_time}).")
    except Exception as e:
        logger.error(f"Admin full report xato: {e}")
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=f"❌ {report_time} hisobot yuborishda xatolik:\n{e}",
            )
        except Exception:
            pass


async def monitor_ad_performance(bot: Bot):
    """
    Har 1 soatda Meta Ads natijalarini tekshiradi.
    Kritik holatlarda: ADMIN ga xabar + eng yomon kampaniyani auto-pause.
    """
    global last_alert_time

    if not ADMIN_ID:
        return

    try:
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)

        # Cooldown tekshirish
        if last_alert_time and (now - last_alert_time) < timedelta(hours=ALERT_COOLDOWN_HOURS):
            return

        meta = MetaAdsService()
        data = await meta.get_account_insights("today")
        yesterday_data = await meta.get_account_insights("yesterday")
        campaigns = await meta.get_campaign_insights("today")

        if not data or data.get("spend", 0) == 0:
            return

        issues = []
        is_critical = False

        # 1. CPL kritik tekshiruvi
        yesterday_cpl = yesterday_data.get("cpl", 0) if yesterday_data else 0
        today_cpl = data.get("cpl", 0)

        if yesterday_cpl > 0 and today_cpl >= yesterday_cpl * CPL_MULTIPLIER_ALERT:
            issues.append(
                f"🚨 KRITIK CPL: ${today_cpl:.2f} (kechagi ${yesterday_cpl:.2f} dan {CPL_MULTIPLIER_ALERT}x oshdi)"
            )
            is_critical = True

        # 2. CTR past tekshiruv
        if data["ctr"] < CTR_MIN_ALERT:
            issues.append(f"CTR juda past: {data['ctr']}% (min: {CTR_MIN_ALERT}%)")

        # 3. Frequency yuqori
        if data["frequency"] > FREQUENCY_MAX_ALERT:
            issues.append(f"Frequency yuqori: {data['frequency']} (max: {FREQUENCY_MAX_ALERT})")

        # 4. Spend bor, lead yo'q
        if data["spend"] > 10 and data["leads"] == 0:
            issues.append(f"Spend ${data['spend']:.2f} — lekin 0 lead")

        if not issues:
            return

        # ── AUTO-PAUSE (faqat kritik CPL holatida) ────────────────────────
        auto_paused = []
        if is_critical and campaigns:
            actions = MetaActionsService()
            # Eng yomon kampaniyalarni topish (CPL > threshold)
            worst = [
                c for c in campaigns
                if c.get("cpl", 0) > 0
                and yesterday_cpl > 0
                and c.get("cpl", 0) >= yesterday_cpl * CPL_MULTIPLIER_ALERT
                and c.get("campaign_id") not in _auto_paused_today
            ]
            # Max 2 ta kampaniyani auto-pause qilamiz
            for camp in worst[:2]:
                camp_id = camp.get("campaign_id")
                camp_name = camp.get("campaign_name", "?")
                if not camp_id:
                    continue
                result = await actions.update_status(camp_id, "PAUSED", admin_id=0)
                if result.get("success"):
                    _auto_paused_today.add(camp_id)
                    auto_paused.append(
                        f"• {camp_name} (CPL: ${camp.get('cpl', '?'):.2f}) — ✅ PAUSED"
                    )
                    logger.warning(f"AUTO-PAUSE: {camp_name} (ID: {camp_id})")
                else:
                    auto_paused.append(
                        f"• {camp_name} — ❌ pause xato: {result.get('message', '?')}"
                    )

        # ── AI TAHLIL ─────────────────────────────────────────────────────
        ai = AIAnalyzer()
        ai_text = await ai.generate_monitoring_alert(data, yesterday_data or {}, issues)

        # ── XABAR TUZISH ──────────────────────────────────────────────────
        impressions_fmt = f"{data['impressions']:,}".replace(",", " ")
        reach_fmt = f"{data['reach']:,}".replace(",", " ")

        alert_msg = (
            f"{'🚨' if is_critical else '⚠️'} TARGET {'KRITIK OGOHLANTIRISH' if is_critical else 'OGOHLANTIRISH'}\n\n"
            f"📅 Vaqt: {now.strftime('%H:%M')}\n"
            f"💰 Xarajat: ${data['spend']:.2f}\n"
            f"📩 Leadlar: {data['leads']}\n"
            f"🎯 CPL: ${data['cpl']:.2f} | Kechagi: ${yesterday_cpl:.2f}\n"
            f"📈 CTR: {data['ctr']}%\n"
            f"📉 CPM: ${data['cpm']:.2f}\n"
            f"📍 Reach: {reach_fmt}\n"
            f"🔄 Frequency: {data['frequency']}\n"
        )

        if auto_paused:
            alert_msg += f"\n🤖 AUTO-PAUSE QILINDI:\n" + "\n".join(auto_paused) + "\n"

        alert_msg += f"\n{ai_text}"

        await bot.send_message(chat_id=ADMIN_ID, text=alert_msg)
        last_alert_time = now
        logger.info(f"Target alert yuborildi. Auto-paused: {len(auto_paused)} ta.")

        # Tunda _auto_paused_today ni tozalash
        tz_now = datetime.now(tz)
        if tz_now.hour == 0:
            _auto_paused_today.clear()

    except Exception as e:
        logger.error(f"Monitoring xato: {e}")


async def send_scheduled_report(bot: Bot):
    """Guruhga avtomatik KPI hisobot."""
    if not GROUP_ID:
        return
    try:
        tz = pytz.timezone(TIMEZONE)
        current_hour = datetime.now(tz).hour
        period = "yesterday" if current_hour < 12 else "today"

        meta = MetaAdsService()
        data = await meta.get_account_insights(period)
        if data is None:
            logger.warning(f"Real data olinmadi ({period}). Guruhga yuborilmadi.")
            return

        report = await build_target_report(period, is_admin=False, include_analysis=False)
        await bot.send_message(chat_id=GROUP_ID, text=report)
        logger.info(f"Avtomatik hisobot guruhga yuborildi ({period}).")
    except Exception as e:
        logger.error(f"Avtomatik hisobot xato: {e}")


def setup_scheduler(bot: Bot):
    """Scheduler'ni sozlash va ishga tushirish."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # Guruhga KPI hisobotlar
    for hour in REPORT_HOURS:
        scheduler.add_job(
            send_scheduled_report, "cron",
            hour=hour, minute=0, args=[bot],
            id=f"group_report_{hour}", replace_existing=True,
        )

    # Admin uchun to'liq hisobot + AI tahlil
    for time_cfg in ADMIN_REPORT_TIMES:
        h, m = time_cfg["hour"], time_cfg["minute"]
        scheduler.add_job(
            send_admin_full_report, "cron",
            hour=h, minute=m, args=[bot, f"{h:02d}:{m:02d}"],
            id=f"admin_report_{h}_{m}", replace_existing=True,
        )

    # Har soatda performance monitoring (+ auto-pause)
    scheduler.add_job(
        monitor_ad_performance, "interval",
        hours=1, args=[bot],
        id="hourly_monitoring", replace_existing=True,
    )

    scheduler.start()

    admin_times_str = ", ".join(f"{t['hour']:02d}:{t['minute']:02d}" for t in ADMIN_REPORT_TIMES)
    group_times_str = ", ".join(f"{h}:00" for h in REPORT_HOURS)
    logger.info(f"Scheduler ishga tushdi ({TIMEZONE})")
    logger.info(f"Guruh hisobot: {group_times_str}")
    logger.info(f"Admin hisobot: {admin_times_str}")
    logger.info(f"Monitoring: har 1 soatda (kritik CPL → auto-pause)")
