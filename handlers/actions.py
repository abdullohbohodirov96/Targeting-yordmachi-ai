"""
Safe Action Confirmation System.
Admin so'ragan actionlar inline button bilan tasdiqlanadi.
Tasdiqlamasdan Meta API ga hech qanday o'zgartirish yuborilmaydi.
"""
import re
from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from services.meta_actions_service import MetaActionsService
from config.settings import ADMIN_ID
from utils.logger import logger

router = Router()

# Kutilayotgan actionlar (object_id -> action details)
pending_actions = {}


def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


# === ACTION KEYWORDS ===

ACTION_KEYWORDS = {
    "pause": ["o'chir", "pauza", "pause", "stop", "to'xtat"],
    "enable": ["yoq", "enable", "active", "ishga tushir", "qayta yoq"],
    "budget": ["budget", "byudjet", "pul", "dollar"],
}

OBJECT_KEYWORDS = {
    "campaigns": ["campaign", "kampaniya"],
    "adsets": ["adset", "ad set", "auditoriya"],
    "ads": ["ad", "reklama", "e'lon"],
}


def detect_action_request(text: str) -> dict | None:
    """
    Matndan action intent va parametrlarni ajratadi.
    Returns: {"action": "pause/enable/budget", "obj_type": "campaigns", "query": "...", "budget": float|None}
    """
    text_lower = text.lower()

    # Action type aniqlash
    action = None
    for act, keywords in ACTION_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            action = act
            break

    if not action:
        return None

    # Object type aniqlash
    obj_type = "campaigns"  # default
    for otype, keywords in OBJECT_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            obj_type = otype
            break

    # Query (campaign nomi) aniqlash — action va object keyword'larini olib tashlaymiz
    query = text_lower
    for keywords in ACTION_KEYWORDS.values():
        for kw in keywords:
            query = query.replace(kw, "")
    for keywords in OBJECT_KEYWORDS.values():
        for kw in keywords:
            query = query.replace(kw, "")
    # Oddiy so'zlarni olib tashlash
    for w in ["ni", "ni", "ga", "da", "dan", "qil", "ber", "kerak", "dagi"]:
        query = query.replace(w, "")
    query = query.strip().strip("'\"").strip()

    # Budget amount aniqlash
    budget = None
    if action == "budget":
        match = re.search(r'\$?\s*(\d+(?:\.\d+)?)', text)
        if match:
            budget = float(match.group(1))

    if not query and action != "budget":
        return None

    return {
        "action": action,
        "obj_type": obj_type,
        "query": query,
        "budget": budget,
    }


def _make_confirm_keyboard(action_id: str) -> InlineKeyboardMarkup:
    """Tasdiqlash/bekor qilish inline button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"confirm_{action_id}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"cancel_{action_id}"),
        ]
    ])


def _make_select_keyboard(objects: list, action: str, budget: float = None) -> InlineKeyboardMarkup:
    """Bir nechta mos ob'ekt topilsa tanlash tugmasi."""
    buttons = []
    for obj in objects[:5]:  # max 5 ta ko'rsatamiz
        obj_id = obj["id"]
        name = obj.get("name", "?")[:30]
        status = obj.get("status", "?")
        cb_data = f"select_{action}_{obj_id}"
        if budget:
            cb_data += f"_{int(budget)}"
        buttons.append([InlineKeyboardButton(
            text=f"{name} [{status}]",
            callback_data=cb_data[:64]  # Telegram limit
        )])
    buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_select")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === MESSAGE HANDLER (action detect) ===

async def handle_action_request(message: types.Message) -> bool:
    """
    Xabardan action so'rovini aniqlaydi va jarayonni boshlaydi.
    Agar action so'rovi bo'lmasa False qaytaradi.
    """
    if not is_admin(message.from_user.id):
        return False

    request = detect_action_request(message.text)
    if not request:
        return False

    meta = MetaActionsService()
    query = request["query"]
    action = request["action"]
    obj_type = request["obj_type"]
    budget = request.get("budget")

    # Campaign/adset/ad qidirish
    if not query and action == "budget" and budget:
        await message.answer("⚠️ Qaysi campaign/adset nazarda tutilganini aniqlashtiring.")
        return True

    matches = await meta.search_objects(query, obj_type)

    if not matches:
        await message.answer(
            f"🔍 \"{query}\" bo'yicha hech qanday {obj_type} topilmadi.\n\n"
            "Iltimos, nom aniqroq yozing."
        )
        return True

    if len(matches) == 1:
        # Bitta mos — darhol confirmation
        obj = matches[0]
        await _send_confirmation(message, obj, action, budget)
    else:
        # Ko'p mos — tanlash
        await message.answer(
            f"🔍 \"{query}\" bo'yicha {len(matches)} ta mos topildi.\nQaysi birini tanlaysiz?",
            reply_markup=_make_select_keyboard(matches, action, budget)
        )

    return True


