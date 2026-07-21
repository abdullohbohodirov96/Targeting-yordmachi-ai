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
        "audience_change": {
          "location_current_city_only": true,
          "disable_expansion": true,
          "add_region_question_to_form": true
        }
      },
      "risk_level": "low | medium | high",
      "requires_marketolog_approval": true
    }
  ]
}
```

## Risk darajalari (Targetolog o'zi belgilaydi)
- **low** — kichik byudjet o'zgarishi (≤20%), kreativ almashtirish taklifi, tahlil.
- **medium** — kampaniya pause/resume, audience o'zgarishi.
- **high** — 20% dan katta byudjet o'zgarishi, bir nechta kampaniyani birdaniga to'xtatish.

## Qoida
`risk_level = medium yoki high` bo'lgan har qanday action **majburiy** ravishda
Marketolog tasdig'idan o'tishi kerak (`requires_marketolog_approval: true`).
`low` bo'lsa ham, MVP bosqichida barcha action'lar baribir Marketolog orqali o'tadi —
bu xavfsizlik uchun standart sozlama (`config.py` da `AUTO_APPROVE_LOW_RISK = False`).
