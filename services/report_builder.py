from datetime import datetime
from services.meta_ads_service import MetaAdsService
from services.ai_analyzer import AIAnalyzer
from utils.logger import logger


async def build_target_report(period: str, is_admin: bool = False, include_analysis: bool = False) -> str:
    """
    To'liq target hisobotini tuzadi.
    Agar is_admin False bo'lsa, faqat oddiy hisobot qaytadi.
    """
    try:
        meta = MetaAdsService()
        ai = AIAnalyzer()

        # Account umumiy statistikasi
        data = await meta.get_account_insights(period)
        if not data:
            return f"❌ Ma'lumot topilmadi ({period})"

        # Kampaniyalar faqat admin uchun kerak bo'lishi mumkin
        campaigns = []
        if is_admin:
            campaigns = await meta.get_campaign_insights(period)

    except Exception as e:
        logger.error(f"Meta API dan ma'lumot olishda xato: {e}")
        return f"❌ Meta API Xatoligi: {e}"

    # Raqamlarni formatlash
    impressions_fmt = f"{data['impressions']:,}".replace(",", " ")
    reach_fmt = f"{data['reach']:,}".replace(",", " ")

    date_str = datetime.now().strftime("%d.%m.%Y")
    period_label = {
        "today": "BUGUNGI",
        "yesterday": "KECHAGI",
        "week": "HAFTALIK",
        "month": "OYLIK"
    }.get(period, period.upper())

    # Data source label
    source = "🟢 Real Data" if data.get("is_real_data") else "🟡 Test Data"

    # ODDIY HISOBOT QISMI
    report = (
        f"📊 {period_label} TARGET HISOBOTI\n\n"
        f"📅 Sana: {date_str}\n"
        f"{source}\n\n"
        f"💰 Xarajat: ${data['spend']:.2f}\n"
        f"📩 Leadlar: {data['leads']}\n"
        f"💬 Xabarlar: {data['messages']}\n"
        f"🎯 CPL: ${data['cpl']:.2f}\n"
        f"📈 CTR: {data['ctr']}%\n"
        f"🖱 CPC: ${data['cpc']:.2f}\n"
        f"📉 CPM: ${data['cpm']:.2f}\n"
        f"👁 Impressions: {impressions_fmt}\n"
        f"📍 Reach: {reach_fmt}\n"
        f"🔄 Frequency: {data['frequency']}"
    )

    # FAQAT ADMIN UCHUN QO'SHIMCHA QISMLAR
    if is_admin:
        best_name = "—"
        worst_name = "—"
        if campaigns:
            best = max(campaigns, key=lambda c: c.get("leads", 0))
            worst = min(campaigns, key=lambda c: c.get("ctr", 999))
            best_name = best.get("campaign_name", "—")
            worst_name = worst.get("campaign_name", "—")
            
        report += (
            f"\n\n🔥 Eng yaxshi kampaniya:\n{best_name}\n\n"
            f"⚠️ Eng yomon kampaniya:\n{worst_name}"
        )

        if include_analysis:
            try:
                # Qo'shimcha kechagi data bilan solishtirish (Sheets yoki Meta orqali)
                yesterday_data = await meta.get_account_insights("yesterday")
                analysis = await ai.analyze_metrics(data, campaigns, yesterday_data)
                report += f"\n\n🤖 AI Tahlil:\n{analysis}"
            except Exception as e:
                logger.error(f"AI tahlil xatolik: {e}")
                report += "\n\n🤖 AI Tahlil:\nHozircha tahlil mavjud emas."

    return report


async def build_campaigns_report(period: str) -> str:
    """Kampaniyalar bo'yicha alohida hisobot (faqat admin)."""
    try:
        meta = MetaAdsService()
        campaigns = await meta.get_campaign_insights(period)
    except Exception as e:
        logger.error(f"Meta API dan ma'lumot olishda xato: {e}")
        return f"❌ Meta API Xatoligi: {e}"

    if not campaigns:
        return "❌ Kampaniya ma'lumotlari topilmadi."

    lines = ["📋 KAMPANIYALAR HISOBOTI\n"]
    for i, c in enumerate(campaigns, 1):
        emoji = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else f"{i}."))
        lines.append(
            f"{emoji} {c.get('campaign_name', '?')}\n"
            f"   💰 ${c.get('spend', 0):.2f} | 📩 {c.get('leads', 0)} lead\n"
            f"   🎯 CPL: ${c.get('cpl', 0):.2f} | 📈 CTR: {c.get('ctr', 0)}%\n"
            f"   🔄 Freq: {c.get('frequency', 0)}\n"
        )

    # Eng yaxshi/yomon
    best = max(campaigns, key=lambda c: c.get("leads", 0))
    worst = min(campaigns, key=lambda c: c.get("ctr", 999))
    lines.append(f"✅ Scale qilish: {best.get('campaign_name', '?')}")
    lines.append(f"❌ O'chirish/yangilash: {worst.get('campaign_name', '?')}")

    return "\n".join(lines)
