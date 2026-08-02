"""
api/index.py — Vercel serverless muhitida ishlaydigan Target Master Telegram
bot (webhook rejimi).

MUHIM FARQ (telegram_bot.py'dan, u endi Vercel'da ISHLATILMAYDI, faqat
mahalliy/VPS uchun namuna sifatida qoladi):
  - `python-telegram-bot` kutubxonasi (long-polling, JobQueue) ISHLATILMAYDI —
    Vercel har so'rovga alohida qisqa muddatli funksiya ishga tushiradi,
    doimiy jarayon saqlab bo'lmaydi.
  - Telegram xabarlari WEBHOOK orqali keladi (Telegram -> POST /api/webhook).
  - "Har 4 soatda" / "har kuni" ishlaydigan fon vazifalari (budget_check,
    daily_analysis) endi Vercel Cron (yoki tashqi cron xizmati) tomonidan
    chaqiriladigan alohida endpoint'lar: GET /api/cron/daily, GET /api/cron/budget.
  - Holat (suhbat tarixi, oxirgi hisobot, byudjet balansi) endi mahalliy
    faylda emas, `kv_store.py` orqali tashqi KV/Redis'da saqlanadi.

BIR MARTALIK O'RNATISH (deploy qilingandan keyin):
    curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<vercel-domeningiz>/api/webhook"

KERAKLI ENV O'ZGARUVCHILAR (Vercel loyihasi -> Settings -> Environment Variables):
    TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, META_ACCESS_TOKEN, META_AD_ACCOUNT_ID,
    META_PAGE_ID (ixtiyoriy), CRON_SECRET,
    KV_REST_API_URL + KV_REST_API_TOKEN (Vercel KV ulaganda avtomatik qo'shiladi)
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

from flask import Flask, request, jsonify

sys.path.insert(0, str(Path(__file__).parent.parent))  # meta_api/orchestrator/... shu papkada

import anthropic
import meta_api
import orchestrator
import budget_tracker
import kv_store
import monthly_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("target-master-webhook")

BASE_DIR = Path(__file__).parent.parent
KNOWLEDGE_BASE = (BASE_DIR / "target_master_agent.md").read_text(encoding="utf-8")

MODEL = orchestrator.LIGHT_MODEL  # oddiy suhbat uchun arzon model yetarli
MAX_HISTORY_MESSAGES = 10

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
CRON_SECRET = os.environ.get("CRON_SECRET", "")

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Telegram Bot API bilan to'g'ridan-to'g'ri ishlash (kutubxonasiz, `requests`)
# ---------------------------------------------------------------------------

def tg_send(chat_id: int, text: str) -> None:
    """Uzun xabarni Telegram limitiga (4096 belgi) mos bo'laklarga bo'lib yuboradi.
    parse_mode ATAYLAB ishlatilmaydi — hisobot/Meta xato matnlarida tez-tez
    uchraydigan "_" kabi belgilar Markdown parserini buzadi."""
    import requests
    for i in range(0, len(text), 4000):
        chunk = text[i:i + 4000]
        try:
            requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": chunk}, timeout=20)
        except Exception:
            logger.exception("Telegramga xabar yuborishda xatolik")


def tg_send_status(chat_id: int, text: str) -> int | None:
    """Vazifa bajarilayotganini ko'rsatuvchi vaqtinchalik xabar yuboradi
    (masalan "⏳ Bajaryapman...") va Telegram'ning message_id'sini qaytaradi —
    ish tugagach shu xabarni `tg_delete()` bilan o'chirish uchun."""
    import requests
    try:
        r = requests.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=20)
        return (r.json().get("result") or {}).get("message_id")
    except Exception:
        logger.exception("Status xabar yuborishda xatolik")
        return None


