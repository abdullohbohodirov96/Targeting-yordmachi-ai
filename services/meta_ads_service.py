import aiohttp
from config.settings import META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_BASE_URL
from utils.logger import logger


class MetaAdsService:
    """
    Meta Marketing API bilan ishlash uchun xizmat.
    Agar API ishlamasa yoki credentials bo'lmasa, None qaytaradi.
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

    async def get_account_insights(self, period: str) -> dict | None:
        """
        Meta Ads API dan umumiy account statistikasini oladi.
        Agar API ishlamasa yoki credentials yo'q bo'lsa, None qaytaradi.
        """
        if not self.access_token or not self.account_id:
            logger.error(
                "❌ META_ACCESS_TOKEN yoki META_AD_ACCOUNT_ID sozlanmagan. "
                "Render Environment Variables'ga qo'shing."
            )
            return None

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
                        return None

                    result = await resp.json()
                    data_list = result.get("data", [])
                    if not data_list:
                        return self._empty_account_data()

                    raw = data_list[0]
                    return self._parse_account_data(raw)
        except Exception as e:
            logger.error(f"Meta API xatosi (Exception): {e}")
            return None

    async def get_campaign_insights(self, period: str) -> list | None:
        """
        Har bir kampaniya bo'yicha alohida ma'lumot oladi.
        Agar API ishlamasa yoki credentials yo'q bo'lsa, None qaytaradi.
        """
        if not self.access_token or not self.account_id:
            logger.error(
                "❌ META_ACCESS_TOKEN yoki META_AD_ACCOUNT_ID sozlanmagan. "
                "Render Environment Variables'ga qo'shing."
            )
            return None

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
                        return None

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
            return None

    def _empty_account_data(self) -> dict:
        """API javob berdi, lekin hech qanday data yo'q (masalan, reklama ishlamayapti)."""
        return {
            "spend": 0.0, "leads": 0, "messages": 0, "cpl": 0.0,
            "cpc": 0.0, "cpm": 0.0, "ctr": 0.0, "reach": 0,
            "impressions": 0, "frequency": 0.0,
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
            "frequency": round(frequency, 2),
        }

    def _parse_campaign_data(self, raw: dict) -> dict:
        data = self._parse_account_data(raw)
        data["campaign_name"] = raw.get("campaign_name", "Noma'lum")
        return data
