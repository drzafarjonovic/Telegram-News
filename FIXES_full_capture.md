# Tuzatishlar — "Barcha xabarni qamrab olish" (v3.4)

Maqsad: har turdagi Telegram xabari (oddiy matn, caption, captionsiz rasm,
ovoz/audio/video, video_note, gif) matnga aylantirilib AI tahlilga va digestga
tushsin. O'chirilgan postlar esa umuman chiqmasin.

## O'zgargan fayllar

### 1) `app/db/repository.py`
- **`get_unprocessed_posts`** — endi tahlil matni `text + ocr_text + transcript`
  birlashtirilib olinadi (`concat_ws`). Qo'shildi:
  - `deleted_at IS NULL` — o'chirilgan postlar chiqmaydi (JIDDIY #1 tuzatildi).
  - Media "freshness gate": media post OCR/STT tugashiga ulgurishi uchun yo
    ajratilgan matnga ega bo'ladi, yo 60 soniya kutiladi. Matnsiz media ham
    qaytariladi (process bosqichida "skip" qilinadi, cheksiz qayta skaner yo'q).
- **`get_stories_for_user`** — `JOIN posts p ... AND p.deleted_at IS NULL`.
  Ya'ni allaqachon story'ga aylangan post keyin o'chirilsa ham digestga chiqmaydi.
- **`append_post_text_extra`** — OCR/transkript qo'shilganda post
  `processed = FALSE, story_id = NULL` qilinadi. Shu bois kech kelgan OCR/STT
  natijasi ham albatta qayta tahlilга tushadi (hech narsa yo'qolmaydi).

### 2) `app/processing.py`
- **`process_new_posts`** — matni bo'sh post (captionsiz media, OCR/STT o'chiq/xato)
  endi story yaratmasdan "qayta ishlangan" deb belgilanadi. Birlashtirilgan matn
  (text+ocr+transcript) to'g'ridan-to'g'ri AI tahliliga uzatiladi (JIDDIY #2 tuzatildi).

### 3) `app/ingest.py`
- STT endi `voice, audio, video, video_note, gif` uchun ishlaydi (avval faqat
  voice/audio edi). Transkripsiyaga to'g'ri fayl nomi (`video.mp4` / `audio.ogg`)
  uzatiladi.

### 4) `config.py`
- `OCR_LANGS` standarti `uzb+rus+eng` (avval `eng` edi — kirill/o'zbekni o'qimasdi).

### 5) `Dockerfile`
- tesseract til paketlari qo'shildi: `rus`, `uzb`, `uzb-cyrl` + `ffmpeg`.

### 6) `requirements.txt`
- `pytesseract` va `Pillow` majburiy qilib yoqildi (OCR uchun).

### 7) `.env.example`
- To'liq qamrov uchun standartlar: `OCR_ENABLED=true`, `OCR_LANGS=uzb+rus+eng`,
  `STT_ENABLED=true`, `STT_BASE_URL=https://api.groq.com/openai/v1`,
  `STT_MODEL=whisper-large-v3`, `MEDIA_DOWNLOAD_MAX_MB=20`.

## Ishga tushirishdan oldin
- `.env` da AI_API_KEY (Groq bepul) to'ldirilgan bo'lsa, STT ham shu kalitni
  ishlatadi (alohida STT_API_KEY shart emas).
- Docker image qayta build qilinishi kerak (tesseract til paketlari uchun).
- STT pullik bo'lishi mumkin (Groq hozircha bepul whisper-large-v3 beradi).

### 8) `app/userbot.py` + `config.py` — BACKFILL bo'shlig'i tuzatildi
- **`_backfill_channel`** endi ikki rejimda ishlaydi:
  - Yangi kanal (last_id=0): eng so'nggi `BACKFILL_LIMIT` ta post (avvalgidek).
  - Mavjud kanal (last_id>0): `min_id=last_id, reverse=True` bilan bo'shliqdagi
    BARCHA yangi postlar eskidan-yangiga olinadi. Telethon avtomatik sahifalaydi,
    `limit` cheklovi yo'q — shu bois faol kanalda ham post tushib qolmaydi.
- Yangi sozlama `BACKFILL_MAX_TOTAL` (default 0 = cheksiz) — xohlasangiz bir
  siklda maks xabar sonini cheklaydigan xavfsizlik shifti.

## Bu tuzatishда QAMRALMAGAN (alohida masalalar, ixtiyoriy)
- Dedup chegarasi 0.5 (false-merge xavfi) — 0.6 tavsiya.
- Digest vaqt belgilari doim server tz (`config.timezone`).
- pool.py TLS tekshiruvi o'chiq (xavfsizlik).
Bularni ham xohlasangiz, aytsangiz tuzataman.
