# Target Master — MVP (Telegram AI Targetolog)

Bitta targetolog xodimning kundalik ishini bosadigan AI agent tizimi: Meta Ads
(Facebook/Instagram) hisobini tahlil qiladi, kampaniya on/off qiladi, byudjetni
sozlaydi, kreativ va lead sifati muammolarini aniqlab, tuzatish tavsiyalarini
beradi — hammasi Telegram bot orqali.

Bilim bazasi — sizning NotebookLM'dagi **"Mastering Meta Ads: 2026 Algorithms
and Scaling Strategies"** bloknotingizdagi 68 ta manbadan yig'ilgan.

## Fayllar tuzilmasi

```
target_master_agent.md          — to'liq bilim bazasi (Meta Ads 2026 strategiyalari)
agents/
  targetolog_system_prompt.md   — Targetolog agent roli (tahlil + action taklif qiladi)
  marketolog_system_prompt.md   — Marketolog agent roli (Targetolog'ni tekshiradi)
  action_schema.md              — ikki agent orasidagi JSON format
business_rules.json             — sizning biznes qoidalaringiz (CPA, byudjet limiti va h.k.)
meta_api.py                     — Meta Marketing API bilan ishlash funksiyalari
orchestrator.py                 — Targetolog -> Marketolog -> ijro tsiklini boshqaradi
telegram_bot.py                 — Telegram bot (suhbat + /analyze, /pause, /resume, /status)
```

## Tizim qanday ishlaydi (MVP arxitektura)

```
[Meta Ads hisobi] --insights/region breakdown--> [Targetolog agent]
                                                        |
                                                        v  (action_plan JSON)
                                                 [Marketolog agent]
                                                        |
                                          approved / rejected / edited
                                                        |
                                                        v
                                    [meta_api.py: pause/resume/budget/audience]
                                                        |
                                                        v
                                          Telegram'ga hisobot + qo'lda ish ro'yxati
```

**Muhim:** Targetolog hech qachon to'g'ridan-to'g'ri hisobga tegmaydi. Har bir
taklif avval Marketolog agent tomonidan tekshiriladi, faqat tasdiqlangani ijro
etiladi. Bu — pulingiz xavfsizligi uchun ataylab qo'yilgan ikkinchi nazorat qatlami.

## Nimalar to'liq avtomatik ishlaydi

- ✅ Kampaniya/adset/ad statistikasini o'qish va tahlil qilish (CPM, CTR, CPA, ROAS, Frequency)
- ✅ Hudud (region) bo'yicha breakdown va noto'g'ri hudud muammosini aniqlash
- ✅ Reklamani pauza/qayta ishga tushirish
- ✅ Byudjetni 10-20% qadamda oshirish/kamaytirish (scaling qoidasiga ko'ra)
- ✅ Auditoriya/joylashuv sozlamalarini tuzatish (current city only, auto-expansion off)
- ✅ **Yangi targeting/kampaniyani to'liq ishga tushirish** — Telegramga oddiy
  matn bilan ("yangi target yoq, IELTS kursi, $20/kun, Toshkent") yozsangiz,
  Targetolog professional spec tuzadi, Marketolog tekshiradi, tasdiqlansa
  campaign + adset (+ ad, agar creative_id bergan bo'lsangiz) haqiqiy hisobda yaratiladi.
- ✅ **A/B test** — "abtest boshla" desangiz, mavjud adset nusxalanadi, bitta
  o'zgaruvchi (auditoriya yoki kreativ) farqlantiriladi, ikkalasi ham yoqiladi.
- ✅ **Har qanday metrikani so'rash** — "video nechta odam ko'rgan", "necha foizi
  15 soniyani ko'rgan (thruplay)", "CPA qancha bo'ldi" kabi savollarga Meta
  API'dan real raqamlarni tortib, aniq javob beradi (o'ylab topmaydi).
- ✅ Har bir amal uchun to'liq log (`logs/run_*.json`)

### Telegram'da qanday ishlatiladi (erkin matn orqali)

Bot har bir xabarni avtomatik 3 turga ajratadi:
1. **Amaliy buyruq** ("yangi target yoq...", "X reklamani to'xtat", "abtest boshla") →
   to'liq Targetolog→Marketolog→ijro zanjiri ishga tushadi.
2. **Metrika savoli** ("video ko'rish % qancha", "bugun qancha xarajat bo'ldi") →
   Meta API'dan real ma'lumot tortib, aniq raqam bilan javob beradi.
3. **Umumiy savol** ("CBO nima", "byudjetni qachon oshirish kerak") → bilim
   bazasidan maslahat beradi, hisobga tegmaydi.

`/analyze`, `/pause`, `/resume`, `/status` buyruqlari ham alohida mavjud.

## Nimalar "taklif" darajasida qoladi (qo'lda tasdiqlash kerak)

Halol bo'lish uchun aytib o'tamiz — bu joylarda AI **video/rasm yarata olmaydi**
va Meta'ning ba'zi bo'limlari (forma dizayni) hali to'liq API orqali ochiq emas:

- 🎨 **Kreativ almashtirish** — Targetolog Hook/Body/CTA matnini yozib beradi,
  lekin videoni/rasmni tayyorlash va yuklash hali odam (yoki video-generatsiya
  vositasi) qo'lida.
- 📋 **Instant Form yaratish** — `meta_api.create_lead_form()` funksiyasi tayyor,
  lekin forma matnini birinchi marta ko'rib chiqib tasdiqlashni tavsiya qilamiz.

Bular ham vaqt o'tishi bilan avtomatlashtirilishi mumkin (masalan video-generatsiya
API'lari bilan bog'lab), lekin MVP bosqichida xavfsizlik va sifat uchun ataylab
inson nazoratida qoldirilgan.