async def _send_confirmation(message_or_callback, obj: dict, action: str, budget: float = None):
    """Confirmation xabarini yuboradi."""
    obj_id = obj["id"]
    obj_name = obj.get("name", "Noma'lum")
    obj_status = obj.get("status", "?")

    action_labels = {
        "pause": "⏸ Pause (to'xtatish)",
        "enable": "▶️ Enable (yoqish)",
        "budget": f"💰 Budget o'zgartirish → ${budget}",
    }
    action_label = action_labels.get(action, action)

    text = (
        f"⚠️ TASDIQLASH KERAK\n\n"
        f"Action: {action_label}\n"
        f"Nomi: {obj_name}\n"
        f"Hozirgi status: {obj_status}\n"
        f"ID: {obj_id}\n\n"
        f"Tasdiqlaysizmi?"
    )

    # Action'ni pending qatorga qo'shamiz
    action_id = f"{obj_id}_{action}"
    pending_actions[action_id] = {
        "object_id": obj_id,
        "object_name": obj_name,
        "action": action,
        "budget": budget,
    }

    kb = _make_confirm_keyboard(action_id)

    if isinstance(message_or_callback, types.CallbackQuery):
        await message_or_callback.message.answer(text, reply_markup=kb)
    else:
        await message_or_callback.answer(text, reply_markup=kb)


# === CALLBACK HANDLERS ===

@router.callback_query(F.data.startswith("confirm_"))
async def on_confirm(callback: types.CallbackQuery):
    """Admin tasdiqladi — action bajariladi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Bu amal faqat admin uchun.", show_alert=True)
        return

    action_id = callback.data.replace("confirm_", "")
    action_data = pending_actions.pop(action_id, None)

    if not action_data:
        await callback.answer("⏳ Bu so'rov eskirgan.", show_alert=True)
        await callback.message.edit_text("⏳ Bu so'rov eskirgan yoki allaqachon bajarilgan.")
        return

    meta = MetaActionsService()
    obj_id = action_data["object_id"]
    obj_name = action_data["object_name"]
    action = action_data["action"]
    budget = action_data.get("budget")

    # Action bajarish
    if action == "pause":
        result = await meta.update_status(obj_id, "PAUSED", callback.from_user.id)
    elif action == "enable":
        result = await meta.update_status(obj_id, "ACTIVE", callback.from_user.id)
    elif action == "budget" and budget:
        result = await meta.update_budget(obj_id, budget, callback.from_user.id)
    else:
        result = {"success": False, "message": "Noma'lum action"}

    # Natijani ko'rsatish
    if result["success"]:
        await callback.message.edit_text(
            f"✅ Amal bajarildi.\n\n"
            f"📋 {obj_name}\n"
            f"Action: {action}\n"
            f"Natija: {result['message']}"
        )
    else:
        await callback.message.edit_text(
            f"❌ Meta API xatolik berdi.\n\n"
            f"📋 {obj_name}\n"
            f"Action: {action}\n"
            f"Xato: {result['message']}"
        )

    await callback.answer()


@router.callback_query(F.data.startswith("cancel_"))
async def on_cancel(callback: types.CallbackQuery):
    """Admin bekor qildi."""
    action_id = callback.data.replace("cancel_", "")
    pending_actions.pop(action_id, None)
    await callback.message.edit_text("❌ Amal bekor qilindi.")
    await callback.answer()


@router.callback_query(F.data.startswith("select_"))
async def on_select(callback: types.CallbackQuery):
    """Admin ob'ektni tanladi — confirmation yuboriladi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Bu amal faqat admin uchun.", show_alert=True)
        return

    parts = callback.data.split("_")
    # select_pause_123456 yoki select_budget_123456_20
    action = parts[1]
    obj_id = parts[2]
    budget = float(parts[3]) if len(parts) > 3 else None

    meta = MetaActionsService()

    # Ob'ekt ma'lumotini olish
    # ID bo'yicha to'g'ridan-to'g'ri olish mumkin emas, shuning uchun qisqacha
    obj = {"id": obj_id, "name": f"ID: {obj_id}", "status": "?"}

    await _send_confirmation(callback, obj, action, budget)
    await callback.answer()
