"""
kv_store.py — Vercel serverless muhitida holatni saqlash uchun yengil wrapper.

MUHIM: Vercel'da har bir so'rov alohida, qisqa muddatli funksiya sifatida
ishga tushadi — mahalliy fayl (masalan budget_state.json) so'rovlar orasida
SAQLANMAYDI. Shuning uchun holat (byudjet balansi, suhbat tarixi, oxirgi
hisobot) tashqi Redis-mos bazada (Vercel KV yoki Upstash Redis) saqlanadi —
bu Upstash'ning oddiy REST API'si, maxsus SDK shart emas, faqat `requests`.

KERAKLI ENV O'ZGARUVCHILAR (birortasi bo'lsa yetarli — ikkalasi ham bir xil
Upstash REST protokoliga mos):
    Vercel KV ulaganda avtomatik qo'shiladi:  KV_REST_API_URL, KV_REST_API_TOKEN
    Mustaqil Upstash Redis ulasa:             UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN
"""

import os
import json
import requests

_URL = (os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN") or ""


class KVNotConfigured(Exception):
    """KV_REST_API_URL/TOKEN (yoki UPSTASH_REDIS_REST_*) o'rnatilmagan."""


def _check_configured():
    if not _URL or not _TOKEN:
        raise KVNotConfigured(
            "KV/Upstash Redis ulanmagan. Vercel loyihasiga KV (Storage -> Create -> KV) "
            "qo'shing yoki UPSTASH_REDIS_REST_URL/UPSTASH_REDIS_REST_TOKEN env "
            "o'zgaruvchilarini qo'lda o'rnating."
        )


def _headers():
    return {"Authorization": f"Bearer {_TOKEN}"}


def kv_get(key: str) -> str | None:
    _check_configured()
    r = requests.get(f"{_URL}/get/{key}", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("result")


def kv_set(key: str, value: str) -> None:
    _check_configured()
    r = requests.post(f"{_URL}/set/{key}", headers=_headers(), data=value.encode("utf-8"), timeout=10)
    r.raise_for_status()


def get_json(key: str, default=None):
    try:
        raw = kv_get(key)
    except KVNotConfigured:
        return default
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def set_json(key: str, value) -> None:
    kv_set(key, json.dumps(value, ensure_ascii=False))