def tg_delete(chat_id: int, message_id: int | None) -> None:
    """`tg_send_status()` bilan yuborilgan vaqtinchalik xabarni o'chiradi —
    xabar allaqachon yo'q bo'lsa ham (masalan foydalanuvchi o'zi o'chirgan
    bo'lsa) xato bermaydi, jim o'tkazib yuboriladi."""
    if not message_id:
        return
    import requests
    try:
        requests.post(f"{TELEGRAM_API}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id}, timeout=20)
    except Exception:
        pass  # xabar allaqachon o'chirilgan/topilmasa muammo emas


def tg_send_document(chat_id: int, filename: str, file_bytes: bytes, caption: str = "") -> bool:
    """Faylni (masalan oylik PDF hisobotni) Telegram'ga HUJJAT sifatida
    yuboradi (`sendDocument`, multipart/form-data). Oddiy `tg_send()`dan farqi
    -- bu yerda matn emas, binary fayl yuboriladi."""
    import requests
    try:
        r = requests.post(
            f"{TELEGRAM_API}/sendDocument",
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"document": (filename, file_bytes, "application/pdf")},
            timeout=55,
        )
        ok = bool(r.json().get("ok"))
        if not ok:
            logger.error("sendDocument xato qaytardi: %s", r.text[:500])
        return ok
    except Exception:
        logger.exception("Telegramga hujjat (PDF) yuborishda xatolik")
        return False


def _handle_monthly_report(chat_id: int, user_text: str) -> None:
    """Oylik PDF hisobot so'ralganda chaqiriladi (`monthly_report.
    is_monthly_report_request()` orqali ANIQLANADI -- classify_intent/
    Claude Sonnet zanjiriga UMUMAN kirmaydi, chunki bu butunlay boshqa oqim:
    hech qanday AI chaqirilmaydi, faqat HAQIQIY Meta ma'lumotidan
    deterministik hisoblab, PDF hujjat sifatida yuboriladi.

    MUHIM: aynan shu turdagi so'rov avval ANALYSIS sifatida aniqlanib,
    to'liq Targetolog/Marketolog Claude Sonnet zanjiriga tushib qolgan va
    Vercel'ning 60 soniyalik limitiga urilib, 504/timeout bergan edi (foyda-
    lanuvchi tomonidan Vercel loglari orqali ko'rsatilgan). Bu funksiya AYNAN
    o'sha muammoni butunlay chetlab o'tadi -- LLM chaqiruvi yo'q, shuning
    uchun tez va ishonchli."""
    status_id = tg_send_status(chat_id, "⏳ Oylik hisobotni tayyorlayapman (PDF)...")
    try:
        since, until, period_label = monthly_report.resolve_monthly_period(user_text)
        data = monthly_report.gather_monthly_report_data(since, until, period_label)
        pdf_bytes = monthly_report.render_monthly_report_pdf(data)
    except meta_api.MetaAPIError as e:
        tg_delete(chat_id, status_id)
        tg_send(chat_id, f"⚠️ Meta API'dan ma'lumot olishda xatolik: {e}")
        return
    except Exception as e:
        logger.exception("Oylik hisobot yaratishda xatolik")
        tg_delete(chat_id, status_id)
        tg_send(
            chat_id,
            f"⚠️ Oylik hisobotni tayyorlashda kutilmagan xatolik: {e}\n\n"
            "Qaytadan urinib ko'ring.",
        )
        return

    filename = f"oylik_hisobot_{since}_{until}.pdf"
    caption = f"📊 Oylik target hisoboti: {period_label}"
    sent = tg_send_document(chat_id, filename, pdf_bytes, caption=caption)
    tg_delete(chat_id, status_id)
    if not sent:
        tg_send(chat_id, "⚠️ PDF hujjatni yuborishda xatolik yuz berdi. Qaytadan urinib ko'ring.")


# ---------------------------------------------------------------------------
# Suhbat tarixi / oxirgi hisobot — endi KV'da (chat_id bo'yicha)
# ---------------------------------------------------------------------------

def _conv_key(chat_id: int) -> str:
    return f"conv:{chat_id}"


def _report_key(chat_id: int) -> str:
    return f"last_report:{chat_id}"


def get_history(chat_id: int) -> list[dict]:
    return kv_store.get_json(_conv_key(chat_id), default=[])


def save_history(chat_id: int, history: list[dict]) -> None:
    kv_store.set_json(_conv_key(chat_id), history[-MAX_HISTORY_MESSAGES:])


def get_last_report(chat_id: int) -> str:
    return kv_store.get_json(_report_key(chat_id), default=None) or (
        "Hali tahlil ishga tushirilmagan. /analyze buyrug'ini yuboring."
    )


def save_last_report(chat_id: int, text: str) -> None:
    kv_store.set_json(_report_key(chat_id), text)


# ---------------------------------------------------------------------------
# Buyruqlar
# ---------------------------------------------------------------------------

