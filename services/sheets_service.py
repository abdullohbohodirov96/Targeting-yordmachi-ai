import json
from datetime import datetime
from config.settings import GOOGLE_SHEETS_ID, GOOGLE_CREDENTIALS_JSON
from services.meta_ads_service import MetaAdsService
from utils.logger import logger

class SheetsService:
    """
    Google Sheets API integratsiyasi.
    Agar ulanmagan bo'lsa, lokal .json faylda arxivlab boradi (fallback sifatida).
    """

    def __init__(self):
        self.sheet_id = GOOGLE_SHEETS_ID
        self.local_cache_file = "data/sheets_cache.json"

    async def sync_today_data(self):
        """Bugungi datani olib Sheets/Cache ga yozadi."""
        meta = MetaAdsService()
        try:
            data = await meta.get_account_insights("today")
            date_str = datetime.now().strftime("%Y-%m-%d")
            data["date"] = date_str
            
            # Agar credentials bo'lsa -> Google Sheetsga yozish logikasi
            if GOOGLE_CREDENTIALS_JSON and self.sheet_id:
                # Hozircha Google Sheets rasmiy integratsiya kutubxonalari kerak. 
                # (gspread yoki google-api-python-client orqali)
                pass 

            # Har doim lokal fallback qilib boramiz (AI trend o'qishi uchun qulay)
            self._write_local_cache(data)

        except Exception as e:
            logger.error(f"Sheets sync xatosi: {e}")

    def _write_local_cache(self, data: dict):
        import os
        if not os.path.exists("data"):
            os.makedirs("data")

        cache = self.get_historical_data()
        # Bugungi datani update qilish yoki qo'shish
        for i, row in enumerate(cache):
            if row.get("date") == data["date"]:
                cache[i] = data
                break
        else:
            cache.append(data)
            
        with open(self.local_cache_file, "w") as f:
            json.dump(cache, f, indent=4)

    def get_historical_data(self) -> list:
        import os
        if os.path.exists(self.local_cache_file):
            try:
                with open(self.local_cache_file, "r") as f:
                    return json.load(f)
            except Exception:
                return []
        return []
