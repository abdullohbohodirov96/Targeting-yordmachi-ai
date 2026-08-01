"""
monthly_report.py -- Oylik "TARGET HISOBOTI" PDF hujjatini quradi.

Foydalanuvchi (Abdulloh) talabiga ko'ra: har bir kampaniya (target) uchun
nomi, yo'nalishi (Lead/Xabar), maqsadi (objective), xarajat, natija, CPL,
ko'rishlar (impressions), qamrov (reach) ALOHIDA-ALOHIDA, aniq va tushunarli
PDF hisobotda ko'rsatilishi kerak. Shu bilan birga: umumiy oy xulosasi,
oldingi davr bilan solishtirish, byudjet monitoring, va kunlik jadval ham
qo'shiladi (foydalanuvchi so'ragan qo'shimchalar, barchasi tanlandi).

MUHIM ARXITEKTURA QARORI: bu modulda barcha RAQAMLAR 100% DETERMINISTIK
Python kod bilan hisoblanadi -- HECH QANDAY AI (OpenAI ham, Anthropic ham)
ISHLATILMAYDI. Sabab: shu loyihada avval call_light() orqali (LLM'ga) Meta
`actions` massivini hisoblashni ishonib topshirilgan edi, va ikki marta xato
chiqdi (1 ta lead 3 marta hisoblab "Leadlar: 3" deb chiqarilgan, mavjud
bo'lmagan "Xabar" o'ylab topilgan). Rasmiy, moliyaviy PDF hisobot uchun bu
xato darajasi qabul qilinishi mumkin emas -- shuning uchun bu yerda LLM
umuman chaqirilmaydi, faqat aniq Python arifmetikasi ishlatiladi. Bu ham
ARZONROQ (API chaqiruvi shart emas), ham ANIQROQ.
"""

import io
import re
import calendar
from datetime import date, datetime, timedelta

import meta_api
import budget_tracker

# Foydalanuvchi oylik PDF hisobot so'rayotganini ANIQ, LLM'siz (deterministik
# regex orqali) aniqlash uchun -- bu butun oqim (PDF yaratish, Telegram'ga
# hujjat sifatida yuborish) boshqa har qanday METRIC/ANALYSIS so'rovidan
# TUBDAN farq qiladi, shuning uchun classify_intent()ga ishonib o'tirmasdan,
# eng boshida to'g'ridan-to'g'ri tekshiriladi (api/index.py'da).
MONTHLY_REPORT_KEYWORDS = re.compile(
    r"oylik hisobot|bir oylik|oy uchun hisobot|oy bo'yicha hisobot|"
    r"oylik pdf|pdf.*hisobot|hisobot.*pdf|oylik report|oy hisoboti",
    re.IGNORECASE,
)

_UZ_MONTHS = {
    "yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6,
    "iyul": 7, "avgust": 8, "sentabr": 9, "sentyabr": 9, "oktabr": 10,
    "noyabr": 11, "dekabr": 12,
}


def is_monthly_report_request(user_text: str) -> bool:
    return bool(MONTHLY_REPORT_KEYWORDS.search(user_text or ""))


