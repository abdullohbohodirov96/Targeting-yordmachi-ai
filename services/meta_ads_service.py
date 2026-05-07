import random

class MetaAdsService:
    def __init__(self, access_token: str, account_id: str):
        self.access_token = access_token
        self.account_id = account_id

    async def get_insights(self, period: str) -> dict:
        """
        period: 'today', 'yesterday', 'week', 'month'
        Returns mock data if real API is not connected.
        """
        # Hozircha Fake Data qaytaramiz (API to'liq ulanmaganligi sababli test uchun)
        base_multiplier = {
            "today": 1,
            "yesterday": 1.1,
            "week": 7,
            "month": 30
        }.get(period, 1)

        spend = round(random.uniform(20.0, 50.0) * base_multiplier, 2)
        leads = int(random.randint(50, 100) * base_multiplier)
        cpl = round(spend / leads if leads > 0 else 0, 2)
        impressions = int(random.randint(30000, 50000) * base_multiplier)
        reach = int(impressions * 0.45)
        ctr = round(random.uniform(1.0, 3.0), 2)
        cpc = round(random.uniform(0.05, 0.15), 2)
        cpm = round((spend / impressions) * 1000 if impressions > 0 else 0, 2)
        messages = int(leads * 1.5)
        frequency = round(impressions / reach if reach > 0 else 1, 2)

        return {
            "spend": spend,
            "leads": leads,
            "messages": messages,
            "cpl": cpl,
            "cpc": cpc,
            "cpm": cpm,
            "ctr": ctr,
            "reach": reach,
            "impressions": impressions,
            "frequency": frequency,
            "best_campaign": "Linoleum Reels",
            "worst_campaign": "Kitchen Form"
        }
