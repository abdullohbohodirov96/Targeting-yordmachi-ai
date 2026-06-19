from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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
from services.meta_actions_service import MetaActionsService
from services.report_builder import build_target_report, build_admin_full_report, build_sms_campaigns_report
from services.cpl_limits import get_limit, set_limit, get_new_campaigns, mark_campaign_seen, get_all_limits
from services.ai_analyzer import AIAnalyzer
from utils.logger import logger

# Alert spam himoyasi uchun oxirgi alert vaqtini saqlash
last_alert_time = None


async def send_admin_full_report(bot: Bot, report_time: str):
    """Admin uchun to'liq target hisobot + AI tahlil."""
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


async def check_new_campaigns_and_ask_limits(bot: Bot):
    """
    Yangi yoqilgan kampaniyalarni aniqlaydi va admin dan CPL limit so'raydi.
    Har 30 daqiqada tekshiriladi.
    """
    if not ADMIN_ID:
        return

    try:
        meta = MetaAdsService()
        active_campaigns = await meta.get_active_campaigns_list()

        if not active_campaigns:
            return

        new_campaigns = get_new_campaigns(active_campaigns)

        for campaign in new_campaigns:
            cid = str(campaign.get("id", ""))
            cname = campaign.get("name", "Noma'lum")

            # Avval ko'rilgan deb belgilaymiz
            mark_campaign_seen(cid)

            # Limit allaqachon o'rnatilgan bo'lsa so'ramaymiz
            if get_limit(cid) is not None:
                continue

            # Admin ga so'rov yuborish
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="$1", callback_data=f"cpl_limit_{cid}_1.0"),
                    InlineKeyboardButton(text="$2", callback_data=f"cpl_limit_{cid}_2.0"),
                    InlineKeyboardButton(text="$3", callback_data=f"cpl_limit_{cid}_3.0"),
                    InlineKeyboardButton(text="$5", callback_data=f"cpl_limit_{cid}_5.0"),
                ],
                [
                    InlineKeyboardButton(text="$7", callback_data=f"cpl_limit_{cid}_7.0"),
                    InlineKeyboardButton(text="$10", callback_data=f"cpl_limit_{cid}_10.0"),
                    InlineKeyboardButton(text="$15", callback_data=f"cpl_limit_{cid}_15.0"),
                    InlineKeyboardButton(text="$20", callback_data=f"cpl_limit_{cid}_20.0"),
                ],
                [
                    InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data=f"cpl_limit_{cid}_skip"),
                ],
            ])

            await bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🆕 Yangi target kampaniya yoqildi!\n\n"
                    f"📋 Nomi: <b>{cname}</b>\n"
                    f"🆔 ID: {cid}\n\n"
                    f"📊 Bu kampaniya uchun maksimal CPL limitini belgilang.\n"
                    f"CPL limit oshganda kampaniya avtomatik to'xtatiladi va sizga xabar yuboriladi.\n\n"
                    f"💡 Quyidagi summalardan birini tanlang yoki /setlimit komandasidan foydalaning:"
                ),
                parse_mode="HTML",
                reply_markup=kb
            )
            logger.info(f"Yangi kampaniya uchun CPL limit so'raldi: {cname} ({cid})")

    except Exception as e:
        logger.error(f"Yangi kampaniyalarni tekshirishda xato: {e}")


async def monitor_cpl_limits(bot: Bot):
    """
    CPL limitlarni tekshiradi.
    Limit oshganda kampaniyani PAUSED qilib admin ga xabar beradi.
    """
    if not ADMIN_ID:
        return

    limits = get_all_limits()
    if not limits:
        return

    try:
        meta = MetaAdsService()
        campaigns = await meta.get_campaign_insights("today")

        if not campaigns:
            return

        actions_service = MetaActionsService()

        for c in campaigns:
            cid = str(c.get("id", ""))
            if not cid or cid not in limits:
                continue

            cpl_limit = limits[cid].get("cpl_limit")
            if cpl_limit is None:
                continue

            current_cpl = c.get("cpl", 0.0)
            leads = c.get("leads", 0)

            if leads == 0 or current_cpl == 0:
                continue

            if current_cpl > cpl_limit:
                cname = c.get("campaign_name", limits[cid].get("campaign_name", "Noma'lum"))
                spend = c.get("spend", 0.0)

                logger.warning(f"CPL limit oshdi: {cname} → ${current_cpl} (limit: ${cpl_limit})")

                # Kampaniyani avtomatik to'xtatish
                result = await actions_service.update_status(cid, "PAUSED", ADMIN_ID)

                if result["success"]:
                    status_text = "✅ Avtomatik to'xtatildi (PAUSED)"
                else:
                    status_text = f"⚠️ To'xtatishda xato: {result['message']}"

                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"🚨 CPL LIMIT OSHDI — AVTOMATIK TO'XTATILDI\n\n"
                        f"📋 Kampaniya: <b>{cname}</b>\n"
                        f"💰 Xarajat: ${spend:.2f}\n"
                        f"📩 Leadlar: {leads}\n"
                        f"🎯 Joriy CPL: <b>${current_cpl:.2f}</b>\n"
                        f"🚫 CPL Limit: ${cpl_limit:.2f}\n\n"
                        f"🔧 Holat: {status_text}\n\n"
                        f"Yangi limit o'rnatish: /setlimit"
                    ),
                    parse_mode="HTML"
                )

    except Exception as e:
        logger.error(f"CPL limit monitoringda xato: {e}")


