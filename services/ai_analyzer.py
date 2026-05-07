class AIAnalyzer:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def analyze_metrics(self, data: dict) -> str:
        """
        Statik tahlil matnini yoki OpenAI qilingan tahlilni qaytaradi.
        """
        cpl = data.get("cpl", 0)
        ctr = data.get("ctr", 0)
        
        analysis = []
        if ctr >= 1.5:
            analysis.append("CTR yaxshi.")
        else:
            analysis.append("CTR past, kreativni almashtirish yoki yomon reklamalarni o'chirish kerak.")
            
        if cpl < 0.5:
            analysis.append("CPL juda yaxshi.")
            analysis.append("Eng yaxshi reklama budjetini oshirish (scale qilish) mumkin.")
        elif cpl < 1.0:
            analysis.append("CPL normal darajada.")
        else:
            analysis.append("CPL qimmat. Sabab: Audience burnout yoki kreativ muammosi bo'lishi mumkin.")
            
        analysis.append("Yomon reklama kreativini almashtirish tavsiya qilinadi.")
        
        return "\n".join(analysis)

    async def answer_question(self, question: str, context_data: dict) -> str:
        """
        Foydalanuvchi bergan savolga mos javob qaytaradi.
        """
        # Hozircha oddiy statik logika, kelajakda OpenAI chat completion ga ulanadi.
        q = question.lower()
        if "cpl" in q and "osh" in q:
            return "CPL oshishining asosiy sababi: reklama chastotasi (frequency) ortishi natijasida auditoriyaning zerikishi (audience burnout) yoki kreativlarning eskirganligidir."
        elif "yaxshi" in q and "kampaniya" in q:
            return f"Hozirda eng yaxshi kampaniya: {context_data.get('best_campaign', 'Noma`lum')}. Bu yerda CPL past va CTR yuqori."
        elif "o'chirish" in q or "yomon" in q:
            return f"Hozirda eng yomon kampaniya: {context_data.get('worst_campaign', 'Noma`lum')}. Shu kampaniyani o'chirish yoki kreativini yangilash tavsiya etiladi."
        else:
            return "Kechirasiz, aniq ma'lumot olish uchun 'CPL nega oshdi?', 'Qaysi kampaniya yaxshi?' kabi savollar bering."
