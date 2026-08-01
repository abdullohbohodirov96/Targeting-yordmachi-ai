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

**Muhim:** Odatda Targetolog to'g'ridan-to'g'ri hisobga tegmaydi — har bir
taklif avval Marketolog agent tomonidan tekshiriladi, faqat tasdiqlangani ijro
etiladi (ikkinchi nazorat qatlami). Agar tezlik muhimroq bo'lsa,
`business_rules.json` dagi `"skip_marketolog": true` orqali bu bosqichni
o'tkazib yuborish mumkin — shunda Targetolog taklif qilgan HAMMA action
to'g'ridan-to'g'ri ijro etiladi. Xavfsizlikni qaytarish uchun `false` qiling.

**Xarajatni balanslash (model tanlash):** har bir so'rovga qimmat model
ishlatilmaydi. Sonnet (`MODEL`) FAQAT HAQIQIY qaror/vazifa yaratilganda
(Targetolog action_plan, Marketolog tekshiruvi, kunlik avtomatik audit/
avto-tuzatish sikli) ishlatiladi -- bu hech qachon o'zgarmaydi, chunki bilim
bazasiga chuqur tayanadigan qaror uchun arzon model xato qilishi mumkin.
Oddiy narsalar -- intent aniqlash ("bu ACTION mi, oddiy savolmi"), "qaysi
target yoqilgan", "CPA/xarajat qancha" kabi metrika savoliga real raqam
bilan javob berish, sana/davr aniqlash ("20 iyul", "bugun" va h.k.), byudjet
deposit/savoli, erkin suhbat -- FAQAT OpenAI orqali bajariladi
(`OPENAI_API_KEY` + `OPENAI_MODEL`, standart `gpt-4o-mini`). Bu yerda
Claude'ga fallback ATAYLAB YO'Q -- Anthropic API xarajati yengil so'rovlarda
umuman sarflanmasin degan aniq qaror. `OPENAI_API_KEY` sozlanmasa yoki OpenAI
so'rovi xato bersa, foydalanuvchiga aniq xato xabari qaytadi (jim-jit
Claude'ga tushib qolinmaydi) -- shuning uchun `OPENAI_API_KEY` botning
ishlashi uchun MAJBURIY.

Har bir ijro natijasi (muvaffaqiyatli/xato) Telegram hisobotida aniq ko'rsatiladi
— agar Meta biror action'ni rad etsa (masalan "audience invalid"), bu Telegramda
❌ belgisi bilan haqiqiy xato matni bilan ko'rinadi, hech qachon yashirilmaydi.

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
- ✅ **Byudjet balansi kuzatuvi** — "bugun 500$ tushdi" desangiz, `budget_tracker.py`
  balansni yozib oladi va REAL kunlik xarajat sur'ati (Meta API'dan) asosida
  necha kunga/qachon tugashini hisoblab beradi. Balans $100 (sozlanadigan,
  `budget_state.json` -> `alert_threshold_usd`) chegarasidan pastga tushsa,
  bot so'ramasangiz ham o'zi birinchi bo'lib Telegram'ga xabar yuboradi.
- ✅ **Kunlik avtomatik tahlil** — botni ishga tushirgandan keyin, har 24
  soatda `run_analysis_cycle()` o'zi ishga tushadi (Targetolog to'liq hisobni
  ko'rib chiqadi, kerak bo'lsa pause/resume/byudjet/`archive_campaign` kabi
  action'larni to'g'ridan-to'g'ri ijro etadi) va natijani Telegram'ga yuboradi
  — botni "review va publish qilib yurishi" shu orqali ishlaydi.
