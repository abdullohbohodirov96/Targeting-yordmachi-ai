from openai import AsyncOpenAI
from config.settings import OPENAI_API_KEY
from utils.logger import logger

SYSTEM_PROMPT = """Sen dunyabunya qurilish mollari do'koni uchun AI Target Assistant'san.
Faqat marketing, target, reklama, kreativ va qurilish savdosiga oid savollarga javob ber. 
Agar savol marketing va targetga mutlaqo aloqador bo'lmasa (masalan: salom, qalaysan, ob havo, futbol, random chat), shunchaki "IGNORE" so'zini qaytar. Boshqa hech narsa yozma.

MUHIM QOIDA: Sen hech qachon real data bo'lmagan joyda raqam o'ylab topma. Faqat mavjud data asosida gapir. Agar data yetmasa, ochiq ayt: "Bu ma'lumot menda yo'q" yoki "Buni aniqlash uchun real data kerak" yoki "O'ylab topmayman". Taxminiy raqamlar, o'rtacha qiymatlar yoki "odatda shunday bo'ladi" kabi gaplar bilan aldama.

dunyabunya haqida:
* dunyabunya — qurilish materiallari gipermarketi. "Barchasi qurilish uchun".
* Asosiy mahsulotlar: gipsokarton, profil, kafel, oboy, linoleum, Tarkett, santexnika, eshik, lyustra, quvur, bazalt, penoplex, qorishmalar, instrumentlar.
* Do'kon yetkazib berish (50 tadan oshiq mashina), o'rnatish va maslahat xizmatlarini taklif qiladi.
* Mijoz segmentlari: uy qurayotganlar, remont qilayotganlar, ustalar, prorablar, quruvchilar, tadbirkorlar.

Vazifalaring:
- Agar foydalanuvchi kreativ so'rasa ("reels ssenariy", "hook", "caption yoz", "oferta", "ad copy", "DM script", "content plan"), quyidagi formatda ber:
  1. Sabab/Kontekst
  2. Yangi creative yo'nalish
  3. 3 ta Hook
  4. 1 ta Reels ssenariy
  5. 1 ta Caption
  6. 1 ta CTA
  7. Target tavsiya
- Marketing strategiya so'ralsa: Dunyabunya qurilish sohasi kontekstida amaliy, batafsil javob ber.
- Target setting, audience, budget tavsiya so'ralsa: real tajriba asosida javob ber.
- Sales script, offer yaratish, lead quality analysis so'ralsa: qurilish sohasi uchun moslangan javob ber.
- Qisqa, amaliy, targetchi tilida va qurilish sohasi kontekstida javob ber.
- Hallucination qilma. O'zing kampaniyalarni avtomatik o'chira olmaysan, faqat maslahat berasan.
- Raqamlar faqat senga berilgan real data'dan bo'lsin. O'ylab topilgan raqam ishlatma.
"""

class AIAnalyzer:
    """OpenAI API orqali reklama ma'lumotlarini tahlil qiluvchi service."""

    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None

    async def analyze_metrics(self, account_data: dict, campaigns: list = None, yesterday_data: dict = None) -> str:
        """
        To'liq tahlil qaytaradi (faqat admin uchun).
        Agar real data bo'lmasa, analiz qilmaydi.
        """
        # Real data bo'lmasa analiz qilmaymiz
        if not account_data:
            return "📊 Analiz uchun real Meta Ads data kerak. Hozirda API'dan ma'lumot olinmadi."

        if self.client:
            try:
                return await self._openai_analyze(account_data, campaigns, yesterday_data)
            except Exception as e:
                logger.error(f"OpenAI analyze xatolik: {e}")
                return self._local_analyze(account_data, campaigns)
        else:
            return self._local_analyze(account_data, campaigns)

    async def answer_question(self, question: str, account_data: dict, campaigns: list = None, yesterday_data: dict = None, is_admin: bool = True) -> str:
        """
        Savolga javob.
        Admin uchun — real data kontekstida.
        Oddiy user uchun — faqat umumiy marketing yordam.
        """
        if self.client:
            try:
                return await self._openai_answer(question, account_data, campaigns, yesterday_data, is_admin)
            except Exception as e:
                logger.error(f"OpenAI QA xatolik: {e}")
                return "⚠️ OpenAI xatosi yuz berdi."
        else:
            return "OpenAI ishlamayapti, AI analiz bera olmayman."

    async def _openai_analyze(self, data: dict, campaigns: list = None, yesterday: dict = None) -> str:
        campaign_text = self._format_campaigns(campaigns) if campaigns else "Kampaniyalar ma'lumoti yo'q."

        # Kechagi data bilan solishtirish
        yest_text = ""
        if yesterday:
            yest_text = f"Kechagi CPL: ${yesterday.get('cpl', 0)}"
        else:
            yest_text = "Kechagi data olinmadi."

        # CPL formatlash
        leads = data.get('leads', 0)
        spend = data.get('spend', 0)
        if leads > 0 and spend > 0:
            cpl_text = f"${data.get('cpl', 0)}"
        elif leads == 0 and spend > 0:
            cpl_text = "hisoblab bo'lmadi (lead yo'q)"
        else:
            cpl_text = "$0"

        prompt = f"""Quyidagi bugungi REAL statistikani tahlil qil. {yest_text}

BUGUNGI REAL DATA: Spend: ${spend}, Leads: {leads}, CPL: {cpl_text}, CTR: {data.get('ctr', 0)}%, CPM: ${data.get('cpm', 0)}, Freq: {data.get('frequency', 0)}
KAMPANIYALAR: {campaign_text}

MUHIM: Faqat yuqoridagi real raqamlar asosida tahlil qil. O'ylab raqam qo'shma. Agar biror metric yo'q bo'lsa, "ma'lumot yo'q" deb yoz.

Format:
1. Nima bo'ldi? (faqat real raqamlar asosida)
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
            # Admin uchun — agar real data bor bo'lsa, kontekst sifatida beramiz
            if data:
                campaign_text = self._format_campaigns(campaigns) if campaigns else ""
                y_cpl = yesterday.get('cpl', 0) if yesterday else "ma'lumot yo'q"

                leads = data.get('leads', 0)
                spend = data.get('spend', 0)
                if leads > 0 and spend > 0:
                    cpl_text = f"${data.get('cpl', 0)}"
                elif leads == 0 and spend > 0:
                    cpl_text = "hisoblab bo'lmadi (lead yo'q)"
                else:
                    cpl_text = "$0"

                prompt += f"""Hozirgi REAL statistika (Kontekst uchun):
