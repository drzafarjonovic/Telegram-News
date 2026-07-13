# 🚀 Telegram News Bot — Interfeys v3.0

Bu versiya foydalanuvchi interfeysini to'liq yangiladi va AI kalitlar bilan
ishlashni sezilarli darajada kuchaytirdi. Ma'lumotlar bazasi o'zgarishlari
`schema.sql` orqali **avtomatik** qo'llanadi (idempotent — mavjud ma'lumotlar
saqlanadi).

## ✨ Yangi interfeys

### 🏠 Soddalashtirilgan navigatsiya
- Pastda faqat bitta doimiy **🏠 Menyu** tugmasi.
- Barcha bo'limlar bitta inline menyu ichida, o'sha xabarning o'zida yangilanadi
  (chat toza qoladi). Har bo'limda **⬅️ Orqaga / Menyu** tugmasi bor.

### 🧭 Qadamli boshlang'ich sozlash (onboarding)
- Yangi foydalanuvchi `/start` bosganda 3 qadamli yordamchi ishga tushadi:
  1️⃣ Kanal qo'shish → 2️⃣ Qiziqishlar → 3️⃣ Yuborish oralig'i.
- Har qadamni o'tkazib yuborish mumkin.

### 📋 Kanal kartochkasi + xavfsiz o'chirish
- Kanal ustiga bosilganda kartochka ochiladi: nomi, @username, postlar soni,
  oxirgi post vaqti, holati (🟢/🟡/🔴).
- O'chirishdan oldin **tasdiqlash** so'raladi (✅ Ha / ❌ Yo'q) — tasodifiy
  o'chirishning oldi olinadi.
- Bir nechta kanalni birdaniga qo'shish mumkin (har birini alohida qatorga).

### 📬 Hozir yuborish
- Digestni jadvalni kutmasdan darhol olish. Spamdan himoya uchun cheklov
  (`MANUAL_DIGEST_COOLDOWN_MIN`, standart 10 daqiqa).

## ⏰ Aqlli yuborish tizimi
- **Ko'proq oraliqlar:** 30 daq, 45 daq, 1/2/3/6/8/12/24 soat.
- **🧠 Aqlli rejim:** jadvaldan oldin ham, yetarlicha (standart 5+) muhim
  yangilik yig'ilsa, digest avtomatik yuboriladi.
- **🚫 Bo'sh digest yubormaslik:** yangilik bo'lmasa bezovta qilmaydi (standart).
- **📅 Dam olish jadvali:** shanba/yakshanba uchun alohida oraliq.
- **⚡ Shoshilinch (breaking):** eng muhim (importance=5) yangiliklar darhol,
  alohida yuboriladi.
- **🌙 Jim soatlar:** belgilangan oraliqda (standart 23:00–07:00) oddiy
  digestlar kechiktiriladi. ❗ Shoshilinch xabarlar jim soatlarni ham yorib
  o'tadi — juda muhim yangilik tunda ham keladi.

## 🔑 AI kalitlar pooli (round-robin + cooldown)
- Har provayderga **bir nechta API kalit** qo'shsa bo'ladi (vergul bilan):
  `GROQ_API_KEY=k1,k2,k3`, `GEMINI_API_KEY=a,b`.
- **Aralash (mixed) pool** — barcha Groq + Gemini kalitlari bitta navbatga
  qo'shilib, so'rovlar teng taqsimlanadi (round-robin).
- Limitga (429 / quota) uchragan kalit avtomatik **vaqtincha dam**ga qo'yiladi
  (server `Retry-After` yoki `AI_COOLDOWN_SEC`), so'rov darhol keyingi kalitga
  o'tadi. Barcha kalit band bo'lsa — dam olayotganlari oxirgi chora sifatida
  sinaladi.
- Bitta kalit bilan ham avvalgidek ishlaydi (to'liq orqaga moslik).

## 🗄 Ma'lumotlar bazasi (avtomatik migratsiya)
- `schedules`: `interval_minutes`, `smart_mode`, `smart_min_stories`,
  `skip_empty`, `breaking_enabled`, `quiet_enabled`, `quiet_start`, `quiet_end`,
  `weekend_enabled`, `weekend_mode`, `weekend_interval_minutes`,
  `weekend_daily_times`.
- `users`: `onboarded`, `last_manual_digest_at`.
- Yangi jadval: `breaking_deliveries` (shoshilinch xabar takrorlanmasligi uchun).

## 🔧 Yangi .env sozlamalari
```
AI_POOL_MODE=mixed            # mixed | priority
AI_COOLDOWN_SEC=60
MANUAL_DIGEST_COOLDOWN_MIN=10
```

## 🚀 Yangilash tartibi
1. Fayllarni GitHub'ga (main branch) yuklang.
2. Serverda:
   ```bash
   cd ~/Telegram-News
   git reset --hard origin/main
   source venv/bin/activate
   pip install -r requirements.txt
   sudo systemctl restart telegram-news
   ```
3. DB ustunlari bot ishga tushganda avtomatik qo'shiladi.