- ✅ **`archive_campaign`** — uzoq vaqt pauzada, kerak bo'lmagan kampaniyalarni
  arxivlaydi (o'chirish emas, Ads Manager'da qaytarib bo'ladi) — "keraksiz"larni
  tozalash uchun.

### Telegram'da qanday ishlatiladi (erkin matn orqali)

Bot har bir xabarni avtomatik turlarga ajratadi:
1. **Amaliy buyruq** ("yangi target yoq...", "X reklamani to'xtat", "abtest boshla") →
   to'liq Targetolog→Marketolog→ijro zanjiri ishga tushadi.
2. **Metrika savoli** ("video ko'rish % qancha", "bugun qancha xarajat bo'ldi",
   "rejalashtirilgan targetlar bormi") → Meta API'dan real ma'lumot tortib,
   qat'iy "ADMIN TARGET HISOBOTI" formatida javob beradi (`orchestrator.
   build_admin_report`).
3. **Umumiy savol** ("CBO nima", "byudjetni qachon oshirish kerak") → bilim
   bazasidan maslahat beradi, hisobga tegmaydi.
4. **Oylik hisobot** ("bir oylik hisobot ber", "iyul oyi hisoboti", "oylik
   pdf") → `monthly_report.py` orqali PDF hujjat sifatida yuboriladi: har
   bir target (kampaniya) alohida nomi/yo'nalishi/xarajat/natija/CPL/
   ko'rishlar/qamrov bilan, + umumiy oy xulosasi, oldingi davr bilan
   solishtirish, byudjet monitoring, kunlik jadval. MUHIM: bu yo'nalish
   HECH QANDAY AI (na OpenAI, na Anthropic) ishlatmaydi -- barcha raqamlar
   100% deterministik Python bilan hisoblanadi (arzonroq va aniqroq,
   avvalgi LLM-hisoblash xatolaridan keyin ataylab shunday qilingan).

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
pip install "python-telegram-bot[job-queue]" anthropic requests
```

(`[job-queue]` MUHIM — kunlik avtomatik tahlil va byudjet ogohlantirishi shunga tayanadi.)

### Kerakli ENV o'zgaruvchilar

| O'zgaruvchi | Qayerdan olinadi |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather |
| `ANTHROPIC_API_KEY` | console.anthropic.com -- Targetolog/Marketolog HAQIQIY qaror/vazifa yaratganda doim shu (Claude Sonnet) ishlatiladi |
| `OPENAI_API_KEY` (MAJBURIY) | platform.openai.com -- YENGIL so'rovlarning (intent aniqlash, metrika/sana savoli, erkin suhbat, byudjet xabari, kunlik oddiy hisobot) YAGONA manbasi. Sozlanmasa shu turdagi so'rovlar xato beradi -- Claude'ga fallback yo'q (ataylab, Anthropic xarajatini tejash uchun). |
| `OPENAI_MODEL` (ixtiyoriy) | standart `gpt-4o-mini` |
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

## Vercel'ga joylashtirish (webhook rejimi)

MVP endi ikki rejimda ishlay oladi:
- **`telegram_bot.py`** (eski, long-polling) — o'z serveringiz/VPS'da doimiy jarayon sifatida.
- **`api/index.py`** (yangi, webhook) — **Vercel** kabi serverless platformalar uchun. Quyida shu haqida.

### Nima o'zgardi

Vercel'da har bir so'rov alohida, qisqa muddatli funksiya sifatida ishlaydi — doimiy
jarayon (`run_polling()`, `JobQueue`) saqlab bo'lmaydi. Shu sababli:

- Telegram xabarlari endi **webhook** orqali keladi (`POST /api/webhook`), long-polling emas.
- "Har kuni" ishlaydigan tahlil va "har 4 soatda" byudjet tekshiruvi endi alohida
  cron endpoint'lar: `GET /api/cron/daily`, `GET /api/cron/budget`.
- Holat (suhbat tarixi, oxirgi hisobot, byudjet balansi) endi mahalliy faylda emas,
  **Vercel KV** (yoki mustaqil Upstash Redis)'da saqlanadi — `kv_store.py`.
- Kunlik hisobot endi faqat **diqqatga loyiq narsa bo'lsa** yuboriladi (nechta action
  bajarildi/xato berdi/qo'lda ko'rib chiqish kerak) — hammasi joyida bo'lsa, bo'sh
  xabar bilan bezovta qilinmaydi (`orchestrator.run_daily_cron_report`).

### Qadamlar

1. **Vercel loyihasi yarating** — bu repo'ni Vercel'ga ulang (GitHub import) yoki
   `vercel` CLI bilan (`vercel --prod`) joylashtiring.
2. **Vercel KV qo'shing** — loyiha -> Storage -> Create Database -> KV. Bu avtomatik
   `KV_REST_API_URL` / `KV_REST_API_TOKEN` environment variable'larini qo'shadi.
3. **Environment Variables** (Settings -> Environment Variables) — `.env.example`
   faylidagi hammasini kiriting: `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`,
   `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID`, `META_PAGE_ID` (ixtiyoriy), `CRON_SECRET`
   (o'zingiz o'ylab toping, masalan `openssl rand -hex 24`).