async def monitor_ad_performance(bot: Bot):
    """Har 1 soatda Meta Ads ma'lumotlarini tekshiradi."""
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
    """Guruhga avtomatik kampaniya bo'yicha SMS hisobot."""
    if not GROUP_ID:
        return

    try:
        tz = pytz.timezone(TIMEZONE)
        current_hour = datetime.now(tz).hour
        period = "yesterday" if current_hour < 12 else "today"

        meta = MetaAdsService()
        data = await meta.get_account_insights(period)

        if data is None:
            logger.warning(f"⚠️ Real data olinmadi ({period}). Guruhga yuborilmadi.")
            return

        # Kampaniya bo'yicha alohida hisobot
        campaigns = await meta.get_campaign_insights(period)
        date_text = meta.get_date_range_text(period)

        if campaigns:
            # Kampaniyalar bo'yicha qisqa SMS format
            report = build_sms_campaigns_report(campaigns, date_text, total_data=data)
        else:
            report = await build_target_report(period, is_admin=False, include_analysis=False)

        await bot.send_message(chat_id=GROUP_ID, text=report)
        logger.info(f"✅ Avtomatik hisobot guruhga yuborildi ({period}).")

    except Exception as e:
        logger.error(f"❌ Avtomatik hisobot xatoligi: {e}")


def setup_scheduler(bot: Bot):
    """Scheduler ni sozlash."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # 1. Guruhga kampaniya bo'yicha SMS hisobotlar (09:00, 15:00, 21:00)
    for hour in REPORT_HOURS:
        scheduler.add_job(
            send_scheduled_report, "cron",
            hour=hour, minute=0, args=[bot],
            id=f"group_report_{hour}", replace_existing=True
        )

    # 2. Admin uchun to'liq report + AI tahlil
    for time_cfg in ADMIN_REPORT_TIMES:
        h = time_cfg["hour"]
        m = time_cfg["minute"]
        time_label = f"{h:02d}:{m:02d}"
        scheduler.add_job(
            send_admin_full_report, "cron",
            hour=h, minute=m, args=[bot, time_label],
            id=f"admin_report_{h}_{m}", replace_existing=True
        )

    # 3. Har 1 soatda performance monitoring + CPL limit check
    scheduler.add_job(
        monitor_ad_performance, "interval",
        hours=1, args=[bot],
        id="hourly_monitoring", replace_existing=True
    )

    scheduler.add_job(
        monitor_cpl_limits, "interval",
        hours=1, args=[bot],
        id="cpl_limit_monitoring", replace_existing=True
    )

    # 4. Har 30 daqiqada yangi kampaniyalarni tekshirish
    scheduler.add_job(
        check_new_campaigns_and_ask_limits, "interval",
        minutes=30, args=[bot],
        id="new_campaigns_check", replace_existing=True
    )

    scheduler.start()

    admin_times_str = ", ".join(
        f"{t['hour']:02d}:{t['minute']:02d}" for t in ADMIN_REPORT_TIMES
    )
    group_times_str = ", ".join(f"{h}:00" for h in REPORT_HOURS)
    logger.info(f"📅 Scheduler ishga tushdi ({TIMEZONE})")
    logger.info(f"📊 Guruh SMS hisobot: {group_times_str}")
    logger.info(f"🔐 Admin report: {admin_times_str}")
    logger.info(f"🔍 CPL limit monitoring: har 1 soatda")
    logger.info(f"🆕 Yangi kampaniya tekshiruvi: har 30 daqiqada")