Bugun -> Spend: ${spend}, Leads: {leads}, CPL: {cpl_text}, CTR: {data.get('ctr', 0)}%, CPM: ${data.get('cpm', 0)}, Freq: {data.get('frequency', 0)}.
Kechagi CPL: ${y_cpl}.
Kampaniyalar: {campaign_text}

MUHIM: Faqat yuqoridagi real raqamlar asosida javob ber. O'ylab raqam qo'shma.
"""
            else:
                prompt += """DIQQAT: Hozirda Meta API'dan real data olinmadi.
Agar foydalanuvchi statistika so'rasa: "Hozirda real Meta Ads data olinmadi. Statistika uchun API ishlashi kerak." deb javob ber.
Agar marketing/kreativ savol bo'lsa (creative, reels, target, audience, caption, hook, DM script, strategy, budget, content plan, ad copy, sales script, offer) — to'liq yaxshi javob ber.
"""
        else:
            prompt += """DIQQAT: Bu foydalanuvchi ADMIN EMAS! 
Senda hozirgi statistika yo'q. U senga joriy natijalar (spend, kampaniyalar, qaysi yomonligi) haqida savol bersa, "Uzr, bu maxfiy ma'lumot va faqat adminga beriladi" deb javob ber.
Maxfiy raqamlar, kampaniya nomlari, spend, CPL, CTR, lead sifati berma.
Faqatgina umumiy kreativ yozish, reels ssenariy, target sozlamalari, marketing maslahatlar, content plan, ad copy kabi umumiy savollarga to'liq yordam ber."""

        resp = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            max_tokens=1000, temperature=0.7
        )
        return resp.choices[0].message.content.strip()

    def _local_analyze(self, data: dict, campaigns: list = None) -> str:
        """OpenAI ulanmagan bo'lsa, oddiy lokal tahlil."""
        if not data:
            return "📊 Analiz uchun real Meta Ads data kerak."

        lines = ["📊 Oddiy tahlil (OpenAI ulanmagan):\n"]

        spend = data.get('spend', 0)
        leads = data.get('leads', 0)

        if spend > 0:
            lines.append(f"💰 Bugungi xarajat: ${spend:.2f}")
        else:
            lines.append("💰 Bugungi xarajat: $0 yoki ma'lumot yo'q")

        if leads > 0:
            lines.append(f"📩 Leadlar: {leads}")
            if spend > 0:
                cpl = round(spend / leads, 2)
                lines.append(f"🎯 CPL: ${cpl}")
        else:
            lines.append("📩 Leadlar: 0 yoki ma'lumot yo'q")
            if spend > 0:
                lines.append("🎯 CPL: hisoblab bo'lmadi (lead yo'q)")

        ctr = data.get('ctr', 0)
        if ctr > 0:
            lines.append(f"📈 CTR: {ctr}%")

        lines.append("\n⚠️ To'liq AI tahlil uchun OpenAI API kalitini sozlang.")
        return "\n".join(lines)

    def _format_campaigns(self, campaigns: list) -> str:
        if not campaigns:
            return ""
        return "\n".join([f"- {c.get('campaign_name')}: CPL=${c.get('cpl')}, CTR={c.get('ctr')}%" for c in campaigns])