4. **Deploy** qiling.
5. **Telegram webhook'ni ro'yxatdan o'tkazing** (bir martalik, deploy domeningiz bilan):
   ```bash
   curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<domeningiz>.vercel.app/api/webhook"
   ```
6. Botga Telegram'da `/start` yozing — shu chat kunlik hisobot/ogohlantirish
   yuboriladigan chat sifatida saqlanadi.
7. `https://<domeningiz>.vercel.app/api/health` orqali barcha kerakli
   environment variable'lar to'g'ri o'rnatilganini tekshiring.

### Cron chastotasi haqida muhim eslatma

Vercel **Hobby (bepul) rejasida** cron faqat **kuniga bir marta** ishlaydi — `vercel.json`
shunga mos qilib faqat `/api/cron/daily` (soat 08:00) ni o'z ichiga oladi. Qolgan uchta
endpoint Hobby rejada Vercel Cron orqali ISHLAMAYDI — tashqi cron xizmati kerak:

- **`/api/cron/budget`** — byudjet balansini tekshiradi (Meta hisobga qancha pul
  qolgani, qachon tugashi). Yengil, tez-tez chaqirsa ham bo'ladi.
- **`/api/cron/watch`** — botning "o'zi doimiy kuzatib, muammo bo'lsa xabar berib/
  tuzatib turishi" shu orqali ishlaydi: `/api/cron/daily` bilan bir xil to'liq
  tahlil+avtomatik-tuzatish tsiklini ishga tushiradi (Targetolog hisobni ko'radi,
  kerak bo'lsa pause/resume/byudjet o'zgartirishni O'ZI bajaradi), lekin har
  soatda emas, siz belgilagan tez-tez oraliqda. Diqqatga loyiq narsa bo'lmasa
  jim turadi (spam qilmaydi).
- **`/api/cron/admin-report`** — har kuni belgilangan vaqtda (tavsiya: ertalab
  09:00, O'zbekiston vaqti) qat'iy "📊 ADMIN TARGET HISOBOTI" formatidagi qisqa
  hisobot yuboradi (xarajat/lead/xabar/CPL/CTR/CPC/CPM/impressions/reach/
  frequency + eng yaxshi/yomon kampaniya). Bu `/api/cron/daily`/`watch`dan
  FARQLI: hech qanday amal (pause/resume/byudjet) BAJARMAYDI, faqat hisobot,
  va FAQAT OpenAI orqali ishlaydi (Claude/Anthropic bu yerda umuman
  chaqirilmaydi — arzon).

Barchasini yoqish uchun:
- **Tavsiya (bepul):** [cron-job.org](https://cron-job.org)da ro'yxatdan o'ting va
  uchta alohida "cron job" yarating:
  - `https://<domeningiz>.vercel.app/api/cron/budget?secret=<CRON_SECRET>` — har 4 soatda
  - `https://<domeningiz>.vercel.app/api/cron/watch?secret=<CRON_SECRET>` — har 30-60
    daqiqada (tavsiya). Bundan tez-tez (masalan har 1-5 daqiqada) chaqirish ham mumkin,
    lekin har chaqiruv Meta API + kamida bitta Claude Sonnet chaqiruvi (pul sarflaydigan)
    talab qiladi — reklama natijalari daqiqama-daqiqa keskin o'zgarmagani uchun 30-60
    daqiqa odatda yetarli.
  - `https://<domeningiz>.vercel.app/api/cron/admin-report?secret=<CRON_SECRET>` —
    har kuni bir marta, soat **04:00 UTC** (= 09:00 O'zbekiston vaqti, UTC+5) qilib
    sozlang. Bu FAQAT OpenAI ishlatadi, shuning uchun tez-tez chaqirsangiz ham
    (masalan yana kunning boshqa vaqtida) katta xarajat qilmaydi.
- **Yoki:** Vercel **Pro** rejaga o'ting — shunda `vercel.json`ga
  `{"path": "/api/cron/watch", "schedule": "*/30 * * * *"}` va
  `{"path": "/api/cron/admin-report", "schedule": "0 4 * * *"}` (va xohlasangiz
  `/api/cron/budget` uchun ham shunga o'xshash qator) qo'shib, to'g'ridan-to'g'ri
  Vercel Cron orqali ishlatish mumkin.