WELCOME_TEXT = (
    "👋 Salom! Men — Targetolog.\n\n"
    "Men bilan oddiy odam bilan gaplashgandek yozavering — masalan:\n"
    "\"IELTS kursi uchun yangi target yoq, kunlik $20, Toshkent\"\n"
    "\"AB | Traffic | IG reklamani to'xtat\"\n"
    "\"hisobim qanday ketyapti\"\n"
    "Tushunaman va o'zim bajaraman — buyruq shart emas.\n\n"
    "Narx keskin ko'tarilsa yoki target yaxshi natija bermasa, o'zim ko'rib "
    "byudjetni kamaytiraman yoki auditoriyani o'zgartirib, CPL'ni tushirishga "
    "harakat qilaman. Qo'limdan to'liq kelmasa, shunday deb ochiq aytaman va "
    "tavsiya beraman — hech qachon \"bajardim\" deb yolg'on aytmayman.\n\n"
    "Qisqa buyruqlar ham bor, xohlasangiz:\n"
    "📊 /analyze — hisobni to'liq tahlil qilaman\n"
    "📋 /status — oxirgi hisobotni ko'rsataman\n"
    "⏸ /pause <ad_id>  ▶️ /resume <ad_id>\n"
    "🔄 /reset — suhbatni tozalayman\n\n"
    "💰 Byudjet haqida yozsangiz (\"bugun 500$ tushdi\"), kuzatib boraman.\n"
    "🔁 Har kuni o'zim tekshirib turaman — diqqatga loyiq narsa bo'lsa, o'zim yozaman."
)


def handle_command(chat_id: int, cmd: str, args: list[str]) -> None:
    if cmd == "/start":
        kv_store.set_json(_conv_key(chat_id), [])
        budget_tracker.set_notify_chat_id(chat_id)
        tg_send(chat_id, WELCOME_TEXT)
        return

    if cmd == "/reset":
        kv_store.set_json(_conv_key(chat_id), [])
        tg_send(chat_id, "🔄 Suhbat tarixi tozalandi.")
        return

    if cmd == "/status":
        tg_send(chat_id, get_last_report(chat_id))
        return

    if cmd == "/analyze":
        status_id = tg_send_status(chat_id, "⏳ Bajaryapman... (hisobni tahlil qilyapman)")
        try:
            report = orchestrator.run_analysis_cycle(dry_run=False)
        except Exception as e:
            logger.exception("Tahlil xatosi")
            report = f"⚠️ Tahlil vaqtida xatolik: {e}"
        tg_delete(chat_id, status_id)
        save_last_report(chat_id, report)
        tg_send(chat_id, report)
        return

    if cmd == "/pause":
        if not args:
            tg_send(chat_id, "Foydalanish: /pause <ad_id>")
            return
        try:
            meta_api.pause_object(args[0])
            tg_send(chat_id, f"⏸ {args[0]} to'xtatildi.")
        except meta_api.MetaAPIError as e:
            tg_send(chat_id, f"⚠️ Xatolik: {e}")
        return

    if cmd == "/resume":
        if not args:
            tg_send(chat_id, "Foydalanish: /resume <ad_id>")
            return
        try:
            meta_api.activate_object(args[0])
            tg_send(chat_id, f"▶️ {args[0]} ishga tushirildi.")
        except meta_api.MetaAPIError as e:
            tg_send(chat_id, f"⚠️ Xatolik: {e}")
        return

    tg_send(chat_id, "Noma'lum buyruq. /start yozib, mavjud buyruqlarni ko'ring.")


def _self_base_url() -> str:
    """Joriy Vercel deploy manzilini aniqlaydi (fon so'rovni O'ZIMIZGA
    yuborish uchun kerak). Vercel `VERCEL_URL` env o'zgaruvchisini avtomatik
    beradi (protokolsiz, masalan "unduurv-bolimi-bot.vercel.app"); u bo'lmasa
    (masalan mahalliy test) ma'lum production domenga tushamiz."""
    host = os.environ.get("VERCEL_URL") or "unduurv-bolimi-bot.vercel.app"
    if not host.startswith("http"):
        host = f"https://{host}"
    return host