def resolve_monthly_period(user_text: str, today: date | None = None) -> tuple[str, str, str]:
    """Foydalanuvchi qaysi oy haqida so'raganini ANIQLAYDI -- LLM'siz, oddiy
    Python bilan (kalit so'z + oy nomi lug'ati orqali), rasmiy hisobot uchun
    sana chegarasi noto'g'ri aniqlanib qolmasligi uchun. Qaytaradi:
    `(since, until, period_label)` -- `since`/`until` YYYY-MM-DD formatida."""
    today = today or (datetime.utcnow() + timedelta(hours=5)).date()
    text_lower = (user_text or "").lower()

    if any(k in text_lower for k in ("o'tgan oy", "otgan oy", "oldingi oy")):
        year, month = today.year, today.month - 1
        if month == 0:
            month, year = 12, year - 1
        since = date(year, month, 1)
        until = date(year, month, calendar.monthrange(year, month)[1])
        return since.isoformat(), until.isoformat(), f"{since.strftime('%d.%m')}–{until.strftime('%d.%m.%Y')}"

    for name, month_num in _UZ_MONTHS.items():
        if name in text_lower:
            year = today.year
            if month_num > today.month:
                year -= 1  # aytilgan oy kelajakda chiqib qolmasligi uchun, o'tgan yildan olinadi
            since = date(year, month_num, 1)
            until = date(year, month_num, calendar.monthrange(year, month_num)[1])
            return since.isoformat(), until.isoformat(), f"{since.strftime('%d.%m')}–{until.strftime('%d.%m.%Y')}"

    # Standart: aniq oy aytilmagan bo'lsa ("bir oylik hisobot ber" kabi umumiy
    # so'rovda) -- joriy oy boshidan BUGUNGACHA.
    since = date(today.year, today.month, 1)
    until = today
    return since.isoformat(), until.isoformat(), f"{since.strftime('%d.%m')}–{until.strftime('%d.%m.%Y')} (joriy oy)"

# Meta insights `actions` massivida BITTA XIL voqea (masalan bitta lead) bir
# nechta turli action_type nomi bilan QAYTA-QAYTA chiqishi mumkin (masalan
# 'lead' VA 'onsite_conversion.lead_grouped' baravariga qiymat bilan
# ko'rinishi mumkin) -- shuning uchun ular HECH QACHON qo'shilmaydi, faqat
# ANIQ USTUVORLIK tartibida ro'yxatdagi BIRINCHI topilgani ishlatiladi.
LEAD_ACTION_PRIORITY = [
    "onsite_conversion.lead_grouped",
    "lead",
    "offsite_conversion.fb_pixel_lead",
]
MESSAGE_ACTION_PRIORITY = [
    "onsite_conversion.messaging_conversation_started_7d",
    "onsite_conversion.total_messaging_connection",
    "onsite_conversion.messaging_first_reply",
]


def _first_matching_action_value(actions, exact_priority, contains_keyword=None):
    """`actions` (Meta insights formatidagi ro'yxat) ichidan ANIQ ustuvorlik
    tartibidagi BIRINCHI mos action_type'ning qiymatini qaytaradi -- hech
    qachon bir nechta yozuvni qo'shib chiqarmaydi (double-count bug'ining
    oldini olish uchun ataylab shunday yozilgan)."""
    if not actions:
        return 0
    by_type = {}
    for a in actions:
        at = a.get("action_type", "")
        if at not in by_type:
            by_type[at] = a.get("value")
    for t in exact_priority:
        if t in by_type and by_type[t] is not None:
            try:
                return int(round(float(by_type[t])))
            except (TypeError, ValueError):
                continue
    if contains_keyword:
        for a in actions:
            at = str(a.get("action_type", "")).lower()
            if contains_keyword in at and a.get("value") is not None:
                try:
                    return int(round(float(a["value"])))
                except (TypeError, ValueError):
                    continue
    return 0


