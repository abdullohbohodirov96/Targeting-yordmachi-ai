import aiohttp
import random
from config.settings import META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_BASE_URL
from utils.logger import logger


class MetaAdsService:
    """
    Meta Marketing API bilan ishlash uchun xizmat.
    Agar ulanish yoki o'zgaruvchilar yo'q bo'lsa, Render deploy qulayligi uchun fake data qaytaradi va crash bo'lmaydi.
    """

    def __init__(self):
        self.access_token = str(META_ACCESS_TOKEN) if META_ACCESS_TOKEN else None
        self.account_id = str(META_AD_ACCOUNT_ID) if META_AD_ACCOUNT_ID else None
        self.base_url = META_BASE_URL

    def _get_date_preset(self, period: str) -> str:
        """Davr bo'yicha Meta API uchun date_preset ni qaytaradi."""
        mapping = {
            "today": "today",
            "yesterday": "yesterday",
            "week": "this_week",
            "month": "this_month"
        }
        return mapping.get(period, "today")

    async def get_account_insights(self, period: str) -> dict:
        """Meta Ads API dan umumiy account statistikasini oladi."""
        if not self.access_token or not self.account_id:
            logger.error("Iltimos, Render Environment Variables'ga qo'shing: META_ACCESS_TOKEN va META_AD_ACCOUNT_ID")
            return self._get_fallback_data(period)

        date_preset = self._get_date_preset(period)
        url = f"{self.base_url}/{self.account_id}/insights"
        params = {
            "access_token": self.access_token,
            "fields": "spend,impressions,reach,cpc,cpm,ctr,frequency,actions",
            "date_preset": date_preset,
            "level": "account",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Meta API error ({resp.status}): {error_text}")
                        return self._get_fallback_data(period)

                    result = await resp.json()
                    data_list = result.get("data", [])
                    if not data_list:
                        return self._empty_account_data()

                    raw = data_list[0]
                    return self._parse_account_data(raw)
        except Exception as e:
            logger.error(f"Meta API xatosi (Exception): {e}")
            return self._get_fallback_data(period)


    async def get_campaign_insights(self, period: str) -> list:
        """Har bir kampaniya bo'yicha alohida ma'lumot oladi."""
        if not self.access_token or not self.account_id:
            logger.error("Iltimos, Render Environment Variables'ga qo'shing: META_ACCESS_TOKEN va META_AD_ACCOUNT_ID")
            return self._get_fallback_campaigns()

        date_preset = self._get_date_preset(period)
        url = f"{self.base_url}/{self.account_id}/insights"
        params = {
            "access_token": self.access_token,
            "fields": "campaign_name,spend,impressions,reach,cpc,cpm,ctr,frequency,actions",
            "date_preset": date_preset,
            "level": "campaign",
            "limit": 50,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Meta Campaign API error ({resp.status}): {error_text}")
                        return self._get_fallback_campaigns()

                    result = await resp.json()
                    data_list = result.get("data", [])
                    if not data_list:
                        return []

                    campaigns = []
                    for raw in data_list:
                        campaigns.append(self._parse_campaign_data(raw))
                    return campaigns
        except Exception as e:
            logger.error(f"Meta Campaign API xatosi: {e}")
            return self._get_fallback_campaigns()

    def _empty_account_data(self) -> dict:
        return {
            "spend": 0.0, "leads": 0, "messages": 0, "cpl": 0.0,
            "cpc": 0.0, "cpm": 0.0, "ctr": 0.0, "reach": 0,
            "impressions": 0, "frequency": 0.0, "is_real_data": True,
        }

    def _parse_account_data(self, raw: dict) -> dict:
        spend = float(raw.get("spend", 0))
        impressions = int(raw.get("impressions", 0))
        reach = int(raw.get("reach", 0))
        cpc = float(raw.get("cpc", 0))
        cpm = float(raw.get("cpm", 0))
        ctr = float(raw.get("ctr", 0))
        frequency = float(raw.get("frequency", 0))

        leads = 0
        messages = 0
        actions = raw.get("actions", [])
        
        for action in actions:
            action_type = action.get("action_type", "")
            value = float(action.get("value", 0))
            if action_type == "lead":
                leads += int(value)
            elif action_type in ("onsite_conversion.messaging_conversation_started_7d",
                                  "onsite_conversion.messaging_first_reply",
                                  "messages"):
                messages += int(value)

        cpl = round(spend / leads, 2) if leads > 0 else 0

        return {
            "spend": round(spend, 2), "leads": leads, "messages": messages,
            "cpl": cpl, "cpc": round(cpc, 2), "cpm": round(cpm, 2),
            "ctr": round(ctr, 2), "reach": reach, "impressions": impressions,
            "frequency": round(frequency, 2), "is_real_data": True,
        }

    def _parse_campaign_data(self, raw: dict) -> dict:
        data = self._parse_account_data(raw)
        data["campaign_name"] = raw.get("campaign_name", "Noma'lum")
        return data

    def _get_fallback_data(self, period: str) -> dict:
        """API ishlamasa (Render variables qo'shilmagan bo'lsa), test data qaytaradi."""
        logger.info(f"Fallback (fake) data ishlatilmoqda ({period})")
        m = {"today": 1, "yesterday": 1.1, "week": 7, "month": 30}.get(period, 1)

        spend = round(random.uniform(20, 50) * m, 2)
        leads = int(random.randint(50, 100) * m)
        cpl = round(spend / leads, 2) if leads > 0 else 0
        impressions = int(random.randint(30000, 50000) * m)
        reach = int(impressions * random.uniform(0.4, 0.5))
        ctr = round(random.uniform(1.0, 3.0), 2)
        cpc = round(random.uniform(0.04, 0.12), 2)
        cpm = round((spend / impressions) * 1000 if impressions > 0 else 0, 2)
        messages = int(leads * random.uniform(1.2, 1.8))
        frequency = round(impressions / reach if reach > 0 else 1, 2)

        return {
            "spend": spend, "leads": leads, "messages": messages, "cpl": cpl,
            "cpc": cpc, "cpm": cpm, "ctr": ctr, "reach": reach,
            "impressions": impressions, "frequency": frequency, "is_real_data": False,
        }

    def _get_fallback_campaigns(self) -> list:
        return [
            {"campaign_name": "Linoleum Reels", "spend": 8.50, "leads": 32, "cpl": 0.27,
             "cpc": 0.05, "cpm": 3.20, "ctr": 2.10, "reach": 6500, "impressions": 14200,
             "frequency": 2.18, "messages": 45, "is_real_data": False},
            {"campaign_name": "Plitka Carousel", "spend": 6.20, "leads": 18, "cpl": 0.34,
             "cpc": 0.07, "cpm": 4.10, "ctr": 1.65, "reach": 4200, "impressions": 9800,
             "frequency": 2.33, "messages": 22, "is_real_data": False},
            {"campaign_name": "Kitchen Form", "spend": 10.70, "leads": 12, "cpl": 0.89,
             "cpc": 0.14, "cpm": 7.80, "ctr": 0.85, "reach": 3800, "impressions": 8500,
             "frequency": 2.24, "messages": 8, "is_real_data": False},
        ]
