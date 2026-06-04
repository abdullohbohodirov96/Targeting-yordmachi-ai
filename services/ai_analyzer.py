"""
Professional AI Targeting Mutaxassisi — OpenAI GPT-4o-mini asosida.
Kompaniya profilidan dinamik kontekst oladi.
Suhbat tarixini saqlaydi va aniqlashtiruvchi savollar beradi.
"""
from openai import AsyncOpenAI
from config.settings import OPENAI_API_KEY
from utils.logger import logger
from utils.company_profile import get_profile_context, get_company_name

# ── Suhbat tarixi (user_id → [messages]) ────────────────────────────────────
_conversation_history: dict[int, list[dict]] = {}
MAX_HISTORY = 8  # Eng ko'p saqlanadigan xabar juftligi


def _get_history(user_id: int) -> list[dict]:
    return _conversation_history.get(user_id, [])


def _add_to_history(user_id: int, role: str, content: str):
    if user_id not in _conversation_history:
        _conversation_history[user_id] = []
    _conversation_history[user_id].append({"role": role, "content": content})
    # Eski xabarlarni tozalash
    if len(_conversation_history[user_id]) > MAX_HISTORY * 2:
        _conversation_history[user_id] = _conversation_history[user_id][-MAX_HISTORY * 2:]


def _clear_history(user_id: int):
    _conversation_history.pop(user_id, None)


def _build_system_prompt() -> str:
    """Dinamik system prompt — kompaniya profili bilan."""
    company_ctx = get_profile_context()
    company_name = get_company_name()

    base = f"""Sen professional AI Targeting Mutaxassisisisan — real xodim.
Kompaniyaning Meta Ads (Facebook/Instagram) kampaniyalarini boshqarasan, tahlil qilasan va optimallashtirasан.

{company_ctx if company_ctx else f"* Kompaniya: {company_name}"}

MUTAXASSIS SIFATIDA VAZIFALARING:
1. Meta Ads kampaniya tahlili va optimizatsiyasi
2. Target auditoriya sozlamalari va tavsiyalari
3. Creative kontent (reels ssenariy, hook, caption, ad copy, DM script)
4. Marketing funnel va lead generation strategiyasi
5. Kampaniyalar bo'yicha qarorlar (pause, enable, budget tavsiyalari)
6. A/B test rejalashtirish va creative fatigue diagnostikasi

QOIDALAR:
- HECH QACHON o'ylab raqam topma — faqat senga berilgan real data asosida gapir
- Agar ma'lumot yetmasa yoki savol noaniq bo'lsa: qisqa ANIQLASHTIRUVCHI SAVOL ber (1-2 savol max)
- Aniqlashtiruvchi savol boshlanishi: "❓" belgisi bilan
- Faqat marketing/targeting/reklama sohalariga javob ber
- Agar savol mutlaqo aloqasiz bo'lsa (futbol, ob-havo, oshpazlik) — "IGNORE" qaytar
- Javoblar qisqa, amaliy va professional bo'lsin
- Data bo'lmagan joyda "taxminan" yoki "odatda shunday bo'ladi" deb raqam ixtiro qilma

KREATIV FORMAT (so'ralganda):
1. Sabab/Kontekst
2. Yangi creative yo'nalish
3. 3 ta Hook varianti
4. 1 ta Reels ssenariy
5. 1 ta Caption
6. 1 ta CTA
7. Target auditoriya tavsiyasi"""

    return base


