"""
Target Master — Telegram bot (MVP)

Ikki rejimda ishlaydi:
  1. Erkin suhbat — foydalanuvchi savol beradi, Targetolog agent (bilim bazasi bilan)
     javob beradi (real hisobga tegmaydi, faqat maslahat).
  2. Buyruqlar — haqiqiy Meta Ads hisobi bilan ishlaydigan orchestrator'ni ishga
     tushiradi (/analyze, /pause, /resume, /status).

O'RNATISH:
    pip install python-telegram-bot anthropic requests

KERAKLI ENV O'ZGARUVCHILAR:
    TELEGRAM_BOT_TOKEN
    ANTHROPIC_API_KEY
    META_ACCESS_TOKEN        (faqat /analyze, /pause, /resume uchun kerak)
    META_AD_ACCOUNT_ID       (masalan: act_1234567890)

ISHGA TUSHIRISH:
    python telegram_bot.py
"""

import os
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
import anthropic

import meta_api
import orchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("target-master-bot")

BASE_DIR = Path(__file__).parent
KNOWLEDGE_BASE = (BASE_DIR / "target_master_agent.md").read_text(encoding="utf-8")

MODEL = "claude-sonnet-4-5"
MAX_HISTORY_MESSAGES = 20

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

conversations: dict[int, list[dict]] = {}
last_report: str = "Hali tahlil ishga tushirilmagan. /analyze buyrug'ini yuboring."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversations[update.effective_chat.id] = []
    await update.message.reply_text(
        "👋 Salom! Men — Target Master.\n\n"
        "💬 Savol bering — Meta Ads bo'yicha maslahat beraman.\n"
        "📊 /analyze — hisobingizni tahlil qilib, tavsiyalar beraman "
        "(Targetolog + Marketolog agentlar ishlaydi).\n"
        "⏸ /pause <ad_id> — reklamani to'xtatish\n"
        "▶️ /resume <ad_id> — reklamani qayta ishga tushirish\n"
        "📋 /status — oxirgi tahlil hisobotini ko'rish\n"
        "🔄 /reset — suhbat tarixini tozalash"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversations[update.effective_chat.id] = []
    await update.message.reply_text("🔄 Suhbat tarixi tozalandi.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(last_report, parse_mode="Markdown")


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_report
    await update.message.reply_text("⏳ Tahlil boshlandi — Targetolog va Marketolog ishlamoqda...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        last_report = orchestrator.run_analysis_cycle(dry_run=False)
    except Exception as e:
        logger.exception("Tahlil xatosi")
        last_report = f"⚠️ Tahlil vaqtida xatolik: {e}"
    await update.message.reply_text(last_report, parse_mode="Markdown")


async def pause_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Foydalanish: /pause <ad_id>")
        return
    ad_id = context.args[0]
    try:
        meta_api.pause_object(ad_id)
        await update.message.reply_text(f"⏸ {ad_id} to'xtatildi.")
    except meta_api.MetaAPIError as e:
        await update.message.reply_text(f"⚠️ Xatolik: {e}")


async def resume_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Foydalanish: /resume <ad_id>")
        return
    ad_id = context.args[0]
    try:
        meta_api.activate_object(ad_id)
        await update.message.reply_text(f"▶️ {ad_id} ishga tushirildi.")
    except meta_api.MetaAPIError as e:
        await update.message.reply_text(f"⚠️ Xatolik: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_report
    chat_id = update.effective_chat.id
    user_text = update.message.text
    history = conversations.setdefault(chat_id, [])

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # Avval: bu erkin xabar haqiqiy amaliy buyruqmi (masalan "yangi target yoq",
    # "X reklamani to'xtat", "abtest boshla")? Bo'lsa — to'liq Targetolog ->
    # Marketolog -> ijro zanjiri avtomatik ishga tushadi, hisobga real o'zgarish
    # kiritiladi va natija Telegram'ga qaytadi.
    try:
        command_result = orchestrator.handle_chat_command(user_text, recent_history=history)
    except Exception as e:
        logger.exception("handle_chat_command xatosi")
        command_result = None

    if command_result is not None:
        last_report = command_result
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": command_result})
        history[:] = history[-MAX_HISTORY_MESSAGES:]
        for i in range(0, len(command_result), 4000):
            await update.message.reply_text(command_result[i:i + 4000], parse_mode="Markdown")
        return

    # Aks holda — oddiy maslahat/Q&A rejimi (hisobga tegilmaydi)
    history.append({"role": "user", "content": user_text})
    history[:] = history[-MAX_HISTORY_MESSAGES:]

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=KNOWLEDGE_BASE,
            messages=history,
        )
        answer = response.content[0].text
    except Exception as e:
        logger.exception("Claude API xatosi")
        answer = f"⚠️ Xatolik yuz berdi: {e}"

    history.append({"role": "assistant", "content": answer})

    for i in range(0, len(answer), 4000):
        await update.message.reply_text(answer[i:i + 4000])


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("pause", pause_ad))
    app.add_handler(CommandHandler("resume", resume_ad))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Target Master bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