def _classify_direction(name: str, objective: str | None, leads: int, messages: int) -> str:
    """Kampaniyaning yo'nalishini (Lead yig'ish yoki Xabar/SMS) aniqlaydi --
    avval NOMdagi kalit so'zdan (odatda "AB | lead | ..." kabi nomlanadi),
    keyin Meta'ning `objective` maydonidan, oxirida haqiqiy natija turidan
    (qaysi turdan ko'proq kelgan bo'lsa)."""
    name_lower = (name or "").lower()
    if "lead" in name_lower:
        return "Lead"
    if any(k in name_lower for k in ("sms", "xabar", "messag")):
        return "Xabar"
    if objective:
        obj = objective.upper()
        if "LEAD" in obj:
            return "Lead"
        if "MESSAGE" in obj or "ENGAGEMENT" in obj:
            return "Xabar"
    if leads and leads >= messages:
        return "Lead"
    if messages:
        return "Xabar"
    return "Noma'lum"


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _campaign_metrics(row: dict, objective_by_name: dict) -> dict:
    name = row.get("campaign_name") or "(nomsiz)"
    spend = _safe_float(row.get("spend"))
    actions = row.get("actions") or []
    leads = _first_matching_action_value(actions, LEAD_ACTION_PRIORITY, "lead")
    messages = _first_matching_action_value(actions, MESSAGE_ACTION_PRIORITY, "messag")
    results = leads if leads >= messages else messages
    cpl = (spend / results) if results else None
    objective = objective_by_name.get(name)
    direction = _classify_direction(name, objective, leads, messages)
    return {
        "name": name,
        "direction": direction,
        "objective": objective or "-",
        "spend": spend,
        "leads": leads,
        "messages": messages,
        "results": results,
        "cpl": cpl,
        "impressions": int(_safe_float(row.get("impressions"))),
        "reach": int(_safe_float(row.get("reach"))),
        "frequency": _safe_float(row.get("frequency")),
    }


def _aggregate(campaigns: list[dict]) -> dict:
    spend = sum(c["spend"] for c in campaigns)
    leads = sum(c["leads"] for c in campaigns)
    messages = sum(c["messages"] for c in campaigns)
    results = leads + messages
    impressions = sum(c["impressions"] for c in campaigns)
    # ESLATMA: Reach kampaniyalar bo'yicha to'g'ridan-to'g'ri qo'shilgan --
    # bu TAXMINIY umumiy qamrov (haqiqiy account-darajasidagi reach'dan farq
    # qilishi mumkin, chunki turli kampaniyalar bir xil odamga ko'rinishi/
    # "overlap" bo'lishi mumkin -- Meta buni account darajasida deduplikatsiya
    # qiladi, lekin kampaniyalar yig'indisida bu hisobga olinmaydi).
    reach = sum(c["reach"] for c in campaigns)
    cpl = (spend / results) if results else None
    return {
        "spend": spend, "leads": leads, "messages": messages, "results": results,
        "cpl": cpl, "impressions": impressions, "reach": reach,
    }


def _daily_breakdown(since: str, until: str) -> list[dict]:
    try:
        rows = meta_api.get_insights(
            level="account",
            time_range={"since": since, "until": until},
            fields=["spend", "actions"],
            time_increment=1,
        )
    except meta_api.MetaAPIError:
        return []
    daily = []
    for row in rows:
        spend = _safe_float(row.get("spend"))
        actions = row.get("actions") or []
        leads = _first_matching_action_value(actions, LEAD_ACTION_PRIORITY, "lead")
        messages = _first_matching_action_value(actions, MESSAGE_ACTION_PRIORITY, "messag")
        results = leads if leads >= messages else messages
        cpl = (spend / results) if results else None
        daily.append({
            "date": row.get("date_start", "?"),
            "spend": spend,
            "results": results,
            "cpl": cpl,
        })
    daily.sort(key=lambda d: d["date"])
    return daily