def _trigger_async_processing(payload: dict) -> tuple[bool, str]:
    """`/api/process-action`ga ICHKI so'rov yuboradi va JAVOBNI ATAYLAB
    KUTMAYDI (juda qisqa timeout).

    NEGA SHUNDAY: Vercel har bir kiruvchi so'rovni qabul qilgach, uni to'liq
    qayta ishlaydi -- chaqiruvchi javobni kutayaptimi yo'qmi, bunga bog'liq
    emas. Shuning uchun bu yerdan qisqa (0.5s) timeout bilan so'rov yuborib,
    javobni kutmasdan darhol qaytish xavfsiz: `/api/process-action` YANGI,
    alohida Vercel funksiya chaqiruvi sifatida ishga tushadi va o'zining
    TO'LIQ 60 soniyalik vaqtiga ega bo'ladi -- joriy webhook so'rovi esa
    Telegram'ga DARHOL 200 OK qaytarib, hech qachon Vercel'ning
    FUNCTION_INVOCATION_TIMEOUT xatosiga urilib qolmaydi.

    Qaytaradi: `(muvaffaqiyatmi, sabab)` -- `sabab` diagnostika uchun (agar
    muvaffaqiyatsiz bo'lsa, foydalanuvchiga ham ko'rsatiladi -- Vercel
    dashboard'ga kirmasdan to'g'ridan-to'g'ri Telegram'da nima xato
    bo'lganini ko'rish uchun)."""
    if not CRON_SECRET:
        reason = "CRON_SECRET Vercel'da sozlanmagan"
        logger.error(reason)
        return False, reason

    import requests
    url = f"{_self_base_url()}/api/process-action"
    headers = {"Authorization": f"Bearer {CRON_SECRET}"}
    # Agar Vercel loyihasida "Deployment Protection" (Vercel Authentication)
    # yoqilgan bo'lsa, HAR BIR so'rov (hatto bizning o'z ichki so'rovimiz
    # ham) Vercel'ning o'zi tomonidan 401 bilan rad etiladi -- CRON_SECRET
    # bunga ta'sir qilmaydi, chunki bu tekshiruv bizning Flask kodimizga
    # yetib kelishidan OLDIN, Vercel'ning "edge" darajasida sodir bo'ladi.
    # Buni chetlab o'tish uchun Vercel'da "Protection Bypass for Automation"
    # yoqilsa, u avtomatik `VERCEL_AUTOMATION_BYPASS_SECRET` degan environment
    # variable yaratadi -- shuni maxsus header sifatida qo'shsak, Vercel
    # so'rovni o'tkazib yuboradi.
    bypass_secret = os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET")
    if bypass_secret:
        headers["x-vercel-protection-bypass"] = bypass_secret
    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=0.5,
        )
        if 200 <= resp.status_code < 300:
            return True, "ok"
        reason = f"ichki so'rov {url} manzilidan {resp.status_code} qaytardi: {resp.text[:200]!r}"
        logger.error("Fon so'rovi kutilmagan status bilan qaytdi: %s", reason)
        return False, reason
    except requests.exceptions.Timeout:
        # KUTILGAN holat: so'rov haqiqatan yuborildi, biz shunchaki javobni
        # kutmadik -- fon ishga tushirish muvaffaqiyatli hisoblanadi.
        return True, "ok (timeout, kutilgan)"
    except requests.exceptions.RequestException as e:
        reason = f"{url} manzilga ulanib bo'lmadi: {type(e).__name__}: {e}"
        logger.exception("Fon so'rovini yuborib bo'lmadi")
        return False, reason


