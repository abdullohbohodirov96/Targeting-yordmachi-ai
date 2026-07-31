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

from flask import Flask, request, jsonify

sys.path.insert(0, str(Path(__file__).parent.parent))  # meta_api/orchestrator/... shu papkada

import anthropic
import meta_api
import orchestrator
import budget_tracker
import kv_store

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
    "👋 Salom! Men — Target Master.\n\n"
    "💬 Savol bering — Meta Ads bo'yicha maslahat beraman.\n"
    "📊 /analyze — hisobingizni tahlil qilib, tavsiyalar beraman "
    "(Targetolog + Marketolog agentlar ishlaydi).\n"
    "⏸ /pause <ad_id> — reklamani to'xtatish\n"
    "▶️ /resume <ad_id> — reklamani qayta ishga tushirish\n"
    "📋 /status — oxirgi tahlil hisobotini ko'rish\n"
    "💰 \"bugun 500$ tushdi\" / \"qancha qoldi?\" — byudjet balansini kuzataman, "
    "chegaradan pastga tushsa o'zim xabar beraman.\n"
    "🔁 Har kuni avtomatik tahlil qilib, kerak bo'lmagan narsalarni o'zim "
    "tuzataman/arxivlayman — faqat DIQQATGA LOYIQ narsa bo'lsa yozaman.\n"
    "🔄 /reset — suhbat tarixini tozalash"
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
        tg_send(chat_id, "⏳ Tahlil boshlandi — Targetolog va Marketolog ishlamoqda...")
        try:
            report = orchestrator.run_analysis_cycle(dry_run=False)
        except Exception as e:
            logger.exception("Tahlil xatosi")
            report = f"⚠️ Tahlil vaqtida xatolik: {e}"
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


def handle_free_text(chat_id: int, user_text: str) -> None:
    history = get_history(chat_id)
    budget_tracker.set_notify_chat_id(chat_id)

    try:
        command_result = orchestrator.handle_chat_command(
            user_text, recent_history=history, chat_id=chat_id
        )
    except Exception as e:
        logger.exception("handle_chat_command xatosi")
        tg_send(
            chat_id,
            f"⚠️ Buyruqni bajarishda kutilmagan xatolik yuz berdi: {e}\n\n"
            "Qaytadan urinib ko'ring yoki aniqroq yozing.",
        )
        return

    if command_result is not None:
        save_last_report(chat_id, command_result)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": command_result})
        save_history(chat_id, history)
        tg_send(chat_id, command_result)
        return

    # Oddiy maslahat/Q&A rejimi (hisobga tegilmaydi)
    history.append({"role": "user", "content": user_text})
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=[{"type": "text", "text": KNOWLEDGE_BASE, "cache_control": {"type": "ephemeral"}}],
            messages=history,
        )
        answer = response.content[0].text
    except Exception as e:
        logger.exception("Claude API xatosi")
        answer = f"⚠️ Xatolik yuz berdi: {e}"

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


@app.route("/api/cron/daily", methods=["GET"])
def cron_daily():
    if not _cron_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    chat_id = budget_tracker.get_notify_chat_id()
    if chat_id is None:
        return jsonify({"ok": True, "note": "notify_chat_id hali yo'q — hech kim /start bosmagan"})

    try:
        report = orchestrator.run_daily_cron_report(dry_run=False)
    except Exception:
        logger.exception("Kunlik avtomatik tahlil xatosi")
        return jsonify({"ok": False, "error": "daily analysis failed"}), 500

    if report is None:
        return jsonify({"ok": True, "sent": False, "note": "diqqatga loyiq narsa yo'q"})

    save_last_report(chat_id, report)
    tg_send(chat_id, "🔁 Kunlik avtomatik tahlil:\n\n" + report)
    return jsonify({"ok": True, "sent": True})


@app.route("/api/cron/budget", methods=["GET"])
def cron_budget():
    if not _cron_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        alert = budget_tracker.check_and_alert()
    except Exception:
        logger.exception("Byudjet tekshiruvida xatolik")
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
