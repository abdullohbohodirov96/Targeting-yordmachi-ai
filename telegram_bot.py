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
    # MUHIM: parse_mode="Markdown" ishlatilmaydi — hisobotlar/Meta xato matnlarida
    # tez-tez "_" kabi belgilar uchraydi (masalan excluded_geo_locations), bular
    # Telegram Markdown parserini buzib, "Can't parse entities" xatosiga olib
    # keladi. Shuning uchun oddiy matn sifatida yuboriladi.
    await update.message.reply_text(last_report)


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_report
    chat_id = update.effective_chat.id
    status_message = await update.message.reply_text("⏳ Tahlil boshlandi — Targetolog va Marketolog ishlamoqda...")
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        last_report = orchestrator.run_analysis_cycle(dry_run=False)
    except Exception as e:
        logger.exception("Tahlil xatosi")
        last_report = f"⚠️ Tahlil vaqtida xatolik: {e}"
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=status_message.message_id)
    except Exception:
        pass
    # MUHIM: parse_mode="Markdown" ishlatilmaydi — hisobotlar/Meta xato matnlarida
    # tez-tez "_" kabi belgilar uchraydi (masalan excluded_geo_locations), bular
    # Telegram Markdown parserini buzib, "Can't parse entities" xatosiga olib
    # keladi. Shuning uchun oddiy matn sifatida yuboriladi.
    await update.message.reply_text(last_report)


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

    # Ish jarayonini ko'rsatuvchi vaqtinchalik xabar — foydalanuvchi bot
    # "osilib qolganmi yoki ishlayaptimi" bilmay qolmasligi uchun. Ish
    # tugagach (natija qanday bo'lishidan qat'iy nazar) shu xabar o'chiriladi.
    status_message = await update.message.reply_text("⏳ Bajaryapman...")

    async def _clear_status():
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=status_message.message_id)
        except Exception:
            pass  # xabar allaqachon o'chirilgan/topilmasa muammo emas

    # Avval: bu erkin xabar haqiqiy amaliy buyruqmi (masalan "yangi target yoq",
    # "X reklamani to'xtat", "abtest boshla")? Bo'lsa — to'liq Targetolog ->
    # Marketolog -> ijro zanjiri avtomatik ishga tushadi, hisobga real o'zgarish
    # kiritiladi va natija Telegram'ga qaytadi.
    try:
        command_result = orchestrator.handle_chat_command(user_text, recent_history=history)
    except Exception as e:
        # MUHIM: bu yerda jim qolib, oddiy maslahat rejimiga "yashirincha"
        # tushib ketmaymiz — aks holda foydalanuvchi buyrug'i bajarilmagan
        # bo'lsa ham, bot xuddi hammasi joyidek maslahat berib qo'yadi va bu
        # aslida hech narsa qilinmaganini yashirib qo'yadi. Xatoni ochiq aytamiz.
        logger.exception("handle_chat_command xatosi")
        await _clear_status()
        await update.message.reply_text(
            f"⚠️ Buyruqni bajarishda kutilmagan xatolik yuz berdi: {e}\n\n"
            "Qaytadan urinib ko'ring yoki aniqroq yozing."
        )
        return

    if command_result is not None:
        last_report = command_result
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": command_result})
        history[:] = history[-MAX_HISTORY_MESSAGES:]
        await _clear_status()
        for i in range(0, len(command_result), 4000):
            # parse_mode ishlatilmaydi — sabab yuqoridagi izohda
            await update.message.reply_text(command_result[i:i + 4000])
        return

    # Aks holda — oddiy maslahat/Q&A rejimi (hisobga tegilmaydi)
    history.append({"role": "user", "content": user_text})
    history[:] = history[-MAX_HISTORY_MESSAGES:]

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            # cache_control — bilim bazasi (KNOWLEDGE_BASE) har xabarda bir xil
            # bo'lgani uchun keshlanadi, xarajatni sezilarli kamaytiradi.
            system=[{"type": "text", "text": KNOWLEDGE_BASE, "cache_control": {"type": "ephemeral"}}],
            messages=history,
        )
        answer = response.content[0].text
    except Exception as e:
        logger.exception("Claude API xatosi")
        answer = f"⚠️ Xatolik yuz berdi: {e}"

    await _clear_status()
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
