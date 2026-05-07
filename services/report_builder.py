from datetime import datetime
from config.settings import META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, OPENAI_API_KEY
from services.meta_ads_service import MetaAdsService
from services.ai_analyzer import AIAnalyzer

async def build_target_report(period: str) -> str:
    """
    Hisobot shakllantiruvchi fuksiya
    period: today, yesterday, week, month
    """
    meta_service = MetaAdsService(META_ACCESS_TOKEN, META_AD_ACCOUNT_ID)
    ai_service = AIAnalyzer(OPENAI_API_KEY)

    data = await meta_service.get_insights(period)
    if not data:
        return f"Ma'lumot topilmadi ({period})"

    analysis = await ai_service.analyze_metrics(data)
    
    # Raqamlarni chiroyli formatlash
    impressions = f"{data['impressions']:,}".replace(",", " ")
    reach = f"{data['reach']:,}".replace(",", " ")
    
    date_str = datetime.now().strftime("%d.%m.%Y")
    
    report = (
        f"📊 TARGET HISOBOTI ({period.upper()})\n\n"
        f"📅 Sana: {date_str}\n\n"
        f"💰 Xarajat: ${data['spend']:.2f}\n"
        f"📩 Leadlar: {data['leads']}\n"
        f"✉️ Xabarlar: {data['messages']}\n"
        f"🎯 CPL: ${data['cpl']:.2f}\n"
        f"📈 CTR: {data['ctr']}%\n"
        f"🖱 CPC: ${data['cpc']:.2f}\n"
        f"📉 CPM: ${data['cpm']:.2f}\n"
        f"👁 Impressions: {impressions}\n"
        f"📍 Reach: {reach}\n"
        f"🔄 Frequency: {data['frequency']}\n\n"
        f"🔥 Eng yaxshi kampaniya:\n{data['best_campaign']}\n\n"
        f"⚠️ Eng yomon kampaniya:\n{data['worst_campaign']}\n\n"
        f"🤖 AI Tahlil:\n{analysis}"
    )
    return report