def handle_free_text(chat_id: int, user_text: str) -> None:
    history = get_history(chat_id)
    budget_tracker.set_notify_chat_id(chat_id)

    # Oylik PDF hisobot -- classify_intent/Claude Sonnet zanjiridan OLDIN,
    # deterministik kalit so'z orqali aniqlanadi (yuqoridagi
    # `_handle_monthly_report()` docstringiga qarang -- sabab: bu so'rov
    # avval ANALYSIS deb aniqlanib, og'ir Sonnet zanjiriga tushib, 60
    # soniyalik Vercel limitiga urilib timeout bergan edi).
    if monthly_report.is_monthly_report_request(user_text):
        _handle_monthly_report(chat_id, user_text)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": "[Oylik PDF hisobot yuborildi]"})
        save_history(chat_id, history)
        return

    # Ish jarayonini ko'rsatuvchi vaqtinchalik xabar — foydalanuvchi bot
    # "osilib qolganmi yoki ishlayaptimi" bilmay qolmasligi uchun.
    status_id = tg_send_status(chat_id, "⏳ Bajaryapman...")

    try:
        verdict, history_text = orchestrator.classify_intent(user_text, history)
    except Exception as e:
        logger.exception("classify_intent xatosi")
        tg_delete(chat_id, status_id)
        tg_send(chat_id, f"⚠️ Xabarni tushunishda xatolik: {e}\n\nQaytadan urinib ko'ring.")
        return

    if orchestrator.is_heavy_intent(verdict):
        # OG'IR YO'L (ACTION/ANALYSIS): Meta API + Claude Sonnet zanjiri bir
        # necha o'n soniya cho'zilishi mumkin -- buni HOZIRGI so'rovda EMAS,
        # `/api/process-action` fon so'roviga uzatishga urinamiz (yuqoridagi
        # izohga qarang). Foydalanuvchiga darhol ishonch xabari beriladi,
        # natija esa fon ishi tugagach alohida xabar sifatida keladi.
        tg_delete(chat_id, status_id)
        history.append({"role": "user", "content": user_text})
        save_history(chat_id, history)
        dispatched, reason = _trigger_async_processing({
            "chat_id": chat_id,
            "user_text": user_text,
            "history_text": history_text,
            "verdict": verdict,
        })
        if dispatched:
            tg_send(
                chat_id,
                "⏳ Qabul qildim, ishlab chiqyapman — tayyor bo'lganda o'zim yozaman "
                "(bir necha o'n soniya ketishi mumkin).",
            )
            return

        # MUHIM: fon so'rovi ishga tushmadi -- bu holatda AVVALGI (sinxron)
        # usulga qaytamiz, hech qachon foydalanuvchini JAVOBSIZ qoldirmaslik
        # uchun. Bu Vercel'ning 60 soniyalik limitiga urilib qolish xavfini
        # qaytaradi (murakkab buyruqlarda), lekin "umuman javob kelmaslik"dan
        # ancha yaxshi -- va aksariyat holatda (oddiyroq buyruqlar) baribir
        # vaqtida tugaydi. Sababni ('reason') ATAYLAB Telegram'ga ham
        # chiqaramiz -- shunda foydalanuvchi Vercel dashboard/loglarga
        # kirmasdan, to'g'ridan-to'g'ri shu yerdan nima xato bo'lganini
        # ko'rib, kerak bo'lsa dasturchiga (yoki bizga) ko'rsatishi mumkin.
        logger.warning("Fon so'rov ishlamadi (%s) -- %s buyrug'i sinxron rejimda bajarilyapti", reason, verdict)
        tg_send(chat_id, f"⏳ Fon rejimi hozircha ishlamadi ({reason}), shu yerning o'zida bajarayapman...")
        try:
            command_result = orchestrator.execute_intent(verdict, user_text, history_text, chat_id)
        except Exception as e:
            logger.exception("execute_intent xatosi (sinxron fallback)")
            tg_send(
                chat_id,
                f"⚠️ Buyruqni bajarishda kutilmagan xatolik yuz berdi: {e}\n\n"
                "Qaytadan urinib ko'ring yoki aniqroq yozing.",
            )
            return
        if command_result is None:
            command_result = "Tushunmadim, aniqroq yozib qayta yuboring."
        history.append({"role": "assistant", "content": command_result})
        save_history(chat_id, history)
        save_last_report(chat_id, command_result)
        tg_send(chat_id, command_result)
        return

    # YENGIL YO'L (BUDGET / METRIC / GENERAL) — bitta arzon model chaqiruvi,
    # 60 soniya ichiga bemalol sig'adi, shuning uchun shu so'rov ichida
    # darhol bajaramiz.
    try:
        command_result = orchestrator.execute_intent(verdict, user_text, history_text, chat_id)
    except Exception as e:
        logger.exception("execute_intent xatosi")
        tg_delete(chat_id, status_id)
        tg_send(
            chat_id,
            f"⚠️ Buyruqni bajarishda kutilmagan xatolik yuz berdi: {e}\n\n"
            "Qaytadan urinib ko'ring yoki aniqroq yozing.",
        )
        return

    if command_result is not None:
        tg_delete(chat_id, status_id)
        save_last_report(chat_id, command_result)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": command_result})
        save_history(chat_id, history)
        tg_send(chat_id, command_result)
        return

    # Oddiy maslahat/Q&A rejimi (hisobga tegilmaydi) — GENERAL
    history.append({"role": "user", "content": user_text})
    try:
        answer = orchestrator.call_light_chat(KNOWLEDGE_BASE, history, max_tokens=1000)
    except Exception as e:
        logger.exception("Yengil model xatosi (GENERAL suhbat)")
        answer = f"⚠️ Xatolik yuz berdi: {e}"

    tg_delete(chat_id, status_id)
    history.append({"role": "assistant", "content": answer})
    save_history(chat_id, history)
    tg_send(chat_id, answer)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/api/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message")
    if not message or "text" not in message:
        return jsonify({"ok": True})  # boshqa turdagi update (masalan rasm) — e'tiborsiz qoldiriladi

    chat_id = message["chat"]["id"]
    text = message["text"].strip()

    try:
        if text.startswith("/"):
            parts = text.split()
            cmd = parts[0].split("@")[0]  # /start@BotName -> /start
            handle_command(chat_id, cmd, parts[1:])
        else:
            handle_free_text(chat_id, text)
    except Exception:
        logger.exception("Webhook ishlov berishda kutilmagan xatolik")
        tg_send(chat_id, "⚠️ Kutilmagan ichki xatolik yuz berdi. Qaytadan urinib ko'ring.")

    return jsonify({"ok": True})


