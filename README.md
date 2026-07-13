# 📰 Telegram-News Bot

Ko'p foydalanuvchili Telegram bot. Foydalanuvchilar kuzatmoqchi bo'lgan **ochiq kanallar** linkini yuboradi, bot esa belgilangan vaqt oralig'ida o'sha kanallardagi postlarni yig'ib, **sun'iy intellekt** yordamida **mavzular bo'yicha** guruhlaydi va mazmunini (digest) yuboradi.

## ✨ Imkoniyatlar

- 🔗 Istalgan **ochiq kanal** linkini qo'shish (`@kanal` yoki `https://t.me/kanal`)
- ⏰ Moslashuvchan vaqt: har **1/3/6/12/24 soatda** yoki har kuni **aniq vaqt(lar)da** (Toshkent vaqti)
- 🧠 AI postlarni **mavzularga** guruhlab, **manba kanal**ni ko'rsatib beradi
- 🔇 Yangi post bo'lmasa — bezovta qilmaydi
- 👑 To'liq **admin paneli**: statistika, foydalanuvchilar, audit, broadcast, kanallar, tizim holati, sozlamalar
- 🔄 AI provayderni almashtirish mumkin: **Groq** (standart), OpenAI, Gemini

## 🏗 Arxitektura

```
Foydalanuvchi ──► BOT (aiogram) ──► Supabase (Postgres)
                                          ▲
              USERBOT (Telethon) ─────────┘  (kanallarni realtime kuzatadi)
                                          │
              SCHEDULER (APScheduler) ────┘  (vaqt kelganda AI digest yuboradi)
                                          │
                                     AI (Groq)
```

| Qatlam | Texnologiya |
|--------|-------------|
| Bot | aiogram 3 |
| Userbot | Telethon |
| Baza | Supabase (PostgreSQL), asyncpg |
| Vaqt jadvali | APScheduler |
| AI | OpenAI-compatible (Groq / OpenAI / Gemini) |
| Deploy | Railway |

## 📁 Tuzilma

```
Telegram-News/
├── main.py              # ishga tushirish nuqtasi
├── login.py             # Telethon StringSession yaratish (bir martalik)
├── config.py            # .env sozlamalari
├── requirements.txt
├── Procfile / railway.json
└── app/
    ├── db/              # schema.sql, pool.py, repository.py
    ├── ai_analyzer.py   # AI (mavzularga guruhlash)
    ├── digest.py        # postlarni yig'ish + formatlash
    ├── userbot.py       # Telethon realtime kuzatuv
    ├── scheduler.py     # digest yuborish vaqti
    ├── runtime.py       # holat havolalari
    └── bot/             # handlers.py, admin_handlers.py, keyboards.py
```

---

## 🚀 O'rnatish

### 1. Talablarni o'rnatish