## O'rnatish

```bash
pip install python-telegram-bot anthropic requests
```

### Kerakli ENV o'zgaruvchilar

| O'zgaruvchi | Qayerdan olinadi |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather |
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `META_ACCESS_TOKEN` | Business Manager -> System Users -> Generate Token (`ads_management`, `ads_read`, `leads_retrieval`, `pages_read_engagement`) |
| `META_AD_ACCOUNT_ID` | Ads Manager'dagi hisob ID (`act_...` formatida) |

### Meta tomonidagi eslatma (juda muhim)

Agar reklama kabinetingiz va Facebook sahifangiz **o'zingizning** Business
Manager'ingiz ostida bo'lsa, System User token orqali `ads_management` va
`ads_read` ruxsatlari **App Review'siz** ishlaydi — o'zingizning hisobingizni
to'liq boshqarishingiz mumkin. `leads_retrieval` (lidlarni o'qish) uchun ba'zan
qo'shimcha tekshiruv talab qilinishi mumkin — agar muammo chiqsa, Meta Business
Help Center orqali "Leads Retrieval" ruxsatini so'rang.

Agar kelajakda boshqa mijozlarning (sizniki bo'lmagan) reklama kabinetlarini
ham shu bot orqali boshqarmoqchi bo'lsangiz, u holda to'liq Meta App Review
jarayonidan o'tish kerak bo'ladi.

### Ishga tushirish

```bash
# Bir martalik tahlil (terminalda test qilish uchun)
python orchestrator.py

# Telegram bot (doimiy ishlaydi)
python telegram_bot.py
```

Botga `/analyze` yuborsangiz — Targetolog + Marketolog tsikli ishga tushadi va
natija Telegram'ga qaytadi.

## Keyingi qadamlar (MVP'dan keyin)

1. `business_rules.json`'ni o'z biznesingiz raqamlariga moslang (maqsadli CPA/ROAS,
   oylik byudjet limiti).
2. `/analyze`'ni kunlik jadval bo'yicha avtomatik ishga tushirish uchun `cron`
   yoki shu Cowork'dagi **schedule** skillidan foydalanishingiz mumkin.
3. Lead CRM (AmoCRM/Bitrix) bilan CAPI integratsiyasini ulash — bu Targetolog'ga
   "sifatli lid" signalini beradi va targeting sifatini oshiradi (4.6-bo'lim).
4. Vaqt o'tishi bilan `logs/run_*.json` tarixidan foydalanib, Marketolog agentga
   "avvalgi takliflar qanday natija bergani" tarixini ham berish mumkin — bu
   qarorlar sifatini yanada oshiradi.