@app.route("/api/process-action", methods=["POST"])
def process_action():
    """OG'IR (ACTION/ANALYSIS) buyruqlarni haqiqiy bajaradigan FON endpoint'i.
    `handle_free_text()` bu yerga `_trigger_async_processing()` orqali,
    javobni kutmasdan (fire-and-forget) murojaat qiladi -- shuning uchun bu
    chaqiruv YANGI, alohida Vercel funksiya invokatsiyasi sifatida ishga
    tushadi va o'ZINING to'liq 60 soniyalik `maxDuration`iga ega bo'ladi.

    Xavfsizlik: faqat `CRON_SECRET` bilan (bizning o'z ichki so'rovimiz)
    chaqirilishi mumkin -- tashqaridan tasodifiy/qasddan chaqirilishning
    oldini oladi."""
    auth = request.headers.get("Authorization", "")
    if not CRON_SECRET or auth != f"Bearer {CRON_SECRET}":
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    chat_id = data.get("chat_id")
    user_text = data.get("user_text")
    history_text = data.get("history_text", "")
    verdict = data.get("verdict", "")
    if chat_id is None or not user_text:
        return jsonify({"ok": False, "error": "bad payload"}), 400

    try:
        result = orchestrator.execute_intent(verdict, user_text, history_text, chat_id)
    except Exception as e:
        logger.exception("Fon ishida xatolik (process_action)")
        tg_send(
            chat_id,
            f"⚠️ Fon ishida kutilmagan xatolik yuz berdi: {e}\n\nQaytadan urinib ko'ring.",
        )
        # 200 qaytaramiz -- Telegram/webhook allaqachon o'z javobini bergan,
        # bu faqat bizning ICHKI fon so'rovimiz, uni qayta urinishga hojat yo'q.
        return jsonify({"ok": False}), 200

    if result is None:
        result = "Tushunmadim, aniqroq yozib qayta yuboring."

    history = get_history(chat_id)
    history.append({"role": "assistant", "content": result})
    save_history(chat_id, history)
    save_last_report(chat_id, result)
    tg_send(chat_id, result)
    return jsonify({"ok": True})


def _cron_authorized() -> bool:
    """Vercel Cron so'rovlari avtomatik `Authorization: Bearer <CRON_SECRET>`
    header'i bilan keladi. Tashqi cron xizmati (masalan cron-job.org) uchun
    `?secret=...` query parametri ham qabul qilinadi."""
    if not CRON_SECRET:
        return False
    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {CRON_SECRET}":
        return True
    return request.args.get("secret") == CRON_SECRET


def _daily_report_targets() -> list[int]:
    """Kunlik hisobot qayerlarga yuborilishini aniqlaydi:
    - Agar `TELEGRAM_AGENTS_GROUP_ID` va/yoki `TELEGRAM_REPORT_GROUP_ID` env
      o'zgaruvchilari o'rnatilgan bo'lsa — hisobot shu guruh(lar)ga yuboriladi
      (bittasi "agentlar" guruhi, bittasi toza "hisobot" guruhi — bir xil
      matn ikkalasiga ham boradi).
    - Aks holda, oxirgi /start bosgan shaxsiy chat'ga (eski, oddiy) rejim."""
    targets: list[int] = []
    for env_name in ("TELEGRAM_AGENTS_GROUP_ID", "TELEGRAM_REPORT_GROUP_ID"):
        raw = os.environ.get(env_name)
        if raw:
            try:
                targets.append(int(raw))
            except ValueError:
                logger.warning("%s noto'g'ri formatda: %r", env_name, raw)
    if targets:
        return targets
    chat_id = budget_tracker.get_notify_chat_id()
    return [chat_id] if chat_id is not None else []


