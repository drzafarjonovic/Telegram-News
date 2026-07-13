# Enterprise v2.0 — o'zgarishlar ro'yxati

Bu yangilanish botni “xabar yo'qolmaydi” (zero message loss) prinsipiga o'tkazadi.
Barcha o'zgarishlar mavjud arxitektura (aiogram bot + Telethon userbot + PostgreSQL
+ APScheduler + AI digest) bilan mos va ortga qarab (backward-compatible) ishlaydi.

## Yangi fayllar
| Fayl | Vazifasi |
|------|----------|
| `app/ingest.py` | Producer/consumer ingest pipeline: `asyncio.Queue` + workerlar, idempotent saqlash, media/OCR/STT dispetcheri. |
| `app/media.py` | Ixtiyoriy OCR (pytesseract) va Speech-to-Text (Whisper API). Sekin degradatsiya qiladi. |
| `app/metrics.py` | Tashqi kutubxonasiz Prometheus-formatdagi `/metrics` + `/healthz` HTTP eksporti. |
| `app/tg_utils.py` | `safe_call(...)` — FloodWait bilan xavfsiz Telethon chaqiruvi (retry). |
| `Dockerfile` | python:3.11-slim + tesseract, autoscaling/deploy uchun. |

## O'zgartirilgan fayllar
| Fayl | O'zgarish |
|------|-----------|
| `app/db/schema.sql` | `raw_messages`, `media`, `processing_logs` jadvallari; `posts`ga `caption/has_media/grouped_id/is_forwarded/fwd_from_channel/reply_to_message_id/edited_at/deleted_at/ocr_text/transcript`; `channels.last_backfilled_at`. Hammasi `IF NOT EXISTS` — idempotent. |
| `app/db/repository.py` | Yangi funksiyalar: `insert_raw_message`, `upsert_post`, `insert_media`, `append_post_text_extra`, `mark_post_edited`, `mark_post_deleted`, `get_max_message_id`, `set_channel_backfilled`, `log_processing`. |
| `app/userbot.py` | To'liq qayta yozildi: NewMessage/Album/MessageEdited/MessageDeleted handlerlari, ingest navbatiga yo'naltirish, backfill (`iter_messages(min_id=...)`), FloodWait bardoshli `add_channel`. |
| `config.py` | Yangi sozlamalar: INGEST_WORKERS, INGEST_QUEUE_MAX, STORE_RAW_MESSAGES, BACKFILL_*, OCR_*, STT_*, MEDIA_DOWNLOAD_MAX_MB, METRICS_*. |
| `main.py` | Metrics server, ingest workerlar va startup backfill ishga tushirish. |
| `app/scheduler.py` | Davriy backfill job (`BACKFILL_INTERVAL_MIN`). |
| `requirements.txt`, `.env.example`, `README.md` | Yangi (ixtiyoriy) bog'liqliklar, env namunalari va hujjat. |

## Reja bandlariga muvofiqlik
1. Event-ingestion → navbat + workerlar — `app/ingest.py`, `app/userbot.py`. ✅
2. Navbat mexanizmi (producer/consumer, backpressure, FloodWait) — `app/ingest.py`, `app/tg_utils.py`. ✅
3. DB sxemasi kengaytmasi (raw_messages/media/processing_logs, ON CONFLICT) — `schema.sql`, `repository.py`. ✅
4. Album + caption + media-only postlar — `_on_album`, `_process_message`. ✅
5. GetHistory/backfill (startup + davriy) — `backfill_all`, scheduler. ✅
6. Tahrir/o'chirish + forward/reply — `mark_post_edited`, `mark_post_deleted`, `_fwd_from`. ✅
7. OCR + Whisper — `app/media.py`. ✅ (ixtiyoriy)
8. Retry + idempotentlik — UNIQUE + ON CONFLICT, `processing_logs`. ✅
9. Load testing + monitoring — `app/metrics.py` (Prometheus/Grafana), Dockerfile. ✅ (metrikslar tayyor)

## Migratsiya
Alohida qadam shart emas: `init_db()` startup'da `schema.sql`ni ishga tushiradi,
barcha DDL idempotent (`IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`). Mavjud
ma'lumotlarga zarar yetmaydi.

## Eslatma
- OCR uchun tizimda `tesseract-ocr` + `pip install pytesseract Pillow` kerak (Dockerfile'da bor).
- OCR/STT default o'chiq (`false`); yoqmaguningizcha resurs sarflamaydi.
- Grafana dashboard va AlertManager qoidalari deploy muhitida sozlanadi (metrikslar `/metrics`da tayyor).