def gather_monthly_report_data(since: str, until: str, period_label: str) -> dict:
    """Berilgan davr (since/until, YYYY-MM-DD) uchun barcha kerakli
    ma'lumotni yig'adi va deterministik hisoblaydi: har bir kampaniya
    natijasi, umumiy jamlanma, oldingi (bir xil uzunlikdagi) davr bilan
    solishtirish, kunlik jadval, va joriy byudjet holati. Hammasi HAQIQIY
    Meta API ma'lumotidan -- hech narsa o'ylab topilmaydi."""
    campaign_rows = meta_api.get_full_report(level="campaign", time_range={"since": since, "until": until})
    structure = meta_api.get_account_structure(active_only=False)
    objective_by_name = {c.get("name"): c.get("objective") for c in structure.get("campaigns", [])}

    campaigns = [_campaign_metrics(row, objective_by_name) for row in campaign_rows]
    campaigns.sort(key=lambda c: c["spend"], reverse=True)
    totals = _aggregate(campaigns)

    since_dt = datetime.strptime(since, "%Y-%m-%d").date()
    until_dt = datetime.strptime(until, "%Y-%m-%d").date()
    span_days = (until_dt - since_dt).days + 1
    prev_until_dt = since_dt - timedelta(days=1)
    prev_since_dt = prev_until_dt - timedelta(days=span_days - 1)

    prev_totals = None
    try:
        prev_rows = meta_api.get_full_report(
            level="campaign",
            time_range={"since": prev_since_dt.isoformat(), "until": prev_until_dt.isoformat()},
        )
        prev_campaigns = [_campaign_metrics(row, objective_by_name) for row in prev_rows]
        prev_totals = _aggregate(prev_campaigns)
    except meta_api.MetaAPIError:
        pass

    daily = _daily_breakdown(since, until)

    try:
        budget_status = budget_tracker.get_status()
    except Exception:
        budget_status = None

    return {
        "period_label": period_label,
        "since": since,
        "until": until,
        "campaigns": campaigns,
        "totals": totals,
        "prev_totals": prev_totals,
        "prev_period_label": f"{prev_since_dt.strftime('%d.%m')}–{prev_until_dt.strftime('%d.%m.%Y')}",
        "daily": daily,
        "budget_status": budget_status,
        "generated_at": datetime.utcnow() + timedelta(hours=5),  # O'zbekiston vaqti
    }


def _fmt_money(value) -> str:
    return f"${value:.2f}" if value is not None else "-"


def _fmt_int(value) -> str:
    return f"{int(value):,}".replace(",", " ")


def _pct_change(cur: float, prev: float) -> str:
    if not prev:
        return "-"
    change = (cur - prev) / prev * 100
    arrow = "▲" if change > 0 else ("▼" if change < 0 else "▬")
    return f"{arrow} {change:+.1f}%"


