from openai import AsyncOpenAI
from config.settings import OPENAI_API_KEY
from utils.logger import logger

SYSTEM_PROMPT = """Sen dunyabunya qurilish mollari do'koni uchun AI Target Assistant'san.
Faqat marketing, target, reklama, kreativ va qurilish savdosiga oid savollarga javob ber. 
Agar savol marketing va targetga mutlaqo aloqador bo'lmasa (masalan: salom, qalaysan, ob havo, futbol, random chat), shunchaki "IGNORE" so'zini qaytar. Boshqa hech narsa yozma.

dunyabunya haqida:
* dunyabunya — qurilish materiallari gipermarketi. "Barchasi qurilish uchun".
* Asosiy mahsulotlar: gipsokarton, profil, kafel, oboy, linoleum, Tarkett, santexnika, eshik, lyustra, quvur, bazalt, penoplex, qorishmalar, instrumentlar.
* Do'kon yetkazib berish (50 tadan oshiq mashina), o'rnatish va maslahat xizmatlarini taklif qiladi.
* Mijoz segmentlari: uy qurayotganlar, remont qilayotganlar, ustalar, prorablar, quruvchilar, tadbirkorlar.

Vazifalaring:
- Agar foydalanuvchi kreativ so'rasa ("reels ssenariy", "hook", "caption yoz", "oferta"), quyidagi formatda ber:
  1. Sabab/Kontekst
  2. Yangi creative yo'nalish
  3. 3 ta Hook
  4. 1 ta Reels ssenariy
  5. 1 ta Caption
  6. 1 ta CTA
  7. Target tavsiya
- Qisqa, amaliy, targetchi tilida va qurilish sohasi kontekstida javob ber.
- Hallucination qilma. O'zing kampaniyalarni avtomatik o'chira olmaysan, faqat maslahat berasan.
"""

class AIAnalyzer:
    """OpenAI API orqali reklama ma'lumotlarini tahlil qiluvchi service."""

    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None

    async def analyze_metrics(self, account_data: dict, campaigns: list = None, yesterday_data: dict = None) -> str:
        """To'liq tahlil qaytaradi (faqat admin uchun)."""
        if self.client:
            try:
                return await self._openai_analyze(account_data, campaigns, yesterday_data)
            except Exception as e:
                logger.error(f"OpenAI analyze xatolik: {e}")
                return self._local_analyze(account_data, campaigns)
        else:
            return self._local_analyze(account_data, campaigns)

    async def answer_question(self, question: str, account_data: dict, campaigns: list = None, yesterday_data: dict = None, is_admin: bool = True) -> str:
        """Savolga javob."""
        if self.client:
            try:
                return await self._openai_answer(question, account_data, campaigns, yesterday_data, is_admin)
            except Exception as e:
                logger.error(f"OpenAI QA xatolik: {e}")
                return "⚠️ OpenAI xatosi yuz berdi."
        else:
            return "OpenAI ishlamayapti, AI analiz bera olmayman."

    async def _openai_analyze(self, data: dict, campaigns: list = None, yesterday: dict = None) -> str:
        campaign_text = self._format_campaigns(campaigns) if campaigns else "Kampaniyalar yo'q."
        yest_text = f"Kechagi CPL: ${yesterday.get('cpl', 0)}" if yesterday else ""

        prompt = f"""Quyidagi bugungi statistikani tahlil qil. {yest_text}

BUGUNGI DATA: Spend: ${data.get('spend', 0)}, Leads: {data.get('leads', 0)}, CPL: ${data.get('cpl', 0)}, CTR: {data.get('ctr', 0)}%, CPM: ${data.get('cpm', 0)}, Freq: {data.get('frequency', 0)}
KAMPANIYALAR: {campaign_text}

Format:
1. Nima bo'ldi?
2. Sababi nima bo'lishi mumkin?
3. Nima qilish kerak?
4. Qaysi kampaniyani kuzatish kerak?"""

        resp = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            max_tokens=800, temperature=0.7
        )
        return resp.choices[0].message.content.strip()

    async def _openai_answer(self, question: str, data: dict, campaigns: list = None, yesterday: dict = None, is_admin: bool = True) -> str:
        prompt = f"Foydalanuvchi so'radi: {question}\n\n"

        if is_admin:
            campaign_text = self._format_campaigns(campaigns) if campaigns else ""
            y_cpl = yesterday.get('cpl', 0) if yesterday else 0
            prompt += f"""Hozirgi statistika (Kontekst uchun):
Bugun -> Spend: ${data.get('spend', 0)}, Leads: {data.get('leads', 0)}, CPL: ${data.get('cpl', 0)}, CTR: {data.get('ctr', 0)}%, CPM: ${data.get('cpm', 0)}, Freq: {data.get('frequency', 0)}.
Kechagi CPL: ${y_cpl}.
Kampaniyalar: {campaign_text}
"""
        else:
            prompt += """DIQQAT: Bu foydalanuvchi ADMIN EMAS! 
Senda hozirgi statistika yo'q. U senga joriy natijalar (spend, kampaniyalar, qaysi yomonligi) haqida savol bersa, "Uzr, bu maxfiy ma'lumot va faqat adminga beriladi" deb javob ber.
Faqatgina umumiy kreativ yozish, reels ssenariy, target sozlamalari, maslahatlar kabi umumiy savollarga to'liq yordam ber."""

        resp = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            max_tokens=1000, temperature=0.7
        )
        return resp.choices[0].message.content.strip()

    def _local_analyze(self, data: dict, campaigns: list = None) -> str:
        return "OpenAI ulanmagan. Analiz mavjud emas."

    def _format_campaigns(self, campaigns: list) -> str:
        if not campaigns: return ""
        return "\n".join([f"- {c.get('campaign_name')}: CPL=${c.get('cpl')}, CTR={c.get('ctr')}%" for c in campaigns])
