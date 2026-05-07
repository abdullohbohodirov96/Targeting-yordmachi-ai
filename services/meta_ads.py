import random

async def get_ad_data(period: str) -> dict:
    """
    Meta Ads API'dan ma'lumot olish.
    Hozircha API ulanmagani uchun test (fake) ma'lumotlar qaytaradi.
    period: 'today' yoki 'week'
    """
    # Kelajakda config dan tokenlarni olib API ga zapros yuboriladi:
    # from config import META_ACCESS_TOKEN, META_AD_ACCOUNT_ID
    # URL = f"https://graph.facebook.com/v19.0/{META_AD_ACCOUNT_ID}/insights"
    
    if period == "today":
        return {
            "spend": 25.40,
            "leads": 76,
            "cpl": 0.33,
            "impressions": 41200,
            "reach": 18500,
            "ctr": 1.45,
            "cpc": 0.06,
        }
    elif period == "week":
        return {
            "spend": 178.50,
            "leads": 530,
            "cpl": 0.34,
            "impressions": 285400,
            "reach": 125000,
            "ctr": 1.52,
            "cpc": 0.07,
        }
    
    return {}