class AIAnalyzer:
    """OpenAI API orqali professional targeting analizi."""

    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.client = None
        if self.api_key:
            try:
                self.client = AsyncOpenAI(api_key=self.api_key)
            except Exception as e:
                logger.error(f"OpenAI client xato: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC METHODS
    # ─────────────────────────────────────────────────────────────────────────

    async def analyze_metrics(
        self,
        account_data: dict,
        campaigns: list = None,
        yesterday_data: dict = None,
    ) -> str:
        if not account_data:
            return "📊 Analiz uchun real Meta Ads data kerak. API'dan ma'lumot olinmadi."
        if self.client:
            try:
                return await self._openai_analyze(account_data, campaigns, yesterday_data)
            except Exception as e:
                logger.error(f"OpenAI analyze xato: {e}")
                return self._local_analyze(account_data, campaigns)
        return self._local_analyze(account_data, campaigns)

    async def answer_question(
        self,
        question: str,
        account_data: dict,
        campaigns: list = None,
        yesterday_data: dict = None,
        is_admin: bool = True,
        user_id: int = 0,
    ) -> str:
        if self.client:
            try:
                return await self._openai_answer(
                    question, account_data, campaigns, yesterday_data, is_admin, user_id
                )
            except Exception as e:
                logger.error(f"OpenAI QA xato: {e}")
                return "⚠️ AI xizmatida vaqtinchalik nosozlik. Iltimos, qayta urinib ko'ring."
        return "⚠️ OpenAI API kaliti sozlanmagan. AI analiz bera olmayman."

    async def generate_monitoring_alert(
        self, data: dict, yesterday: dict, issues: list
    ) -> str:
        if not self.client:
            return "⚠️ AI ulanmagan. Iltimos, natijalarni qo'lda tekshiring."

        company_name = get_company_name()
        issues_text = "\n".join(f"- {i}" for i in issues)
        y_cpl = yesterday.get("cpl", "?") if yesterday else "Noma'lum"

        prompt = f"""DIQQAT: {company_name} reklamalarida muammo aniqlandi!

ANIQLANGAN MUAMMOLAR:
{issues_text}

BUGUNGI REAL DATA:
Spend: ${data.get('spend')}, Leads: {data.get('leads')}, CPL: ${data.get('cpl')},
CTR: {data.get('ctr')}%, CPM: ${data.get('cpm')}, Freq: {data.get('frequency')}

KECHAGI DATA:
CPL: ${y_cpl}

VAZIFA:
1. Muammolarni {company_name} kontekstida qisqa tahlil qil
2. Amaliy 5 ta tavsiya ber
3. Faqat real raqamlar asosida gapir

FORMAT:
🧠 Xulosa: (1-2 jumla)
📋 Tavsiyalar:
• ...
• ...
• ...
• ...
• ..."""

        try:
            resp = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _build_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=600,
                temperature=0.6,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Monitoring alert xato: {e}")
            return f"⚠️ AI tahlili yuklanmadi. Muammolar: {', '.join(issues)}"

    async def parse_action_intent(self, text: str) -> dict | None:
        """Xabardan Meta action intentini aniqlaydi."""
        if not self.client:
            return None

        prompt = f"""Foydalanuvchi: "{text}"

Bu matn Meta Ads kampaniyasini o'zgartirish so'rovimi? Aniqlash:
- pause/o'chir/to'xtat → action: "pause"
- yoq/enable/active → action: "enable"
- budget o'zgartir → action: "budget"
- duplicate/copy/nusxa → action: "duplicate"
- create/yarat/yangi → action: "create"

AGAR marketing yordami (creative, reels, ssenariy, strategiya) haqida bo'lsa → "NONE"
AGAR guruhga yuborish haqida bo'lsa → "NONE"
AGAR aniq ob'ekt nomi ko'rsatilmagan bo'lsa → "NONE"

Object turlari:
- campaigns: campaign, kampaniya
- adsets: adset, ad set, target
- ads: ad, reklama, e'lon

Agar action bo'lsa, FAQAT JSON:
{{"action": "pause|enable|budget|create|duplicate", "obj_type": "campaigns|adsets|ads", "query": "ob'ekt nomi (bo'lmasa bo'sh)", "budget": null_yoki_son}}

Misollar:
"bazalt kampaniyani o'chir" → {{"action":"pause","obj_type":"campaigns","query":"bazalt","budget":null}}
"remont adsetini yoq" → {{"action":"enable","obj_type":"adsets","query":"remont","budget":null}}
"20$ budget qo'y" → {{"action":"budget","obj_type":"campaigns","query":"","budget":20}}
"reels g'oyasi ber" → NONE"""

        try:
            resp = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=120,
                temperature=0.0,
            )
            content = resp.choices[0].message.content.strip()
            if content == "NONE":
                return None

            import json
            for fence in ["```json", "```"]:
                if fence in content:
                    content = content.split(fence)[1].split("```")[0].strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"Intent parsing xato: {e}")
            return None

    async def analyze_task(self, text: str) -> dict:
        """Admin vazifasini tahlil qiladi."""
        if not self.client:
            return {"can_do": False, "message": "AI ulanmagan."}

        company_name = get_company_name()
        prompt = f"""Admin vazifa: "{text}"

Sen nima qila olasan:
1. send_to_group: Guruhga chiroyli xabar yuborish (markdown, emojilar bilan)
2. marketing_advice: Marketing/kreativ maslahat

Agar guruhga yozish bo'lsa → "send_to_group" va "formatted_text" maydoniga tayyor xabarni yoz.
Agar qila olmasang → can_do: false.

FAQAT JSON:
{{"can_do": true/false, "action": "send_to_group|marketing_advice|none", "formatted_text": "...", "message": "admin uchun javob"}}"""

        try:
            resp = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _build_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1000,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            import json
            return json.loads(resp.choices[0].message.content.strip())
        except Exception as e:
            logger.error(f"Task analysis xato: {e}")
            return {"can_do": False, "message": f"Xatolik: {e}"}

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE METHODS
    # ─────────────────────────────────────────────────────────────────────────

    async def _openai_analyze(
        self, data: dict, campaigns: list = None, yesterday: dict = None
    ) -> str:
        campaign_text = self._format_campaigns(campaigns) if campaigns else "Ma'lumot yo'q."
        y_cpl = f"${yesterday.get('cpl', 0)}" if yesterday else "Ma'lumot yo'q"

        leads = data.get("leads", 0)
        spend = data.get("spend", 0)
        cpl_text = (
            f"${data.get('cpl', 0)}"
            if leads > 0 and spend > 0
            else ("hisoblab bo'lmadi (lead yo'q)" if spend > 0 else "$0")
        )

        prompt = f"""Quyidagi REAL statistikani tahlil qil. Kechagi CPL: {y_cpl}

BUGUNGI DATA: Spend: ${spend}, Leads: {leads}, CPL: {cpl_text}, CTR: {data.get('ctr', 0)}%, CPM: ${data.get('cpm', 0)}, Freq: {data.get('frequency', 0)}
KAMPANIYALAR: {campaign_text}

MUHIM: Faqat yuqoridagi real raqamlar asosida tahlil qil.

Format:
1. Nima bo'ldi? (real raqamlar)
2. Sababi nima bo'lishi mumkin?
3. Nima qilish kerak? (konkret tavsiya)
4. Qaysi kampaniyani kuzatish kerak?"""

        resp = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
            temperature=0.6,
        )
        return resp.choices[0].message.content.strip()

    async def _openai_answer(
        self,
        question: str,
        data: dict,
        campaigns: list = None,
        yesterday: dict = None,
        is_admin: bool = True,
        user_id: int = 0,
    ) -> str:
        system = _build_system_prompt()

        # Suhbat tarixini olish
        history = _get_history(user_id) if user_id else []

        # Kontekst qurilishi
        context_block = ""
        if is_admin:
            if data:
                campaign_text = self._format_campaigns(campaigns) if campaigns else ""
                y_cpl = yesterday.get("cpl", 0) if yesterday else "ma'lumot yo'q"
                leads = data.get("leads", 0)
                spend = data.get("spend", 0)
                cpl_text = (
                    f"${data.get('cpl', 0)}"
                    if leads > 0 and spend > 0
                    else ("hisoblab bo'lmadi" if spend > 0 else "$0")
                )
                context_block = (
                    f"\n\nHOZIRGI REAL DATA:\n"
                    f"Spend: ${spend}, Leads: {leads}, CPL: {cpl_text}, "
                    f"CTR: {data.get('ctr', 0)}%, CPM: ${data.get('cpm', 0)}, "
                    f"Freq: {data.get('frequency', 0)}. Kechagi CPL: ${y_cpl}.\n"
                    f"Kampaniyalar: {campaign_text}\n"
                    f"MUHIM: Faqat yuqoridagi real raqamlar asosida javob ber."
                )
            else:
                context_block = (
                    "\n\nDIQQAT: Hozirda Meta API'dan real data olinmadi. "
                    "Statistika so'ralsa: 'Hozirda real data olinmadi, API ishlashi kerak' de. "
                    "Marketing/kreativ savol bo'lsa — to'liq yaxshi javob ber."
                )
        else:
            context_block = (
                "\n\nDIQQAT: Bu foydalanuvchi ADMIN EMAS. "
                "Maxfiy raqamlar, kampaniya nomlari, spend, CPL berma. "
                "Faqat umumiy kreativ, target sozlamalari, marketing maslahat ber."
            )

        # Xabarlar ro'yxati
        messages = [{"role": "system", "content": system + context_block}]
        messages.extend(history)
        messages.append({"role": "user", "content": question})

        resp = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=1000,
            temperature=0.7,
        )
        answer = resp.choices[0].message.content.strip()

        # Tariхga qo'shish
        if user_id:
            _add_to_history(user_id, "user", question)
            _add_to_history(user_id, "assistant", answer)

        return answer

    def _local_analyze(self, data: dict, campaigns: list = None) -> str:
        """OpenAI ulanmagan bo'lsa — sodda lokal tahlil."""
        if not data:
            return "📊 Analiz uchun real Meta Ads data kerak."

        lines = ["📊 Tahlil (AI ulanmagan):\n"]
        spend = data.get("spend", 0)
        leads = data.get("leads", 0)

        lines.append(f"💰 Xarajat: ${spend:.2f}" if spend > 0 else "💰 Xarajat: $0")
        if leads > 0:
            lines.append(f"📩 Leadlar: {leads}")
            if spend > 0:
                lines.append(f"🎯 CPL: ${round(spend/leads, 2)}")
        else:
            lines.append("📩 Leadlar: 0")
            if spend > 0:
                lines.append("🎯 CPL: hisoblab bo'lmadi (lead yo'q)")

        ctr = data.get("ctr", 0)
        if ctr > 0:
            lines.append(f"📈 CTR: {ctr}%")

        lines.append("\n⚠️ To'liq AI tahlil uchun OpenAI API kalitini sozlang.")
        return "\n".join(lines)

    def _format_campaigns(self, campaigns: list) -> str:
        if not campaigns:
            return ""
        return " | ".join(
            f"{c.get('campaign_name','?')}: CPL=${c.get('cpl','?')}, CTR={c.get('ctr','?')}%"
            for c in campaigns[:8]
        )