def _notify_cron_failure(cron_label: str, targets: list[int], error: Exception) -> None:
    """MUHIM (bug fix): avvalgi versiyada cron endpoint'larida xatolik
    chiqsa, faqat server logiga yozilardi (`logger.exception`) va HTTP
    500 qaytarilardi -- lekin bu ikkalasi ham FOYDALANUVCHIGA KO'RINMAYDI
    (Vercel Cron/cron-job.org javobini hech kim o'qib o'tirmaydi). Natijada
    foydalanuvchi kunlik hisobot kelmay qolganini payqamaguncha, bot
    "sukut saqlab" qo'yardi -- xuddi hech narsa so'ralmagandek. Endi har
    qanday cron xatoligida ham guruhga QISQA ogohlantirish yuboriladi,
    shuning uchun "hisobot/tekshiruv kelmadi, lekin nega ekani noma'lum"
    degan holat butunlay yo'qoladi -- kamida xatolik borligi ko'rinadi."""
    if not targets:
        return
    text = f"⚠️ {cron_label} ishlamadi (texnik xatolik): {error}\n\nKeyingi urinishda avtomatik qayta tekshiriladi."
    for cid in targets:
        try:
            tg_send(cid, text)
        except Exception:
            logger.exception("Cron xatoligi haqida ham xabar yuborib bo'lmadi (%s)", cron_label)


@app.route("/api/cron/daily", methods=["GET"])
def cron_daily():
    if not _cron_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    targets = _daily_report_targets()
    if not targets:
        return jsonify({
            "ok": True,
            "note": "Hisobot yuboriladigan chat yo'q — TELEGRAM_AGENTS_GROUP_ID/"
                    "TELEGRAM_REPORT_GROUP_ID sozlanmagan va hech kim /start bosmagan.",
        })

    try:
        # Kechagi holat bilan solishtirish `orchestrator.gather_data()` ichida
        # avtomatik amalga oshadi (KV'da saqlangan oldingi kun snapshoti orqali).
        report = orchestrator.run_daily_cron_report(dry_run=False)
    except Exception as e:
        logger.exception("Kunlik avtomatik tahlil xatosi")
        _notify_cron_failure("Kunlik avtomatik tahlil (/api/cron/daily)", targets, e)
        return jsonify({"ok": False, "error": "daily analysis failed"}), 500

    if report is None:
        return jsonify({"ok": True, "sent": False, "note": "diqqatga loyiq narsa yo'q"})

    text = "🔁 Kunlik tahlil:\n\n" + report
    for cid in targets:
        save_last_report(cid, report)
        tg_send(cid, text)
    return jsonify({"ok": True, "sent": True, "targets": len(targets)})


@app.route("/api/cron/watch", methods=["GET"])
def cron_watch():
    """TEZ-TEZ ishlaydigan "kuzatuv" endpoint'i (masalan har 30-60 daqiqada,
    tashqi cron xizmati -- cron-job.org -- orqali chaqiriladi, chunki Vercel
    Hobby'ning o'z cron'i kuniga faqat 1 marta ishlaydi).

    `/api/cron/daily` bilan BIR XIL tahlil+avtomatik-tuzatish tsiklini
    ishga tushiradi (Targetolog hisobni ko'radi, kerak bo'lsa pause/resume/
    byudjet o'zgartirish kabi amallarni O'ZI bajaradi) -- farqi shundaki,
    bu tez-tez chaqiriladi, shuning uchun muammo yuzaga kelganda soatlab
    emas, daqiqalar ichida aniqlanadi va (agar avtomatik tuzatib bo'ladigan
    bo'lsa) tuzatiladi. Har doimgidek, faqat DIQQATGA LOYIQ narsa bo'lsa
    (o'zgarish/xato/qo'lda ko'rib chiqish kerak) xabar yuboriladi -- hammasi
    joyida bo'lsa jim turadi, ortiqcha xabar bilan bezovta qilmaydi.

    ESLATMA (xarajat haqida): har chaqiruv Meta API'dan o'qish + kamida bitta
    Claude Sonnet chaqiruvini talab qiladi. Juda tez-tez (masalan har 1-5
    daqiqada) chaqirish keraksiz xarajatga olib kelishi mumkin -- 30-60
    daqiqalik oraliq odatda yetarli, chunki reklama natijalari daqiqama-daqiqa
    keskin o'zgarmaydi."""
    if not _cron_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    targets = _daily_report_targets()
    if not targets:
        return jsonify({
            "ok": True,
            "note": "Hisobot yuboriladigan chat yo'q — TELEGRAM_AGENTS_GROUP_ID/"
                    "TELEGRAM_REPORT_GROUP_ID sozlanmagan va hech kim /start bosmagan.",
        })

    try:
        report = orchestrator.run_daily_cron_report(dry_run=False)
    except Exception as e:
        logger.exception("Kuzatuv tsikli xatosi")
        _notify_cron_failure("Kuzatuv tsikli (/api/cron/watch)", targets, e)
        return jsonify({"ok": False, "error": "watch analysis failed"}), 500

    if report is None:
        return jsonify({"ok": True, "sent": False, "note": "diqqatga loyiq narsa yo'q"})

    text = "👀 Kuzatuv natijasi:\n\n" + report
    for cid in targets:
        save_last_report(cid, report)
        tg_send(cid, text)
    return jsonify({"ok": True, "sent": True, "targets": len(targets)})


