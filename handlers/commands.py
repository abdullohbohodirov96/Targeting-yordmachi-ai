from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from services.report_builder import build_target_report, build_campaigns_report
from services.meta_ads_service import MetaAdsService
from services.cpl_limits import get_all_limits, set_limit, remove_limit, get_limit
from config.settings import ADMIN_ID

router = Router()


# === FSM STATES ===

class SetLimitState(StatesGroup):
    waiting_campaign = State()
    waiting_limit = State()


# === HELPER FUNCTIONS ===

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

def is_private_chat(message: types.Message) -> bool:
    return message.chat.type == "private"

def is_group_chat(message: types.Message) -> bool:
    return message.chat.type in ["group", "supergroup"]


# === COMMANDS ===

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    if is_admin(message.from_user.id):
        text = (
            "🤖 *DUNYABUNYA AI TARGET ASSISTANT*\n\n"
            "Assalomu alaykum, Admin 👋\n\n"
            "Sizga to'liq access berilgan:\n"
            "📊 Real-time statistika\n"
            "🤖 AI tahlil va takliflar\n"
            "📋 Kampaniya tahlili\n"
            "🎬 Kreativ va strategiya\n\n"
            "👉 /help — barcha buyruqlar"
        )
    else:
        text = (
            "🤖 *DUNYABUNYA AI TARGET ASSISTANT*\n\n"
            "Assalomu alaykum 👋\n\n"
            "Men sizga marketing va kreativ bo'yicha yordam bera olaman:\n"
            "🎬 Reels ssenariy\n"
            "✍️ Caption, hook, ad copy\n"
            "🎯 Target maslahat\n"
            "💡 Marketing strategiya\n\n"
            "📊 *Statistika* guruhda mavjud.\n\n"
            "👉 /help — yordam"
        )
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    if is_admin(message.from_user.id):
        text = (
            "📌 *ADMIN BUYRUQLARI*\n\n"
            "📈 *Statistika:*\n"
            "/today — bugungi\n"
            "/yesterday — kechagi\n"
            "/week — haftalik\n"
            "/month — oylik\n"
            "/campaigns — kampaniyalar\n"
            "/analyze — AI tahlil\n\n"
            "🚫 *CPL Limit tizimi:*\n"
            "/setlimit — kampaniya CPL limitini o'rnatish\n"
            "/limits — barcha limitlarni ko'rish\n\n"
            "🎬 *AI Assistant:*\n"
            "Kreativ, reels, strategiya, target — hamma narsani so'rang.\n"
        )
    else:
        text = (
            "📌 *BOT YORDAMI*\n\n"
            "🎬 *AI Assistant (private chatda):*\n"
            "• creative yozib ber\n"
            "• reels ssenariy\n"
            "• hook yoz\n"
            "• caption yoz\n"
            "• marketing maslahat\n\n"
            "📊 *Statistika (faqat guruhda):*\n"
            "/today, /yesterday, /week, /month\n"
            "Yoki: '1-may hisobot', 'haftalik statistika'\n\n"
            "⚠️ AI analiz va kampaniya tahlili faqat admin uchun."
        )
    await message.answer(text, parse_mode="Markdown")


# === REPORT COMMANDS ===

async def _send_report(message: types.Message, period: str):
    """
    Report yuborish logikasi:
    - Admin private: to'liq report + AI
    - Admin guruhda: public KPI
    - Oddiy user guruhda: public KPI
    - Oddiy user private: ❌ ruxsat yo'q
    """
    user_admin = is_admin(message.from_user.id)
    private = is_private_chat(message)

    # Oddiy user private chatda statistika so'rayapti — rad etamiz
    if private and not user_admin:
        await message.answer(
            "❌ Uzr, private chatda bu ma'lumotlar faqat admin uchun mavjud.\n\n"
            "📊 Statistikani guruhda olishingiz mumkin."
        )
        return

    await message.answer("⏳ Yuklanmoqda...")

    # Admin private chatda — to'liq report
    if private and user_admin:
        report = await build_target_report(
            period=period, is_admin=True, include_analysis=True
        )
    else:
        # Guruhda — hammaga faqat public KPI
        report = await build_target_report(
            period=period, is_admin=False, include_analysis=False
        )

    await message.answer(report)


@router.message(Command("today"))
async def cmd_today(message: types.Message):
    await _send_report(message, "today")

@router.message(Command("yesterday"))
async def cmd_yesterday(message: types.Message):
    await _send_report(message, "yesterday")

@router.message(Command("week"))
async def cmd_week(message: types.Message):
    await _send_report(message, "week")

@router.message(Command("month"))
async def cmd_month(message: types.Message):
    await _send_report(message, "month")


# === ADMIN-ONLY COMMANDS ===

