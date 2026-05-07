from services.meta_ads import get_ad_data
from services.ai_analyzer import analyze_data

async def build_report(period: str) -> str:
    """
    Hisobot matnini tayyorlaydi
    """
    data = await get_ad_data(period)
    if not data:
        return "Ma'lumot topilmadi."
        
    analysis = await analyze_data(data)
    
    title = "Bugungi" if period == "today" else "Haftalik"
    
    # Raqamlarni probel bilan formatlash (masalan, 41200 -> 41 200)
    impressions = f"{data['impressions']:,}".replace(",", " ")
    reach = f"{data['reach']:,}".replace(",", " ")
    
    report = (
        f"📊 {title} Target Hisoboti\n\n"
        f"💰 Xarajat: ${data['spend']:.2f}\n"
        f"📩 Leadlar: {data['leads']} ta\n"
        f"🎯 CPL: ${data['cpl']:.2f}\n"
        f"👁 Ko‘rishlar: {impressions}\n"
        f"📍 Reach: {reach}\n"
        f"📈 CTR: {data['ctr']}%\n"
        f"🖱 CPC: ${data['cpc']:.2f}\n\n"
        f"🤖 AI tahlil:\n"
        f"{analysis}"
    )
    
    return report