```bash
git clone https://github.com/drzafarjonovic/Telegram-News.git
cd Telegram-News
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Kerakli kalitlarni olish

| Kalit | Qayerdan |
|-------|----------|
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `API_ID`, `API_HASH` | [my.telegram.org](https://my.telegram.org) → API development tools |
| `DATABASE_URL` | [Supabase](https://supabase.com) → Project Settings → Database → Connection string (URI) |
| `AI_API_KEY` | [Groq Console](https://console.groq.com/keys) (bepul) |
| `ADMIN_IDS` | [@userinfobot](https://t.me/userinfobot) dan o'z ID'ngiz |

### 3. `.env` faylni sozlash

```bash
cp .env.example .env
# .env ni tahrirlab, yuqoridagi qiymatlarni to'ldiring
```

### 4. Supabase'da jadvallarni yaratish

Ikki yo'l bor:
- **Avtomatik:** botni birinchi ishga tushirsangiz, `app/db/schema.sql` avtomatik bajariladi.
- **Qo'lda:** Supabase → SQL Editor → `app/db/schema.sql` mazmunini joylab `Run` bosing.

### 5. Userbot sessiyasini yaratish (MUHIM)

Userbot sizning Telegram akkauntingiz orqali ochiq kanallarni o'qiydi. Sessiyani **lokal kompyuterda** bir marta yarating:

```bash
python login.py
```

Telefon raqami va Telegram koddi so'raladi. Chiqqan uzun **STRING_SESSION** satrini `.env` (yoki Railway Variables) ga `STRING_SESSION=...` qilib qo'ying.

> ⚠️ STRING_SESSION akkauntingizga to'liq kirish beradi — uni hech kimga bermang va commit qilmang (`.gitignore` da himoyalangan).

### 6. Ishga tushirish

```bash
python main.py
```

---

## ☁️ Railway'ga deploy

1. [Railway](https://railway.app) da yangi loyiha oching → **Deploy from GitHub repo** → `Telegram-News`.
2. **Variables** bo'limiga `.env` dagi barcha qiymatlarni qo'shing (`BOT_TOKEN`, `API_ID`, `API_HASH`, `STRING_SESSION`, `DATABASE_URL`, `AI_API_KEY`, `ADMIN_IDS`, ...).
   - ⚠️ `STRING_SESSION` ni oldindan (5-qadam) yarating — Railway'da interaktiv login ishlamaydi.
3. Railway `railway.json` / `Procfile` ni avtomatik o'qiydi va `python main.py` bilan ishga tushiradi.
4. Loglarni kuzating: `Hammasi ishga tushdi` xabari chiqsa — tayyor.

> 💡 Supabase uchun **Connection Pooling** (port `6543`) satrini ishlatish tavsiya etiladi.

---

## 🤖 Foydalanish

**Foydalanuvchi:**
| Buyruq | Vazifa |
|--------|--------|
| `/start` | Boshlash |
| `/add @kanal` | Kanal qo'shish (yoki shunchaki link yuboring) |
| `/list` | Kanallar ro'yxati |
| `/remove` | Kanalni o'chirish |
| `/time` | Digest vaqtini sozlash |
| `/help` | Yordam |

**Admin** (`ADMIN_IDS` dagilar):
| Buyruq | Vazifa |
|--------|--------|
| `/admin` | Statistika + boshqaruv menyusi |
| `/broadcast` | Barchaga e'lon yuborish |

Admin menyusidagi tugmalar orqali: 👥 foydalanuvchilar (profil, ban, limit), 📡 kanallar, 📜 audit, 🩺 tizim holati, ⚙️ sozlamalar.

---

## 🔧 AI provayderni almashtirish

`.env` da:

```env
AI_PROVIDER=groq      # groq | openai | gemini
AI_API_KEY=...
AI_MODEL=             # bo'sh bo'lsa standart model ishlatiladi
```

| Provayder | Standart model | Bepulmi |
|-----------|----------------|---------|
| `groq` | llama-3.3-70b-versatile | ✅ |
| `gemini` | gemini-2.0-flash | ✅ |
| `openai` | gpt-4o-mini | ❌ |

---

## ⚠️ Eslatmalar

- Faqat **ochiq** kanallar qo'llab-quvvatlanadi (yopiq kanal uchun userbot akkaunti a'zo bo'lishi kerak).
- Barcha kanallar bitta userbot akkaunti orqali kuzatiladi — Telegram bitta akkaunt uchun ~500 kanal cheklovini qo'yadi.
- Postlar 7 kundan keyin avtomatik tozalanadi (`scheduler.py`).


---

## 🧩 Faza 1 — Cache pipeline & barqarorlik

Bot endi **2-bosqichli** ishlaydi (token tejash + personalizatsiya):

**Bosqich A (umumiy, har yangilik uchun 1 marta):**
1. Yangi postlar `Jaccard` o'xshashligi orqali **dublikatlar**ga tekshiriladi (Kun.uz, Daryo va h.k. dagi bir xil yangilik birlashtiriladi).
2. Har bir noyob yangilik (story) uchun AI **bir marta** ishlaydi va natijani cache'laydi:
   - 📝 mazmun · 📁 kategoriya · 🔥 muhimlik (1-5) · 🟢 sentiment
3. Natija `stories` jadvalida saqlanadi.

**Bosqich B (shaxsiy, AI'siz):**
- Foydalanuvchining digesti tayyor cache'dan yig'iladi → **70-95% token tejaladi**.

**Qo'shimcha barqarorlik:**
- 🔁 **AI fallback**: asosiy provayder ishlamasa, avtomatik keyingisiga o'tadi (`AI_FALLBACKS`).
- 🩺 **Kanal health check**: har 6 soatda kanallar tekshiriladi (o'chirilgan / yopiq / username o'zgargan) va adminlar ogohlantiriladi.

### Faza 1 uchun qo'shimcha Variables (ixtiyoriy)

| Variable | Standart | Izoh |
|----------|----------|------|
| `AI_FALLBACKS` | *(bo'sh)* | Zaxira provayderlar, masalan `gemini,openai` |
| `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` | *(bo'sh)* | Fallback provayderlar kalitlari |
| `DEDUP_SIMILARITY` | `0.5` | Dublikat chegarasi (Jaccard, 0..1) |
| `PROCESS_BATCH_SIZE` | `25` | Har siklda qayta ishlanadigan post soni |

> 💡 Fallback ishlatish uchun: `AI_FALLBACKS=gemini` qo'ying va `GEMINI_API_KEY` ni to'ldiring.


---

## 🚀 Enterprise v2.0 — xabarlarni yo'qotmasdan yig'ish

Bu versiya botni “xabar yo'qolmaydi” prinsipi asosida qayta qurdi. Asosiy yangiliklar:

### 1. Ingest pipeline (navbat + workerlar)
Kiruvchi hodisalar (`events.NewMessage`, `events.Album`) darhol `asyncio.Queue`ga
yoziladi; bir nechta asinxron worker (`INGEST_WORKERS`) ularni olib idempotent
tarzda bazaga saqlaydi. Navbat to'lsa — backpressure (joy bo'shaguncha kutish).
Modul: `app/ingest.py`.

### 2. Kengaytirilgan DB sxemasi
`app/db/schema.sql` (idempotent, mavjud bazaga xavfsiz qo'llanadi):
- **raw_messages** — har xabarning xom JSON nusxasi (`UNIQUE(tg_channel_id, tg_message_id)`).
- **posts** yangi ustunlar: `caption`, `has_media`, `grouped_id`, `is_forwarded`,
  `fwd_from_channel`, `reply_to_message_id`, `edited_at`, `deleted_at`, `ocr_text`, `transcript`.
- **media** — media metadata (`UNIQUE(channel_id, tg_message_id, unique_file_id)`).
- **processing_logs** — har bosqich (ingest/ocr/whisper) auditi.

### 3. Idempotentlik
`posts` UNIQUE(channel_id, tg_message_id) + `ON CONFLICT` — bir xil xabar
realtime va backfill orqali kelsa ham dublikat bo'lmaydi.

### 4. Album, forward va reply
Albomlar `events.Album` orqali bitta hodisa sifatida olinadi; caption
(`message.message`/`raw_text`), forward (`fwd_from`) va reply (`reply_to_msg_id`)
ma'lumotlari saqlanadi. Endi media-only postlar ham (caption bilan) yig'iladi.

### 5. Backfill (GetHistory)
Startup'da va har `BACKFILL_INTERVAL_MIN` daqiqada har kanaldan oxirgi saqlangan
`tg_message_id`dan keyingi xabarlar (`iter_messages(min_id=...)`) olinadi —
bot o'chiq bo'lgan davrdagi bo'shliqlar to'ldiriladi.

### 6. Tahrir / o'chirish kuzatuvi
`MessageEdited` → matn yangilanadi va qayta tahlilga belgilanadi; `MessageDeleted`
→ `deleted_at` (tomb-stone), o'chirilgan postlar digestlarga tushmaydi.

### 7. OCR + Speech-to-Text (ixtiyoriy)
`app/media.py`: rasmlar uchun `pytesseract` (OCR), audio uchun Whisper API.
Har ikkisi ham ixtiyoriy va sekin degradatsiya qiladi (kutubxona/kalit bo'lmasa
bot ishlayveradi). `OCR_ENABLED` / `STT_ENABLED` bilan yoqiladi.

### 8. FloodWait bardoshliligi
`app/tg_utils.py` → `safe_call(...)` API chaqiruvlarini FloodWait bilan xavfsiz
bajaradi (`asyncio.sleep(e.seconds)` + retry).

### 9. Monitoring (Prometheus + Grafana)
`app/metrics.py` — tashqi kutubxonasiz `/metrics` (Prometheus formati) va
`/healthz`. Metrikslar: qabul/qayta ishlangan/tashlangan xabarlar, navbat
uzunligi, faol workerlar, OCR/STT, backfill, tahrir/o'chirish, FloodWait.
Prometheus scrape target: `http://<host>:9101/metrics`.

### Konteynerizatsiya
`Dockerfile` (python:3.11-slim + tesseract) autoscaling/deploy uchun.

Batafsil o'zgarishlar ro'yxati: **ENTERPRISE_V2_CHANGELOG.md**.