def render_monthly_report_pdf(data: dict) -> bytes:
    """`gather_monthly_report_data()` natijasidan tushunarli, ixcham PDF
    quradi (reportlab orqali, jadval ko'rinishida)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak

    def make_table(rows, col_widths, header=False, small=False):
        font_size = 8 if small else 9.5
        t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
        style = [
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
            ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        if header:
            style += [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E4053")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        t.setStyle(TableStyle(style))
        return t

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=1.4 * cm, bottomMargin=1.4 * cm, leftMargin=1.4 * cm, rightMargin=1.4 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleUZ", parent=styles["Title"], fontSize=18, spaceAfter=4)
    subtitle_style = ParagraphStyle("SubUZ", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#555555"))
    h2 = ParagraphStyle("H2UZ", parent=styles["Heading2"], fontSize=13, spaceBefore=16, spaceAfter=6, textColor=colors.HexColor("#2E4053"))

    elements = [
        Paragraph("OYLIK TARGET HISOBOTI", title_style),
        Paragraph(
            f"Davr: {data['period_label']}  |  Tayyorlandi: "
            f"{data['generated_at'].strftime('%d.%m.%Y %H:%M')} (O'zbekiston vaqti)",
            subtitle_style,
        ),
        Spacer(1, 10),
    ]

    # 1) Umumiy oy xulosasi
    t = data["totals"]
    elements.append(Paragraph("Umumiy oy xulosasi", h2))
    elements.append(make_table([
        ["Umumiy xarajat", _fmt_money(t["spend"])],
        ["Umumiy natija (lead + xabar)", str(t["results"])],
        ["   shundan Lead", str(t["leads"])],
        ["   shundan Xabar", str(t["messages"])],
        ["O'rtacha CPL", _fmt_money(t["cpl"])],
        ["Umumiy ko'rishlar (Impressions)", _fmt_int(t["impressions"])],
        ["Umumiy qamrov (Reach, taxminiy*)", _fmt_int(t["reach"])],
    ], col_widths=[9 * cm, 6 * cm]))

    # 2) Oldingi davr bilan solishtirish
    if data["prev_totals"]:
        pt = data["prev_totals"]
        elements.append(Paragraph(f"Oldingi davr bilan solishtirish ({data['prev_period_label']})", h2))
        elements.append(make_table([
            ["Ko'rsatkich", "Bu davr", "Oldingi davr", "O'zgarish"],
            ["Xarajat", _fmt_money(t["spend"]), _fmt_money(pt["spend"]), _pct_change(t["spend"], pt["spend"])],
            ["Natija", str(t["results"]), str(pt["results"]), _pct_change(t["results"], pt["results"])],
            [
                "CPL",
                _fmt_money(t["cpl"]),
                _fmt_money(pt["cpl"]),
                _pct_change(t["cpl"], pt["cpl"]) if (t["cpl"] and pt["cpl"]) else "-",
            ],
        ], col_widths=[4 * cm, 3.7 * cm, 3.7 * cm, 3.6 * cm], header=True))

    # 3) Byudjet monitoring
    if data["budget_status"]:
        b = data["budget_status"]
        elements.append(Paragraph("Byudjet monitoring", h2))
        budget_rows = [
            ["Joriy balans", _fmt_money(b.get("balance_usd"))],
            ["Kunlik o'rtacha xarajat (so'nggi 3 kun)", _fmt_money(b.get("daily_burn_usd"))],
        ]
        if b.get("days_remaining") is not None:
            budget_rows.append([
                "Taxminan yetadi",
                f"{b['days_remaining']} kunga (~{b['run_out_date']})",
            ])
        else:
            budget_rows.append(["Izoh", b.get("note", "-")])
        elements.append(make_table(budget_rows, col_widths=[9 * cm, 6 * cm]))

    # 4) Har bir target natijasi
    elements.append(Paragraph("Har bir target natijasi", h2))
    rows = [["Target nomi", "Yo'nalish", "Xarajat", "Natija", "CPL", "Ko'rishlar", "Qamrov"]]
    for c in data["campaigns"]:
        rows.append([
            c["name"], c["direction"], _fmt_money(c["spend"]), str(c["results"]),
            _fmt_money(c["cpl"]), _fmt_int(c["impressions"]), _fmt_int(c["reach"]),
        ])
    if len(rows) == 1:
        rows.append(["(shu davrda faol target topilmadi)", "-", "-", "-", "-", "-", "-"])
    elements.append(make_table(
        rows, col_widths=[5.2 * cm, 1.8 * cm, 2 * cm, 1.8 * cm, 1.8 * cm, 2.2 * cm, 2 * cm],
        header=True, small=True,
    ))

    # 5) Kunlik jadval
    if data["daily"]:
        elements.append(PageBreak())
        elements.append(Paragraph("Kunlik jadval", h2))
        daily_rows = [["Sana", "Xarajat", "Natija", "CPL"]]
        for d in data["daily"]:
            daily_rows.append([d["date"], _fmt_money(d["spend"]), str(d["results"]), _fmt_money(d["cpl"])])
        elements.append(make_table(daily_rows, col_widths=[3.5 * cm, 3.5 * cm, 3.5 * cm, 3.5 * cm], header=True))

    elements.append(Spacer(1, 14))
    elements.append(Paragraph(
        "* Qamrov (Reach) kampaniyalar bo'yicha qo'shib chiqilgan -- bir xil odam bir nechta "
        "kampaniyada ko'rgan bo'lishi mumkin, shuning uchun bu taxminiy umumiy son.",
        ParagraphStyle("FootUZ", parent=styles["Normal"], fontSize=7.5, textColor=colors.HexColor("#888888")),
    ))

    doc.build(elements)
    return buf.getvalue()
