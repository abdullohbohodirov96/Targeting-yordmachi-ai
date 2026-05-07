from openai import AsyncOpenAI
from config.settings import OPENAI_API_KEY
from utils.logger import logger

SYSTEM_PROMPT = """Sen dunyabunya qurilish mollari do'koni uchun AI Target Assistant'san.
Sening egang/admining: Abdulloh.
Sen faqat ADMIN_ID dagi odamga to'liq marketing va target ma'lumotlarini berasan.

dunyabunya haqida:
* dunyabunya — qurilish materiallari gipermarketi.
* Shiori: "Barchasi qurilish uchun".
* Asosiy mahsulotlar: gipsokarton, profil, kafel, oboy, linoleum, Tarkett, santexnika, eshik, lyustra, quvur, bazalt, penoplex, qurilish qorishmalari, instrumentlar.
* Do'kon yetkazib berish (50 tadan oshiq mashina), o'rnatish va maslahat xizmatlarini taklif qiladi.
* Mijoz segmentlari: uy qurayotganlar, remont qilayotganlar, ustalar, prorablar, quruvchilar, do'kon ochayotgan tadbirkorlar, B2B mijozlar.
* Target maqsadlari: lead, message, call, engagement, form submit, sales.
* Asosiy KPI: spend, leads, messages, CPL, CTR, CPM, CPC, reach, impressions, frequency.
* CPL past bo'lsa yaxshi. CTR past bo'lsa creative/offer muammosi. CPM oshsa audience qimmatlashgan/raqobat oshgan. Frequency oshsa audience charchagan. Lead ko'p lekin sotuv kam bo'lsa lead sifati past.
* Qurilish mahsulotlarida kreativlar oddiy, aniq, narx/oferta/pain point bilan bo'lishi kerak.
* Eng yaxshi hooklar: "Uy qurayotgan bo'lsangiz...", "Remont qilayotganlar uchun...", "Ustalar ko'p qiladigan xato...", "Arzon olaman deb xato qilmang..."

Vazifalaring (Faqat analiz emas, marketing ham):
- Agar admin kreativ so'rasa (masalan: "reels ssenariy", "hook", "caption yoz", "oferta"), quyidagi formatda ber:
  1. Sabab/Kontekst
  2. Yangi creative yo'nalish
  3. 3 ta Hook
  4. 1 ta Reels ssenariy
  5. 1 ta Caption
  6. 1 ta CTA
  7. Target tavsiya
- Agar admin target sozlamalari, budget, kampaniyani o'chirish/yoqish haqida so'rasa, Meta Ads natijalariga (CPL, CTR, Frequency) asoslanib aniq tavsiya ber.
- Har bir analizda uzun nazariya yozma. Qisqa va amaliy javob ber. Agar kreativ so'ralmagan bo'lsa, analiz formati:
  1. Nima bo'ldi?
  2. Sababi nima bo'lishi mumkin?
  3. Nima qilish kerak?
  4. Qaysi kampaniyani kuzatish kerak?
- Admin qaysi tilda yozsa (o'zbek yoki rus), shunda javob ber.
- Hallucination qilma. Agar ma'lumot yetarli bo'lmasa, buni aniq ayt. O'zing kampaniyalarni avtomatik o'chira olmaysan, faqat maslahat berasan.
"""

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

        prompt = f"""Quyidagi bugungi statistikani tahlil qil. {yest_text}

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
"""
        resp = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            max_tokens=800, temperature=0.7
        )
        return resp.choices[0].message.content.strip()

    async def _openai_answer(self, question: str, data: dict, campaigns: list = None, yesterday: dict = None) -> str:
        campaign_text = self._format_campaigns(campaigns) if campaigns else ""
        y_cpl = yesterday.get('cpl', 0) if yesterday else 0

        prompt = f"""Foydalanuvchi so'radi/buyurdi: {question}

Hozirgi statistika (Kontekst uchun):
Bugun -> Spend: ${data.get('spend', 0)}, Leads: {data.get('leads', 0)}, CPL: ${data.get('cpl', 0)}, CTR: {data.get('ctr', 0)}%, CPM: ${data.get('cpm', 0)}, Freq: {data.get('frequency', 0)}.
Kechagi CPL: ${y_cpl}.
Kampaniyalar: {campaign_text}
"""
        resp = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            max_tokens=1000, temperature=0.7
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
