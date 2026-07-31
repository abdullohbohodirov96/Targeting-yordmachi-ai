"""
budget_tracker.py — Reklama hisobiga qancha pul "tushirilgani" (deposit) va
joriy REAL xarajat sur'atiga (burn-rate) qarab bu pul necha kunga/qachongacha
yetishini hisoblaydigan modul.

VERCEL UCHUN MOSLASHTIRILDI: holat endi mahalliy faylda emas, `kv_store.py`
orqali tashqi KV/Redis'da saqlanadi (Vercel'da fayl tizimi so'rovlar orasida
saqlanmaydi).

Ishlash mantig'i:
  - Foydalanuvchi Telegram'da "bugun 500$ tushdi" desa -> `record_deposit()`
    balansga 500 qo'shadi.
  - Har safar balans so'ralganda yoki tekshirilganda, oxirgi tekshiruvdan
    beri REAL sarflangan pul (Meta API'dan) balansdan ayiriladi
    (`_reconcile()`) — shuning uchun balans doim haqiqiy xarajatga mos keladi,
    hech qachon o'ylab topilmaydi.
  - `get_status()` — joriy balans + so'nggi 3 kunlik o'rtacha kunlik xarajat
    (burn-rate) asosida necha kunga yetishini va taxminiy tugash sanasini
    hisoblab qaytaradi.
  - `check_and_alert()` — cron (/api/cron/budget) muntazam chaqiradi; balans
    belgilangan chegaradan (odatda $100) pastga tushsa, foydalanuvchi
    so'ramasa ham, birinchi bo'lib xabar yuborish uchun matn qaytaradi.
"""

from datetime import datetime, timezone, timedelta

import meta_api
import kv_store

STATE_KEY = "budget_state"

DEFAULT_STATE = {
    "balance_usd": 0.0,
    "last_reconciled_at": None,       # ISO — oxirgi marta xarajat balansdan ayirilgan payt
    "alert_threshold_usd": 100.0,     # shu qiymatdan pastga tushsa ogohlantiriladi
    "alert_sent_for_current_balance": False,
    "notify_chat_id": None,           # ogohlantirish/kunlik hisobot yuboriladigan Telegram chat
    "deposit_history": [],            # [{"at": ISO, "amount": 500.0}]
}


def _load_state() -> dict:
    state = kv_store.get_json(STATE_KEY, default=None)
    if state is None:
        return dict(DEFAULT_STATE)
    for k, v in DEFAULT_STATE.items():
        state.setdefault(k, v)
    return state


def _save_state(state: dict) -> None:
    kv_store.set_json(STATE_KEY, state)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reconcile(state: dict) -> dict:
    """Oxirgi tekshiruvdan beri REAL sarflangan pulni (Meta API orqali)
    balansdan ayiradi. Har doim `get_status`/`record_deposit`/`check_and_alert`
    ichida chaqiriladi — foydalanuvchi hech qachon balansni qo'lda
    "sinxronlashtirish" haqida o'ylashi shart emas."""
    now = datetime.now(timezone.utc)
    if state["last_reconciled_at"]:
        since_date = datetime.fromisoformat(state["last_reconciled_at"]).date().isoformat()
        until_date = now.date().isoformat()
        try:
            spent = meta_api.get_account_spend(since=since_date, until=until_date)
            state["balance_usd"] = max(0.0, state["balance_usd"] - spent)
        except meta_api.MetaAPIError:
            pass  # API xato bo'lsa balansni buzmaymiz, keyingi safar qayta urinamiz
    state["last_reconciled_at"] = _now_iso()
    return state


def record_deposit(amount: float, chat_id: int) -> dict:
    """Foydalanuvchi 'X$ tushdi' deganda chaqiriladi. Avval joriy balansni
    haqiqiy xarajat bilan sinxronlaydi, keyin yangi summani qo'shadi va
    joriy burn-rate asosida to'liq holatni qaytaradi."""
    state = _load_state()
    state = _reconcile(state)
    state["balance_usd"] += amount
    state["notify_chat_id"] = chat_id
    state["alert_sent_for_current_balance"] = False  # yangi deposit -> yangi ogohlantirish tsikli
    state["deposit_history"].append({"at": _now_iso(), "amount": amount})
    _save_state(state)
    return get_status(state)


