from openai import AsyncOpenAI
from config.settings import OPENAI_API_KEY
from utils.logger import logger

class AIAnalyzer:
    """OpenAI API orqali reklama ma'lumotlarini tahlil qiluvchi service."""

    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None

    async def analyze_metrics(self, account_data: dict, campaigns: list = None, yesterday_data: dict = None) -> str:
        """To'liq tahlil qaytaradi."""
        if self.client:
            try:
                return await self._openai_analyze(account_data, campaigns, yesterday_data)
            except Exception as e:
                logger.error(f"OpenAI analyze xatolik: {e}")
                return self._local_analyze(account_data, campaigns)
        else:
            return self._local_analyze(account_data, campaigns)

    async def answer_question(self, question: str, account_data: dict, campaigns: list = None, yesterday_data: dict = None) -> str:
        """Savolga javob."""
        if self.client:
            try:
                return await self._openai_answer(question, account_data, campaigns, yesterday_data)
            except Exception as e:
                logger.error(f"OpenAI QA xatolik: {e}")
                return self._local_answer(question, account_data, campaigns)
        else:
            return self._local_answer(question, account_data, campaigns)

    async def _openai_analyze(self, data: dict, campaigns: list = None, yesterday: dict = None) -> str:
        campaign_text = self._format_campaigns(campaigns) if campaigns else "Kampaniyalar yo'q."
        
        yest_text = ""
        if yesterday:
            yest_text = f"Kechagi data: CPL: ${yesterday.get('cpl', 0)}, CTR: {yesterday.get('ctr', 0)}%, Xarajat: ${yesterday.get('spend', 0)}."

        prompt = f"""Sen marketing bo'yicha top professional AI Assistant'san.
Quyidagi bugungi statistikani tahlil qil. {yest_text}

BUGUNGI DATA:
Spend: ${data.get('spend', 0)}
Leads: {data.get('leads', 0)}
CPL: ${data.get('cpl', 0)}
CPC: ${data.get('cpc', 0)}
CPM: ${data.get('cpm', 0)}
CTR: {data.get('ctr', 0)}%
Freq: {data.get('frequency', 0)}

KAMPANIYALAR:
{campaign_text}

Javobing marketingchi tilida qisqa, tushunarli, emojis bilan bo'lsin. Kechagi kun bilan solishtir (trend yaxshimi yomonmi). Scale qilish yoki o'chirish kerakligini ayt. Audience burnout yoki creative fatigue bormi?"""

        resp = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Professional target AI."}, {"role": "user", "content": prompt}],
            max_tokens=600, temperature=0.7
        )
        return resp.choices[0].message.content.strip()

    async def _openai_answer(self, question: str, data: dict, campaigns: list = None, yesterday: dict = None) -> str:
        campaign_text = self._format_campaigns(campaigns) if campaigns else ""
        y_cpl = yesterday.get('cpl', 0) if yesterday else 0

        prompt = f"""Foydalanuvchi so'radi: {question}

Javob berish uchun bazaviy ma'lumotlar:
Bugun -> Spend: ${data.get('spend', 0)}, Leads: {data.get('leads', 0)}, CPL: ${data.get('cpl', 0)}, CTR: {data.get('ctr', 0)}%, CPM: ${data.get('cpm', 0)}, Freq: {data.get('frequency', 0)}.
Kechagi CPL: ${y_cpl}.
Kampaniyalar: {campaign_text}

Professional marketing assistantdek 1-2 xatboshida aniq va lo'nda javob ber."""

        resp = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Professional Target Assistant."}, {"role": "user", "content": prompt}],
            max_tokens=500, temperature=0.7
        )
        return resp.choices[0].message.content.strip()

    def _local_analyze(self, data: dict, campaigns: list = None) -> str:
        lines = []
        if data.get("ctr", 0) >= 1.5: lines.append("✅ CTR yaxshi darajada.")
        else: lines.append("🔴 CTR past, kreativni o'zgartirish kerak.")
        if data.get("frequency", 0) > 2.5: lines.append("⚠️ Frequency oshmoqda, audience burnout!")
        return "\n".join(lines)

    def _local_answer(self, q: str, data: dict, campaigns: list = None) -> str:
        return f"Bugungi statistika:\nCPL: ${data.get('cpl', 0)}, CTR: {data.get('ctr', 0)}%\nOpenAI ishlamayapti, to'liq analiz bera olmayman."

    def _format_campaigns(self, campaigns: list) -> str:
        if not campaigns: return ""
        return "\n".join([f"- {c.get('campaign_name')}: CPL=${c.get('cpl')}, CTR={c.get('ctr')}%" for c in campaigns])
