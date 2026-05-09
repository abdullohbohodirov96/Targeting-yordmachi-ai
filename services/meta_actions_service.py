"""
Meta Marketing API orqali campaign/adset/ad boshqarish.
Faqat admin tasdiqlashidan keyin action bajariladi.
"""
import aiohttp
from datetime import datetime
from config.settings import META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_BASE_URL
from utils.logger import logger

# Action log (in-memory, Render restart bo'lsa tozalanadi)
action_log = []


class MetaActionsService:
    """Campaign, Adset, Ad bo'yicha amallar bajaradi."""

    def __init__(self):
        self.access_token = str(META_ACCESS_TOKEN) if META_ACCESS_TOKEN else None
        self.account_id = str(META_AD_ACCOUNT_ID) if META_AD_ACCOUNT_ID else None
        self.base_url = META_BASE_URL

    async def search_objects(self, query: str, obj_type: str = "campaigns") -> list:
        """
        Campaign/adset/ad nomini qidiradi.
        obj_type: "campaigns", "adsets", "ads"
        """
        if not self.access_token or not self.account_id:
            return []

        endpoint_map = {
            "campaigns": "campaigns",
            "adsets": "adsets",
            "ads": "ads",
        }
        endpoint = endpoint_map.get(obj_type, "campaigns")
        url = f"{self.base_url}/{self.account_id}/{endpoint}"
        params = {
            "access_token": self.access_token,
            "fields": "id,name,status,daily_budget,lifetime_budget",
            "limit": 100,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.error(f"Meta search error: {await resp.text()}")
                        return []
                    result = await resp.json()
                    all_objects = result.get("data", [])

                    # Nomdan qidirish (case-insensitive)
                    query_lower = query.lower()
                    matches = [
                        obj for obj in all_objects
                        if query_lower in obj.get("name", "").lower()
                    ]
                    return matches
        except Exception as e:
            logger.error(f"Meta search exception: {e}")
            return []

    async def update_status(self, object_id: str, new_status: str, admin_id: int) -> dict:
        """
        Campaign/adset/ad statusini o'zgartiradi.
        new_status: "PAUSED" yoki "ACTIVE"
        Returns: {"success": True/False, "message": "..."}
        """
        if not self.access_token:
            return {"success": False, "message": "META_ACCESS_TOKEN sozlanmagan."}

        url = f"{self.base_url}/{object_id}"
        data = {
            "access_token": self.access_token,
            "status": new_status,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    result = await resp.json()

                    if resp.status == 200 and result.get("success", False):
                        self._log_action(admin_id, "status_change", object_id, "—", new_status, "success")
                        return {"success": True, "message": f"Status: {new_status}"}
                    else:
                        error_msg = result.get("error", {}).get("message", str(result))
                        self._log_action(admin_id, "status_change", object_id, "—", new_status, f"failed: {error_msg}")
                        return {"success": False, "message": error_msg}
        except Exception as e:
            self._log_action(admin_id, "status_change", object_id, "—", new_status, f"exception: {e}")
            return {"success": False, "message": str(e)}

    async def update_budget(self, object_id: str, budget_dollars: float, admin_id: int) -> dict:
        """
        Campaign/adset daily_budget ni o'zgartiradi.
        budget_dollars: USD qiymat ($20)
        Meta API cents/minor units kutadi: $20 = 2000
        """
        if not self.access_token:
            return {"success": False, "message": "META_ACCESS_TOKEN sozlanmagan."}

        budget_cents = int(budget_dollars * 100)
        url = f"{self.base_url}/{object_id}"
        data = {
            "access_token": self.access_token,
            "daily_budget": budget_cents,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    result = await resp.json()

                    if resp.status == 200 and result.get("success", False):
                        self._log_action(admin_id, "budget_change", object_id, "—", f"${budget_dollars}", "success")
                        return {"success": True, "message": f"Budget: ${budget_dollars}"}
                    else:
                        error_msg = result.get("error", {}).get("message", str(result))
                        self._log_action(admin_id, "budget_change", object_id, "—", f"${budget_dollars}", f"failed: {error_msg}")
                        return {"success": False, "message": error_msg}
        except Exception as e:
            self._log_action(admin_id, "budget_change", object_id, "—", f"${budget_dollars}", f"exception: {e}")
            return {"success": False, "message": str(e)}

    async def duplicate_object(self, object_id: str, admin_id: int) -> dict:
        """
        Campaign/adset/ad dan nusxa oladi.
        Returns: {"success": True/False, "message": "..."}
        """
        if not self.access_token:
            return {"success": False, "message": "META_ACCESS_TOKEN sozlanmagan."}

        url = f"{self.base_url}/{object_id}/copies"
        data = {
            "access_token": self.access_token,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    result = await resp.json()

                    # Meta API returns a new object ID or copied_..._id
                    if resp.status == 200:
                        new_id = result.get("copied_campaign_id") or result.get("copied_adset_id") or result.get("copied_ad_id") or result.get("id", "Yangi nusxa")
                        self._log_action(admin_id, "duplicate", object_id, "—", str(new_id), "success")
                        return {"success": True, "message": f"Muvaffaqiyatli nusxa olindi. Yangi ID: {new_id}"}
                    else:
                        error_msg = result.get("error", {}).get("message", str(result))
                        self._log_action(admin_id, "duplicate", object_id, "—", "—", f"failed: {error_msg}")
                        return {"success": False, "message": error_msg}
        except Exception as e:
            self._log_action(admin_id, "duplicate", object_id, "—", "—", f"exception: {e}")
            return {"success": False, "message": str(e)}

    def _log_action(self, admin_id, action_type, object_id, old_value, new_value, status):
        """Har bir actionni logga yozish."""
        entry = {
            "admin_id": admin_id,
            "action_type": action_type,
            "object_id": object_id,
            "old_value": old_value,
            "new_value": new_value,
            "time": datetime.now().isoformat(),
            "status": status,
        }
        action_log.append(entry)
        logger.info(f"ACTION LOG: {entry}")