def set_notify_chat_id(chat_id: int) -> None:
    """Bot har qanday xabar/interaktsiyada shu chat_id'ni saqlab qo'yadi —
    shunda deposit hali yozilmagan bo'lsa ham, kunlik avtomatik tahlil va
    ogohlantirishlar qayerga yuborilishini bot biladi."""
    state = _load_state()
    if state.get("notify_chat_id") != chat_id:
        state["notify_chat_id"] = chat_id
        _save_state(state)


def get_notify_chat_id() -> int | None:
    return _load_state().get("notify_chat_id")


def get_status(state: dict | None = None) -> dict:
    """Joriy balans, kunlik o'rtacha xarajat (burn-rate) va necha kunga/
    qachon tugashi haqida REAL Meta xarajat ma'lumotidan hisoblangan
    to'liq natijani qaytaradi (hech narsa o'ylab topilmaydi)."""
    if state is None:
        state = _load_state()
        state = _reconcile(state)
        _save_state(state)

    try:
        daily_burn = meta_api.get_account_daily_spend_avg(days=3)
    except meta_api.MetaAPIError:
        daily_burn = 0.0

    balance = state["balance_usd"]
    threshold = state["alert_threshold_usd"]
    result = {
        "balance_usd": round(balance, 2),
        "daily_burn_usd": round(daily_burn, 2),
        "alert_threshold_usd": threshold,
    }
    if daily_burn > 0:
        days_remaining = balance / daily_burn
        days_until_threshold = max(0.0, (balance - threshold) / daily_burn)
        now = datetime.now(timezone.utc)
        result["days_remaining"] = round(days_remaining, 1)
        result["run_out_date"] = (now + timedelta(days=days_remaining)).date().isoformat()
        result["days_until_threshold"] = round(days_until_threshold, 1)
        result["threshold_date"] = (now + timedelta(days=days_until_threshold)).date().isoformat()
    else:
        result["days_remaining"] = None
        result["note"] = "So'nggi 3 kunda xarajat qayd etilmagan — kun hisoblanmadi."
    return result


def format_status_message(status: dict) -> str:
    lines = [
        f"💰 Joriy balans: ${status['balance_usd']:.2f}",
        f"🔥 Kunlik o'rtacha xarajat (so'nggi 3 kun): ${status['daily_burn_usd']:.2f}",
    ]
    if status.get("days_remaining") is not None:
        lines.append(
            f"📅 Shu sur'atda ~{status['days_remaining']} kunga yetadi "
            f"(taxminan {status['run_out_date']} atrofida tugaydi)."
        )
        lines.append(
            f"⚠️ ${status['alert_threshold_usd']:.0f} chegarasiga ~{status['days_until_threshold']} "
            f"kunda (taxminan {status['threshold_date']}) yetadi — shu payt sizga o'zim xabar beraman."
        )
    else:
        lines.append(status.get("note", ""))
    return "\n".join(lines)


def check_and_alert() -> dict | None:
    """cron (/api/cron/budget) muntazam chaqiradi. Agar balans chegaradan
    pastga tushgan bo'lsa va shu tushish uchun hali xabar berilmagan bo'lsa —
    {'chat_id':..., 'message':...} qaytaradi, aks holda `None`."""
    state = _load_state()
    state = _reconcile(state)
    _save_state(state)

    if state["notify_chat_id"] is None:
        return None
    if state["balance_usd"] > state["alert_threshold_usd"]:
        return None
    if state["alert_sent_for_current_balance"]:
        return None

    status = get_status(state)
    state["alert_sent_for_current_balance"] = True
    _save_state(state)
    message = (
        f"⚠️ Diqqat! Balans ${state['alert_threshold_usd']:.0f} chegarasidan pastga tushdi.\n\n"
        + format_status_message(status)
    )
    return {"chat_id": state["notify_chat_id"], "message": message}