@app.route("/api/cron/admin-report", methods=["GET"])
def cron_admin_report():
    """Har kuni belgilangan vaqtda (tavsiya: 09:00, O'zbekiston vaqti --
    cron-job.org'da 04:00 UTC qilib sozlang) qat'iy "ADMIN TARGET HISOBOTI"
    formatidagi qisqa hisobot yuboradi (`orchestrator.build_admin_report`).

    MUHIM FARQ `/api/cron/daily`/`/api/cron/watch`dan: bular to'liq
    audit+avtomatik-tuzatish tsiklini (Claude Sonnet orqali, pulli) ishga
    tushiradi; bu endpoint esa FAQAT bugungi asosiy ko'rsatkichlarni
    (xarajat/lead/CPL/CTR/CPM va h.k.) OpenAI orqali hisoblab, foydalanuvchi
    so'ragan qat'iy formatda yuboradi -- hech qanday amal (pause/resume/
    byudjet o'zgartirish) BAJARMAYDI, faqat hisobot."""
    if not _cron_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    targets = _daily_report_targets()
    if not targets:
        return jsonify({
            "ok": True,
            "note": "Hisobot yuboriladigan chat yo'q -- TELEGRAM_AGENTS_GROUP_ID/"
                    "TELEGRAM_REPORT_GROUP_ID sozlanmagan va hech kim /start bosmagan.",
        })

    tashkent_now = datetime.utcnow() + timedelta(hours=5)  # O'zbekiston vaqti (UTC+5)
    period_label = tashkent_now.strftime("%d.%m.%Y")
    hisobot_vaqti = tashkent_now.strftime("%H:%M")

    try:
        report = orchestrator.build_admin_report(
            period_label,
            hisobot_vaqti,
            "Ertalabki holat va bugungi ish rejasi",
            insight_kwargs={"date_preset": "today"},
        )
    except Exception as e:
        logger.exception("Admin hisobot xatosi")
        _notify_cron_failure("Kunlik ADMIN TARGET HISOBOTI (/api/cron/admin-report)", targets, e)
        return jsonify({"ok": False, "error": str(e)}), 500

    for cid in targets:
        save_last_report(cid, report)
        tg_send(cid, report)
    return jsonify({"ok": True, "sent": True, "targets": len(targets)})


@app.route("/api/cron/budget", methods=["GET"])
def cron_budget():
    if not _cron_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        alert = budget_tracker.check_and_alert()
    except Exception as e:
        logger.exception("Byudjet tekshiruvida xatolik")
        _notify_cron_failure("Byudjet tekshiruvi (/api/cron/budget)", _daily_report_targets(), e)
        return jsonify({"ok": False, "error": "budget check failed"}), 500

    if alert:
        tg_send(alert["chat_id"], alert["message"])
        return jsonify({"ok": True, "sent": True})
    return jsonify({"ok": True, "sent": False})


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "telegram_token_set": bool(TELEGRAM_TOKEN),
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "meta_token_set": bool(os.environ.get("META_ACCESS_TOKEN")),
        "kv_configured": bool(os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")),
        "cron_secret_set": bool(CRON_SECRET),
    })
