from datetime import datetime
from services.meta_ads_service import MetaAdsService
from services.ai_analyzer import AIAnalyzer
from utils.logger import logger

# Real data olinmaganida ko'rsatiladigan xabar
NO_DATA_MSG = (
    "❌ Real Meta Ads ma'lumot topilmadi.\n"
    "Iltimos, tekshiring:\n\n"
    "• META_ACCESS_TOKEN to'g'rimi\n"
    "• META_AD_ACCOUNT_ID to'g'rimi\n"
    "• token'da ads_read permission bormi\n"
    "• ad account access bormi\n"
    "• kampaniyada bugun data bormi"
)


async def build_target_report(period: str = None, since: str = None, until: str = None, is_admin: bool = False, include_analysis: bool = False) -> str:
    """
    Asosiy report builder. 
    period yoki since/until orqali data oladi.
    Public yoki Admin formatda qaytaradi.
    """
    try:
        meta = MetaAdsService()
        
        # 1. Data olish
        if since and until:
            data = await meta.get_account_insights_by_date(since, until)
            date_range_text = f"{datetime.strptime(since, '%Y-%m-%d').strftime('%d.%m.%Y')} — {datetime.strptime(until, '%Y-%m-%d').strftime('%d.%m.%Y')}"
            if since == until:
                date_range_text = datetime.strptime(since, '%Y-%m-%d').strftime('%d.%m.%Y')
        else:
            period = period or "today"
            data = await meta.get_account_insights(period)
            date_range_text = meta.get_date_range_text(period)

        if data is None:
            return NO_DATA_MSG

        # 2. Public report tuzish
        report = build_public_report(data, date_range_text)

        # 3. Admin qismlarini qo'shish (faqat is_admin=True bo'lsa)
        if is_admin:
            campaigns = []
            camp_result = await meta.get_campaign_insights(period or "today")
            campaigns = camp_result if camp_result is not None else []
            
            # Kampaniya tahlili qo'shish
            admin_part = _build_admin_part(campaigns)
            report += admin_part

            # AI Analiz qo'shish
            if include_analysis:
                ai = AIAnalyzer()
                try:
                    yesterday_data = await meta.get_account_insights("yesterday")
                    analysis = await ai.analyze_metrics(data, campaigns, yesterday_data)
                    report += f"\n\n🤖 AI Tahlil:\n{analysis}"
                except Exception as e:
                    logger.error(f"AI tahlil xatolik: {e}")
                    report += "\n\n🤖 AI Tahlil:\nHozircha tahlil mavjud emas."

        return report

    except Exception as e:
        logger.error(f"Report tuzishda xato: {e}")
        return f"❌ Xatolik yuz berdi: {e}"


def build_public_report(data: dict, date_range_text: str) -> str:
    """Faqat KPI raqamlarini o'z ichiga olgan ochiq hisobot."""
    impressions_fmt = f"{data['impressions']:,}".replace(",", " ")
    reach_fmt = f"{data['reach']:,}".replace(",", " ")

    # CPL formatlash
    if data['leads'] > 0 and data['spend'] > 0:
        cpl_text = f"${data['cpl']:.2f}"
    elif data['leads'] == 0 and data['spend'] > 0:
        cpl_text = "hisoblab bo'lmadi"
    else:
        cpl_text = "$0.00"

    return (
        f"📊 TARGET HISOBOTI\n"
        f"📅 Davr: {date_range_text}\n"
        f"🟢 Real Data\n\n"
        f"💰 Xarajat: ${data['spend']:.2f}\n"
        f"📩 Leadlar: {data['leads']}\n"
        f"💬 Xabarlar: {data['messages']}\n"
        f"🎯 CPL: {cpl_text}\n"
        f"📈 CTR: {data['ctr']}%\n"
        f"🖱 CPC: ${data['cpc']:.2f}\n"
        f"📉 CPM: ${data['cpm']:.2f}\n"
        f"👁 Impressions: {impressions_fmt}\n"
        f"📍 Reach: {reach_fmt}\n"
        f"🔄 Frequency: {data['frequency']}"
    )


def _build_admin_part(campaigns: list) -> str:
    """Admin uchun maxfiy kampaniya ma'lumotlari."""
    if not campaigns:
        return "\n\n📋 Faol kampaniyalar topilmadi."
    
    best = max(campaigns, key=lambda c: c.get("leads", 0))
    worst = min(campaigns, key=lambda c: c.get("ctr", 999))
    
    return (
        f"\n\n🔥 Eng yaxshi kampaniya:\n{best.get('campaign_name', '—')}\n\n"
        f"⚠️ Eng yomon kampaniya:\n{worst.get('campaign_name', '—')}"
    )


async def build_campaigns_report(period: str) -> str:
    """Kampaniyalar bo'yicha batafsil hisobot (admin uchun)."""
    try:
        meta = MetaAdsService()
        campaigns = await meta.get_campaign_insights(period)
        if campaigns is None: return NO_DATA_MSG
        if not campaigns: return "📋 Hozirda faol kampaniyalar topilmadi."

        date_text = meta.get_date_range_text(period)
        lines = [f"📋 KAMPANIYALAR HISOBOTI\n📅 Davr: {date_text}\n"]
        
        for i, c in enumerate(campaigns, 1):
            emoji = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else f"{i}."))
            c_leads = c.get('leads', 0)
            c_spend = c.get('spend', 0)
            cpl = f"${c.get('cpl', 0):.2f}" if c_leads > 0 else "—"
            
            lines.append(
                f"{emoji} {c.get('campaign_name', '?')}\n"
                f"   💰 ${c_spend:.2f} | 📩 {c_leads} lead\n"
                f"   🎯 CPL: {cpl} | 📈 CTR: {c.get('ctr', 0)}%\n"
            )
        
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Campaign report xato: {e}")
        return f"❌ Xato: {e}"
