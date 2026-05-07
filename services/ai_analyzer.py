from openai import AsyncOpenAI
from config.settings import OPENAI_API_KEY
from utils.logger import logger


class AIAnalyzer:
    """
    OpenAI API orqali reklama ma'lumotlarini tahlil qiluvchi production service.
    Agar OpenAI ishlamasa, lokal (offline) tahlil qaytaradi — bot hech qachon o'chmaydi.
    """

    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None

    # ─────────────────────────────────────────────
    #  ASOSIY ANALIZ
    # ─────────────────────────────────────────────
    async def analyze_metrics(self, account_data: dict, campaigns: list = None) -> str:
        """
        Metrikalarni tahlil qilib, tavsiyalar qaytaradi.
        OpenAI ishlasa — real AI, ishlamasa — lokal analiz.
        """
        if self.client:
            try:
                return await self._openai_analyze(account_data, campaigns)
            except Exception as e:
                logger.error(f"OpenAI analyze xatolik: {e}")
                return self._local_analyze(account_data, campaigns)
        else:
            logger.info("OpenAI API key topilmadi. Lokal analiz ishlatiladi.")
            return self._local_analyze(account_data, campaigns)

    # ─────────────────────────────────────────────
    #  SAVOLLARGA JAVOB
    # ─────────────────────────────────────────────
    async def answer_question(self, question: str, account_data: dict, campaigns: list = None) -> str:
        """Foydalanuvchi savoliga AI javob beradi."""
        if self.client:
            try:
                return await self._openai_answer(question, account_data, campaigns)
            except Exception as e:
                logger.error(f"OpenAI QA xatolik: {e}")
                return self._local_answer(question, account_data, campaigns)
        else:
            return self._local_answer(question, account_data, campaigns)

    # ═══════════════════════════════════════════════
    #  OPENAI METODLARI
    # ═══════════════════════════════════════════════
    async def _openai_analyze(self, data: dict, campaigns: list = None) -> str:
        """OpenAI orqali chuqur analiz."""
        campaign_text = self._format_campaigns(campaigns) if campaigns else "Kampaniya ma'lumotlari mavjud emas."

        prompt = f"""Sen professional Meta Ads target reklama tahlilchisisisan.
Quyidagi statistikani tahlil qil va o'zbek tilida qisqa, aniq tavsiyalar ber.

ACCOUNT STATISTIKASI:
- Xarajat: ${data.get('spend', 0)}
- Leadlar: {data.get('leads', 0)}
- Xabarlar: {data.get('messages', 0)}
- CPL: ${data.get('cpl', 0)}
- CPC: ${data.get('cpc', 0)}
- CPM: ${data.get('cpm', 0)}
- CTR: {data.get('ctr', 0)}%
- Reach: {data.get('reach', 0)}
- Impressions: {data.get('impressions', 0)}
- Frequency: {data.get('frequency', 0)}

KAMPANIYALAR:
{campaign_text}

Quyidagilarni tahlil qil:
1. CTR past yoki yuqori?
2. CPM qimmat yoki arzon?
3. CPL qanday?
4. Frequency yuqori bo'lsa audience burnout bormi?
5. Qaysi kampaniyani scale qilish kerak?
6. Qaysi kampaniyani o'chirish kerak?
7. Creative fatigue (kreativ charchaganlik) bormi?
8. Umumiy tavsiya

Javobni qisqa, aniq, punktlar bilan ber. Har bir punkt emoji bilan boshlansin."""

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sen professional reklama tahlilchisisisan. O'zbek tilida javob ber. Qisqa va aniq bo'l."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800,
            temperature=0.7,
        )

        return response.choices[0].message.content.strip()

    async def _openai_answer(self, question: str, data: dict, campaigns: list = None) -> str:
        """OpenAI orqali foydalanuvchi savoliga javob."""
        campaign_text = self._format_campaigns(campaigns) if campaigns else ""

        prompt = f"""Foydalanuvchi savoli: {question}

Quyidagi real reklama ma'lumotlari asosida javob ber:
- Xarajat: ${data.get('spend', 0)}
- Leadlar: {data.get('leads', 0)}
- CPL: ${data.get('cpl', 0)}
- CPC: ${data.get('cpc', 0)}
- CPM: ${data.get('cpm', 0)}
- CTR: {data.get('ctr', 0)}%
- Reach: {data.get('reach', 0)}
- Impressions: {data.get('impressions', 0)}
- Frequency: {data.get('frequency', 0)}
{campaign_text}

O'zbek tilida qisqa javob ber."""

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sen professional Meta Ads tahlilchisisisan. O'zbek tilida javob ber."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.7,
        )

        return response.choices[0].message.content.strip()

    # ═══════════════════════════════════════════════
    #  LOKAL (OFFLINE) TAHLIL — FALLBACK
    # ═══════════════════════════════════════════════
    def _local_analyze(self, data: dict, campaigns: list = None) -> str:
        """OpenAI ishlamasa shu lokal tahlil ishlaydi."""
        lines = []

        # CTR tahlili
        ctr = data.get("ctr", 0)
        if ctr >= 2.0:
            lines.append("✅ CTR yuqori — kreativlar yaxshi ishlayapti.")
        elif ctr >= 1.0:
            lines.append("⚠️ CTR o'rtacha — kreativlarni yangilash foydali.")
        else:
            lines.append("🔴 CTR past — kreativlarni almashtirish SHART. Creative fatigue bo'lishi mumkin.")

        # CPM tahlili
        cpm = data.get("cpm", 0)
        if cpm > 10:
            lines.append("🔴 CPM qimmat — auditoriya tor yoki raqobat yuqori.")
        elif cpm > 5:
            lines.append("⚠️ CPM o'rtacha.")
        else:
            lines.append("✅ CPM arzon — yaxshi natija.")

        # CPL tahlili
        cpl = data.get("cpl", 0)
        if cpl == 0:
            lines.append("⚠️ Leadlar topilmadi yoki hisoblash imkoni yo'q.")
        elif cpl < 0.5:
            lines.append("✅ CPL juda past — budjetni oshirish (scale) mumkin.")
        elif cpl < 1.5:
            lines.append("⚠️ CPL normal darajada.")
        else:
            lines.append("🔴 CPL qimmat — auditoriya yoki kreativ muammosi bor.")

        # Frequency / Audience burnout
        freq = data.get("frequency", 0)
        if freq > 3:
            lines.append("🔴 Frequency yuqori — Audience burnout! Yangi auditoriya kerak.")
        elif freq > 2:
            lines.append("⚠️ Frequency oshmoqda — auditoriyaga e'tibor bering.")
        else:
            lines.append("✅ Frequency normal.")

        # Kampaniya tahlili
        if campaigns and len(campaigns) > 0:
            best = max(campaigns, key=lambda c: c.get("leads", 0))
            worst = min(campaigns, key=lambda c: c.get("ctr", 999))

            lines.append(f"\n📈 Scale qilish kerak: {best.get('campaign_name', '?')} (Leadlar: {best.get('leads', 0)}, CPL: ${best.get('cpl', 0)})")
            lines.append(f"📉 O'chirish/yangilash kerak: {worst.get('campaign_name', '?')} (CTR: {worst.get('ctr', 0)}%, CPL: ${worst.get('cpl', 0)})")

        return "\n".join(lines)

    def _local_answer(self, question: str, data: dict, campaigns: list = None) -> str:
        """Lokal savol-javob."""
        q = question.lower()

        if "cpl" in q and ("osh" in q or "qimmat" in q or "nega" in q):
            freq = data.get("frequency", 0)
            ctr = data.get("ctr", 0)
            reasons = []
            if freq > 2.5:
                reasons.append("Frequency yuqori — auditoriya eskirgan (burnout)")
            if ctr < 1.0:
                reasons.append("CTR past — kreativ yaxshi ishlamayapti")
            reasons.append("Auditoriyani yangilash yoki kreativni almashtirish kerak")
            return "CPL oshishi sabablari:\n" + "\n".join(f"• {r}" for r in reasons)

        elif ("yaxshi" in q or "best" in q) and "kampaniya" in q:
            if campaigns:
                best = max(campaigns, key=lambda c: c.get("leads", 0))
                return f"Eng yaxshi kampaniya: {best['campaign_name']}\nLeadlar: {best['leads']}, CPL: ${best['cpl']}"
            return f"Bugungi umumiy CPL: ${data.get('cpl', 0)}, CTR: {data.get('ctr', 0)}%"

        elif "o'chir" in q or "yomon" in q or "worst" in q:
            if campaigns:
                worst = min(campaigns, key=lambda c: c.get("ctr", 999))
                return f"Eng yomon kampaniya: {worst['campaign_name']}\nCTR: {worst['ctr']}%, CPL: ${worst['cpl']}\nShu kampaniya kreativini almashtirish yoki o'chirish tavsiya etiladi."
            return "Kampaniya ma'lumotlari hali yuklanmagan."

        elif "ctr" in q:
            ctr = data.get("ctr", 0)
            return f"CTR: {ctr}%. " + ("Yaxshi natija!" if ctr >= 1.5 else "Past — kreativlarni yangilash kerak.")

        elif "bugun" in q or "natija" in q or "today" in q:
            return (f"Bugungi natija:\n"
                    f"💰 Xarajat: ${data.get('spend', 0)}\n"
                    f"📩 Leadlar: {data.get('leads', 0)}\n"
                    f"🎯 CPL: ${data.get('cpl', 0)}\n"
                    f"📈 CTR: {data.get('ctr', 0)}%")

        elif "scale" in q or "kuchaytir" in q or "oshir" in q:
            if campaigns:
                best = max(campaigns, key=lambda c: c.get("leads", 0))
                return f"Scale qilish uchun: {best['campaign_name']}\nCPL past va leadlar ko'p — budjetni 20-30% ga oshirish mumkin."
            return "Kampaniya ma'lumotlari yuklanmagan."

        else:
            return (f"Bugungi umumiy statistika:\n"
                    f"💰 ${data.get('spend', 0)} | 📩 {data.get('leads', 0)} lead | 🎯 CPL ${data.get('cpl', 0)}\n"
                    f"Aniqroq savol bering: 'CPL nega oshdi?', 'Qaysi kampaniya yaxshi?', 'Qaysi reklamani o'chirish kerak?'")

    # ─────────────────────────────────────────────
    #  YORDAMCHI
    # ─────────────────────────────────────────────
    def _format_campaigns(self, campaigns: list) -> str:
        """Kampaniyalar ro'yxatini matn formatga o'giradi."""
        if not campaigns:
            return ""
        lines = []
        for c in campaigns:
            lines.append(
                f"- {c.get('campaign_name', '?')}: "
                f"Spend=${c.get('spend', 0)}, Leads={c.get('leads', 0)}, "
                f"CPL=${c.get('cpl', 0)}, CTR={c.get('ctr', 0)}%, "
                f"Frequency={c.get('frequency', 0)}"
            )
        return "\n".join(lines)
