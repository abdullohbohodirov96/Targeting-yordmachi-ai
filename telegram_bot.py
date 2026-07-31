"""
Target Master — Telegram bot (MVP)

Ikki rejimda ishlaydi:
  1. Erkin suhbat — foydalanuvchi savol beradi, Targetolog agent (bilim bazasi bilan)
     javob beradi (real hisobga tegmaydi, faqat maslahat).
  2. Buyruqlar — haqiqiy Meta Ads hisobi bilan ishlaydigan orchestrator'ni ishga
     tushiradi (/analyze, /pause, /resume, /status).

O'RNATISH:
    pip install "python-telegram-bot[job-queue]" anthropic requests
    (MUHIM: [job-queue] qismi shart — kunlik avtomatik tahlil va byudjet
    ogohlantirishi shunga tayanadi, bo'lmasa bot ishga tushadi lekin bu
    ikkalasi ishlamay, faqat ogohlantiruvchi log yozadi.)

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
import budget_tracker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("target-master-bot")

BASE_DIR = Path(__file__).parent
KNOWLEDGE_BASE = (BASE_DIR / "target_master_agent.md").read_text(encoding="utf-8")

# Oddiy erkin suhbat (hisobga tegmaydigan, faqat bilim bazasidan maslahat)
# uchun arzon model yetarli — real qaror/vazifa yaratilmaydigan joylarda
# doim Sonnet emas, Haiku ishlatiladi (xarajatni balanslash).
MODEL = orchestrator.LIGHT_MODEL
MAX_HISTORY_MESSAGES = 10  # xarajatni kamaytirish uchun kamaytirildi (avval 20)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

conversations: dict[int, list[dict]] = {}
last_report: str = "Hali tahlil ishga tushirilmagan. /analyze buyrug'ini yuboring."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversations[update.effective_chat.id] = []
    # Kunlik avtomatik tahlil va byudjet ogohlantirishlari shu chatga
    # yuborilishi uchun saqlab qo'yamiz (deposit hali yozilmagan bo'lsa ham).
    budget_tracker.set_notify_chat_id(update.effective_chat.id)
    await update.message.reply_text(
        "👋 Salom! Men — Targetolog.\n\n"
        "Men bilan oddiy odam bilan gaplashgandek yozavering — buyruq shart emas, "
        "tushunaman va o'zim bajaraman.\n\n"
        "Narx keskin ko'tarilsa yoki target yaxshi natija bermasa, o'zim ko'rib "
        "byudjetni kamaytiraman yoki auditoriyani o'zgartirib, CPL'ni tushirishga "
        "harakat qilaman. Qo'limdan to'liq kelmasa, ochiq shunday deb aytaman.\n\n"
        "Qisqa buyruqlar ham bor:\n"
        "📊 /analyze — hisobni to'liq tahlil qilaman\n"
        "📋 /status — oxirgi hisobotni ko'rsataman\n"
        "⏸ /pause <ad_id>  ▶️ /resume <ad_id>\n"
        "💰 \"bugun 500$ tushdi\" / \"qancha qoldi?\" — byudjet balansini kuzataman, "
        "chegaradan pastga tushsa o'zim xabar beraman.\n"
        "🔁 Har kuni avtomatik tahlil qilib, kerak bo'lmagan narsalarni o'zim "
        "tuzataman/arxivlayman.\n"
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

    # Kunlik avtomatik tahlil va byudjet ogohlantirishlari qayerga
    # yuborilishini har bir xabarda yangilab boramiz.
    budget_tracker.set_notify_chat_id(chat_id)

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
        command_result = orchestrator.handle_chat_command(
            user_text, recent_history=history, chat_id=chat_id
        )
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
            max_tokens=1000,  # xarajatni kamaytirish uchun kamaytirildi
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


async def budget_check_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue muntazam chaqiradi (masalan har 4 soatda). Balans
    ($100 kabi) chegaradan pastga tushsa, foydalanuvchi so'ramasa ham
    o'zimiz birinchi bo'lib xabar beramiz."""
    try:
        alert = budget_tracker.check_and_alert()
    except Exception:
        logger.exception("Byudjet tekshiruvida xatolik")
        return
    if alert:
        try:
            await context.bot.send_message(chat_id=alert["chat_id"], text=alert["message"])
        except Exception:
            logger.exception("Byudjet ogohlantirishini yuborishda xatolik")


async def daily_analysis_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue kuniga bir marta chaqiradi — hisobni to'liq tahlil qilib
    (Targetolog + kerak bo'lsa avtomatik ijro), natijani foydalanuvchiga
    o'zi yuboradi. Shu orqali bot doim "review va publish qilib yuradi"."""
    global last_report
    chat_id = budget_tracker.get_notify_chat_id()
    if chat_id is None:
        return
    try:
        last_report = orchestrator.run_analysis_cycle(dry_run=False)
    except Exception:
        logger.exception("Kunlik avtomatik tahlil xatosi")
        return
    try:
        text = "🔁 Kunlik avtomatik tahlil:\n\n" + last_report
        for i in range(0, len(text), 4000):
            await context.bot.send_message(chat_id=chat_id, text=text[i:i + 4000])
    except Exception:
        logger.exception("Kunlik tahlil hisobotini yuborishda xatolik")


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

    # Byudjet ogohlantirishi va kunlik avtomatik tahlil uchun fon vazifalari.
    # MUHIM: bular ishlashi uchun `python-telegram-bot[job-queue]` kerak
    # (oddiy `python-telegram-bot` yetarli emas — pastdagi eslatmaga qarang).
    if app.job_queue:
        app.job_queue.run_repeating(budget_check_job, interval=4 * 3600, first=120)
        app.job_queue.run_repeating(daily_analysis_job, interval=24 * 3600, first=300)
    else:
        logger.warning(
            "job_queue mavjud emas — 'pip install \"python-telegram-bot[job-queue]\"' "
            "o'rnating, aks holda avtomatik byudjet ogohlantirishi va kunlik tahlil ishlamaydi."
        )

    logger.info("Target Master bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