@router.message(Command("campaigns"))
async def cmd_campaigns(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bu funksiya faqat admin uchun mavjud.")
        return
    if not is_private_chat(message):
        await message.answer("⚠️ Kampaniya ma'lumotlari faqat shaxsiy chatda ko'rsatiladi.")
        return

    await message.answer("⏳ Kampaniyalar yuklanmoqda...")
    report = await build_campaigns_report("today")
    await message.answer(report)

@router.message(Command("analyze"))
async def cmd_analyze(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bu funksiya faqat admin uchun mavjud.")
        return
    if not is_private_chat(message):
        await message.answer("⚠️ AI analiz faqat shaxsiy chatda ko'rsatiladi.")
        return

    await message.answer("🤖 AI tahlil qilinmoqda...")
    report = await build_target_report("today", is_admin=True, include_analysis=True)
    await message.answer(report)


@router.message(Command("limits"))
async def cmd_limits(message: types.Message):
    """Barcha CPL limitlarni ko'rsatish."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bu funksiya faqat admin uchun mavjud.")
        return

    limits = get_all_limits()
    if not limits:
        await message.answer(
            "📋 Hozircha hech qanday CPL limit o'rnatilmagan.\n\n"
            "Yangi limit qo'shish: /setlimit"
        )
        return

    lines = ["📊 <b>CPL LIMITLAR</b>\n"]
    for cid, info in limits.items():
        cname = info.get("campaign_name", "Noma'lum")
        cpl_limit = info.get("cpl_limit", 0)
        lines.append(f"🎯 {cname}\n   🚫 Max CPL: ${cpl_limit:.2f}\n   🆔 {cid}")

    lines.append("\n📝 Limitni o'zgartirish: /setlimit")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("setlimit"))
async def cmd_setlimit(message: types.Message, state: FSMContext):
    """Kampaniya uchun CPL limit o'rnatish."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bu funksiya faqat admin uchun mavjud.")
        return

    await message.answer("⏳ Kampaniyalar yuklanmoqda...")

    meta = MetaAdsService()
    campaigns = await meta.get_active_campaigns_list()

    if not campaigns:
        await message.answer(
            "❌ Faol kampaniyalar topilmadi.\n\n"
            "Meta Ads da ACTIVE kampaniya bo'lishi kerak."
        )
        return

    buttons = []
    for c in campaigns[:10]:
        cid = c.get("id", "")
        cname = c.get("name", "Noma'lum")[:35]
        current_limit = get_limit(cid)
        limit_text = f" [${current_limit:.0f} limit]" if current_limit else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"🎯 {cname}{limit_text}",
                callback_data=f"sl_camp_{cid}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="sl_cancel")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(
        "📋 <b>Kampaniyani tanlang:</b>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await state.set_state(SetLimitState.waiting_campaign)


@router.callback_query(F.data.startswith("sl_camp_"))
async def on_select_campaign_for_limit(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Faqat admin.", show_alert=True)
        return

    cid = callback.data.replace("sl_camp_", "")

    meta = MetaAdsService()
    campaigns = await meta.get_active_campaigns_list()
    campaign = next((c for c in campaigns if str(c.get("id")) == cid), None)
    cname = campaign.get("name", "Noma'lum") if campaign else cid

    await state.update_data(campaign_id=cid, campaign_name=cname)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="$1", callback_data=f"sl_val_1.0"),
            InlineKeyboardButton(text="$2", callback_data=f"sl_val_2.0"),
            InlineKeyboardButton(text="$3", callback_data=f"sl_val_3.0"),
            InlineKeyboardButton(text="$5", callback_data=f"sl_val_5.0"),
        ],
        [
            InlineKeyboardButton(text="$7", callback_data=f"sl_val_7.0"),
            InlineKeyboardButton(text="$10", callback_data=f"sl_val_10.0"),
            InlineKeyboardButton(text="$15", callback_data=f"sl_val_15.0"),
            InlineKeyboardButton(text="$20", callback_data=f"sl_val_20.0"),
        ],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="sl_cancel")],
    ])

    await callback.message.edit_text(
        f"📋 Kampaniya: <b>{cname}</b>\n\n"
        f"💰 Maksimal CPL limitini tanlang yoki raqam yuboring (masalan: 4.5):",
        parse_mode="HTML",
        reply_markup=kb
    )
    await state.set_state(SetLimitState.waiting_limit)
    await callback.answer()


@router.callback_query(F.data.startswith("sl_val_"))
async def on_select_limit_value(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Faqat admin.", show_alert=True)
        return

    val = float(callback.data.replace("sl_val_", ""))
    data = await state.get_data()
    cid = data.get("campaign_id")
    cname = data.get("campaign_name", "Noma'lum")

    if cid:
        set_limit(cid, cname, val)
        await callback.message.edit_text(
            f"✅ <b>CPL Limit o'rnatildi!</b>\n\n"
            f"📋 Kampaniya: {cname}\n"
            f"🚫 Max CPL: <b>${val:.2f}</b>\n\n"
            f"CPL bu miqdordan oshsa, kampaniya avtomatik to'xtatiladi.",
            parse_mode="HTML"
        )
    await state.clear()
    await callback.answer()


@router.message(SetLimitState.waiting_limit)
async def on_limit_text_input(message: types.Message, state: FSMContext):
    """Admin matn orqali CPL limit kiritganda."""
    if not is_admin(message.from_user.id):
        return

    try:
        val = float(message.text.strip().replace("$", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Noto'g'ri format. Raqam kiriting, masalan: 3.5")
        return

    data = await state.get_data()
    cid = data.get("campaign_id")
    cname = data.get("campaign_name", "Noma'lum")

    if cid:
        set_limit(cid, cname, val)
        await message.answer(
            f"✅ <b>CPL Limit o'rnatildi!</b>\n\n"
            f"📋 Kampaniya: {cname}\n"
            f"🚫 Max CPL: <b>${val:.2f}</b>\n\n"
            f"CPL bu miqdordan oshsa, kampaniya avtomatik to'xtatiladi.",
            parse_mode="HTML"
        )
    await state.clear()


@router.callback_query(F.data == "sl_cancel")
async def on_setlimit_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()
