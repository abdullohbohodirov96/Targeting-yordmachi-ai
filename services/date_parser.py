"""
Natural language date parser for Uzbek/Russian date formats.
Supports:
- 1 may, 1-may, 01.05, 01.05.2026
- 1 maydan 5 maygacha
- с 1 мая по 5 мая
- bugungi/kechagi/haftalik/oylik
- статистика за 1 мая / отчет за неделю
"""

import re
from datetime import datetime, timedelta


# Uzbek oy nomlari
UZ_MONTHS = {
    "yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4,
    "may": 5, "iyun": 6, "iyul": 7, "avgust": 8,
    "sentabr": 9, "oktyabr": 10, "noyabr": 11, "dekabr": 12,
}

# Russian oy nomlari (barcha formalar)
RU_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4,
    "ма": 5, "мая": 5, "май": 5, "июн": 6, "июл": 7, "август": 8,
    "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

# Statistika kalit so'zlari
STAT_KEYWORDS_UZ = [
    "statistika", "hisobot", "report", "natija",
    "ko'rsat", "tashla", "ber", "chiqar",
]
STAT_KEYWORDS_RU = [
    "статистик", "отчет", "отчёт", "результат",
]

# Period kalit so'zlari
PERIOD_KEYWORDS = {
    # Uzbek
    "bugun": "today", "bugungi": "today",
    "kecha": "yesterday", "kechagi": "yesterday",
    "hafta": "week", "haftalik": "week",
    "oy": "month", "oylik": "month",
    # Russian
    "сегодня": "today", "сегодняшн": "today",
    "вчера": "yesterday", "вчерашн": "yesterday",
    "недел": "week", "неделю": "week",
    "месяц": "month", "месяца": "month",
}


def _find_month(text: str) -> int | None:
    """Matndan oy raqamini topadi."""
    text_lower = text.lower()
    for name, num in UZ_MONTHS.items():
        if name in text_lower:
            return num
    for name, num in RU_MONTHS.items():
        if name in text_lower:
            return num
    return None


def _extract_day(text: str, month_name: str) -> int | None:
    """Matndan kun raqamini topadi (oy nomidan oldin)."""
    # "1 may", "01 may", "1-may", "1may"
    pattern = rf'(\d{{1,2}})\s*[-\s]?\s*{re.escape(month_name)}'
    match = re.search(pattern, text.lower())
    if match:
        return int(match.group(1))
    return None


def _extract_year(text: str) -> int:
    """Matndan yil topadi, topilmasa joriy yil."""
    match = re.search(r'20\d{2}', text)
    if match:
        return int(match.group())
    return datetime.now().year


def is_date_request(text: str) -> bool:
    """Matn statistika/hisobot so'rovimi?"""
    text_lower = text.lower()

    # Period kalit so'zlari
    for kw in PERIOD_KEYWORDS:
        if kw in text_lower:
            # "statistika", "hisobot", "report" ham bo'lishi kerak
            for sk in STAT_KEYWORDS_UZ + STAT_KEYWORDS_RU:
                if sk in text_lower:
                    return True

    # Aniq sana bor — "1 may statistika", "01.05 hisobot"
    has_date = bool(re.search(r'\d{1,2}[.\s-]\s*\d{1,2}', text_lower)) or _find_month(text_lower) is not None
    has_stat_keyword = any(kw in text_lower for kw in STAT_KEYWORDS_UZ + STAT_KEYWORDS_RU)

    if has_date and has_stat_keyword:
        return True

    # Faqat sana + "tashla/ber/chiqar"
    if has_date and any(kw in text_lower for kw in ["tashla", "ber", "chiqar", "ko'rsat"]):
        return True

    return False


def parse_date_request(text: str) -> dict | None:
    """
    Matndan sana yoki davr ajratib oladi.
    Returns: {"since": "YYYY-MM-DD", "until": "YYYY-MM-DD", "display": "01.05.2026 — 05.05.2026"}
    yoki {"period": "today"/"yesterday"/"week"/"month"}
    yoki None
    """
    text_lower = text.lower().strip()
    year = _extract_year(text)

    # 1. Period kalit so'zlarini tekshirish
    for kw, period in PERIOD_KEYWORDS.items():
        if kw in text_lower:
            return {"period": period}

    # 2. DD.MM.YYYY yoki DD.MM formati
    # Oraliq: 01.05.2026 — 05.05.2026 yoki 01.05 - 05.05
    range_dot = re.search(
        r'(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\s*[-—–]\s*(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?',
        text_lower
    )
    if range_dot:
        d1, m1 = int(range_dot.group(1)), int(range_dot.group(2))
        y1 = int(range_dot.group(3)) if range_dot.group(3) else year
        d2, m2 = int(range_dot.group(4)), int(range_dot.group(5))
        y2 = int(range_dot.group(6)) if range_dot.group(6) else year
        try:
            since = datetime(y1, m1, d1).date()
            until = datetime(y2, m2, d2).date()
            return {
                "since": since.strftime("%Y-%m-%d"),
                "until": until.strftime("%Y-%m-%d"),
                "display": f"{since.strftime('%d.%m.%Y')} — {until.strftime('%d.%m.%Y')}"
            }
        except ValueError:
            pass

    # Bitta sana: 01.05.2026 yoki 01.05
    single_dot = re.search(r'(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?', text_lower)
    if single_dot:
        d, m = int(single_dot.group(1)), int(single_dot.group(2))
        y = int(single_dot.group(3)) if single_dot.group(3) else year
        try:
            date = datetime(y, m, d).date()
            return {
                "since": date.strftime("%Y-%m-%d"),
                "until": date.strftime("%Y-%m-%d"),
                "display": date.strftime("%d.%m.%Y")
            }
        except ValueError:
            pass

    # 3. "1 maydan 5 maygacha" yoki "с 1 мая по 5 мая"
    month_num = _find_month(text_lower)
    if month_num:
        # Oraliq: "1 maydan 5 maygacha" yoki "с 1 мая по 5 мая"
        range_match = re.findall(r'(\d{1,2})', text_lower)
        if len(range_match) >= 2 and ("gacha" in text_lower or "dan" in text_lower
                                       or "по" in text_lower or "до" in text_lower):
            d1, d2 = int(range_match[0]), int(range_match[1])
            try:
                since = datetime(year, month_num, d1).date()
                until = datetime(year, month_num, d2).date()
                return {
                    "since": since.strftime("%Y-%m-%d"),
                    "until": until.strftime("%Y-%m-%d"),
                    "display": f"{since.strftime('%d.%m.%Y')} — {until.strftime('%d.%m.%Y')}"
                }
            except ValueError:
                pass

        # Bitta sana: "1 may", "1 мая"
        day_nums = re.findall(r'(\d{1,2})', text_lower)
        if day_nums:
            d = int(day_nums[0])
            try:
                date = datetime(year, month_num, d).date()
                return {
                    "since": date.strftime("%Y-%m-%d"),
                    "until": date.strftime("%Y-%m-%d"),
                    "display": date.strftime("%d.%m.%Y")
                }
            except ValueError:
                pass

    return None
