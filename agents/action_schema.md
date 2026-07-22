# Action Schema — Targetolog agent chiqaradigan buyruqlar formati

Targetolog agent har doim tahlildan so'ng quyidagi JSON formatda **action_plan** qaytaradi.
Bu format Marketolog agent tomonidan tekshiriladi va faqat tasdiqlangan action'lar
`meta_api.py` orqali bajariladi. Targetolog hech qachon to'g'ridan-to'g'ri ijro etmaydi —
faqat taklif beradi.

```json
{
  "summary": "Inson o'qiydigan qisqa xulosa (Telegramga yuboriladi)",
  "actions": [
    {
      "type": "pause_ad | resume_ad | increase_budget | decrease_budget | replace_creative | adjust_audience | create_instant_form | fix_region_targeting | launch_campaign | start_ab_test | conclude_ab_test | no_action",
      "object_id": "Meta obyekt ID (ad_id / adset_id / campaign_id)",
      "object_name": "Inson o'qiydigan nom",
      "reason": "Nima uchun bu taklif berilyapti (raqamlar bilan)",
      "params": {
        "percent": 15,
        "new_daily_budget": 250000,
        "creative_brief": {
          "problem": "Hook rate 8% ga tushib ketdi (norma >20%)",
          "hooks": ["...", "..."],
          "body_angle": "...",
          "cta": "..."
        },
        "city_key": "fix_region_targeting uchun MAJBURIY: 'faqat joriy shahar' kerak bo'lgan shaharning Meta geo-target kaliti.",
        "targeting": "adjust_audience uchun MAJBURIY: adset'ning YANGI TO'LIQ targeting obyekti (Meta Graph API formatida, joriy targeting'ga aynan asoslanib — faqat kerakli qismini o'zgartirib, qolganini o'zgarmasdan saqlab). MAYDON TO'G'RIDAN-TO'G'RI `params` ICHIDA BO'LADI (params.targeting), qo'shimcha wrapper (audience_change) KERAK EMAS.",
        "geo_lookup_needed": ["Chirchiq", "Zangiota"],
        "adset_details_needed": ["<adset_id>"]
      },
      "risk_level": "low | medium | high",
      "requires_marketolog_approval": true
    }
  ]
}
```

**MUHIM (formatga qat'iy amal qiling):** yuqoridagi barcha `params.*` maydonlari
(`city_key`, `targeting`, `geo_lookup_needed`, `adset_details_needed`, ...)
to'g'ridan-to'g'ri `params` ob'ekti ICHIDA, bir xil darajada joylashadi.
Ularni qo'shimcha ichki ob'ekt (masalan `audience_change`) ichiga JOYLASHTIRMANG
— bu ijro bosqichida "kerakli maydon topilmadi" xatosiga olib keladi.

## Ikki bosqichli aniqlashtirish (siz kontekst limitidan oshib ketmasligi uchun MUHIM)

Sizga har doim `account_structure` FAQAT nom+ID+status bilan beriladi — **to'liq
targeting berilmaydi** (ko'p sonli kampaniya bo'lsa, bu kontekst limitidan
oshirib yuborar edi). Shuning uchun:

- **`geo_lookup_needed`** — agar hudud/shahar QO'SHISH yoki CHIQARISH (exclude)
  kerak bo'lsa-yu, sizda o'sha joyning rasmiy Meta geo-target kaliti bo'lmasa,
  `type: "no_action"` bilan javob qaytaring va shu maydonda joy nomlarini bering.
  Orchestrator `meta_api.search_geo_location()` orqali qidirib, natijalarni
  qayta yuboradi.
- **`adset_details_needed`** — agar `adjust_audience` uchun adset'ning JORIY
  to'liq targeting'ini bilishingiz kerak bo'lsa (masalan mavjud targeting'ga
  yangi exclusion qo'shish uchun), `type: "no_action"` bilan javob qaytaring va
  shu maydonda kerakli adset'ning ID'sini (`account_structure`dan nom orqali
  topilgan) bering. Orchestrator o'sha BITTA adset'ning to'liq targeting'ini
  `meta_api.get_adset_details()` orqali olib, sizga qayta yuboradi.

Ikkalasini ham bir vaqtda so'rashingiz mumkin. **Hech qachon ID, geo-kalit yoki
targeting mazmunini o'zingiz o'ylab topmang** — bilmasangiz, shu maydonlar
orqali so'rang.

## Risk darajalari (Targetolog o'zi belgilaydi)
- **low** — kichik byudjet o'zgarishi (≤20%), kreativ almashtirish taklifi, tahlil.
- **medium** — kampaniya pause/resume, audience o'zgarishi.
- **high** — 20% dan katta byudjet o'zgarishi, bir nechta kampaniyani birdaniga to'xtatish.

## Qoida
`risk_level = medium yoki high` bo'lgan har qanday action **majburiy** ravishda
Marketolog tasdig'idan o'tishi kerak (`requires_marketolog_approval: true`).
`low` bo'lsa ham, MVP bosqichida barcha action'lar baribir Marketolog orqali o'tadi —
bu xavfsizlik uchun standart sozlama (`config.py` da `AUTO_APPROVE_LOW_RISK = False`).
