"""
Ingest pipeline (Enterprise v2.0) — producer/consumer navbat tizimi.

Userbot hodisalari (NewMessage, Album, backfill) IngestJob sifatida navbatga
yoziladi; bir nechta asinxron worker ularni olib, idempotent tarzda bazaga
saqlaydi (raw_messages, posts, media) va ixtiyoriy OCR/Whisper bajaradi.

Idempotentlik kafolati:
  • posts.UNIQUE(channel_id, tg_message_id) + ON CONFLICT
  • raw_messages.UNIQUE(tg_channel_id, tg_message_id)
  • media.UNIQUE(channel_id, tg_message_id, unique_file_id)
Shu bilan bir xil xabar qayta kelsa (realtime + backfill) ham dublikat
yaratilmaydi — xabarlar yo'qolmaydi va ikkilanmaydi.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from config import config
from app import media, metrics
from app.db import repository as repo

logger = logging.getLogger(__name__)


@dataclass
class IngestJob:
    kind: str                    # 'message' | 'album'
    messages: list               # telethon Message obyektlari
    db_channel_id: int
    tg_channel_id: int
    grouped_id: int | None = None
    source: str = "realtime"     # 'realtime' | 'backfill'
    enqueued_at: float = field(default_factory=time.monotonic)


def _media_info(msg):
    """(media_type, unique_id) — Telethon message'dan media turini aniqlaydi."""
    try:
        if msg.photo:
            return "photo", getattr(msg.photo, "id", None)
        if getattr(msg, "voice", None):
            return "voice", getattr(msg.document, "id", None)
        if getattr(msg, "video_note", None):
            return "video_note", getattr(msg.document, "id", None)
        if getattr(msg, "gif", None):
            return "gif", getattr(msg.document, "id", None)
        if getattr(msg, "video", None):
            return "video", getattr(msg.document, "id", None)
        if getattr(msg, "audio", None):
            return "audio", getattr(msg.document, "id", None)
        if getattr(msg, "sticker", None):
            return "sticker", getattr(msg.document, "id", None)
        if msg.document:
            return "document", getattr(msg.document, "id", None)
    except Exception:  # noqa: BLE001
        pass
    return "other", None


def _fwd_from(msg) -> str | None:
    """Forward qilingan xabar manbasini matn sifatida qaytaradi."""
    fwd = getattr(msg, "fwd_from", None)
    if not fwd:
        return None
    name = getattr(fwd, "from_name", None)
    if name:
        return str(name)
    from_id = getattr(fwd, "from_id", None)
    return str(from_id) if from_id else None


class IngestPipeline:
    def __init__(self, client) -> None:
        self.client = client
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=config.ingest_queue_max)
        self.worker_count = max(1, config.ingest_workers)
        self._workers: list[asyncio.Task] = []
        self._max_media = config.media_download_max_mb * 1024 * 1024

    # ---- lifecycle ----
    def start(self) -> None:
        for i in range(self.worker_count):
            self._workers.append(asyncio.create_task(self._worker(i)))
        metrics.workers_active.set(self.worker_count)
        logger.info("Ingest pipeline: %d worker ishga tushdi.", self.worker_count)

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        self._workers.clear()
        metrics.workers_active.set(0)

    async def enqueue(self, job: IngestJob) -> None:
        """Jobni navbatga qo'yadi. Navbat to'lsa — joy bo'shaguncha kutadi (backpressure)."""
        if self.queue.full():
            metrics.messages_dropped.inc(len(job.messages))
            logger.warning(
                "Ingest navbati to'ldi (%d) — backpressure, kutilyapti.",
                self.queue.maxsize,
            )
        await self.queue.put(job)
        metrics.queue_depth.set(self.queue.qsize())

    # ---- workers ----
    async def _worker(self, idx: int) -> None:
        while True:
            job = await self.queue.get()
            try:
                for msg in job.messages:
                    await self._process_message(job, msg)
                metrics.messages_processed.inc(len(job.messages))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                metrics.ingest_errors.inc()
                logger.exception("Worker %d xatosi: %s", idx, exc)
            finally:
                self.queue.task_done()
                metrics.queue_depth.set(self.queue.qsize())

    async def _process_message(self, job: IngestJob, msg) -> None:
        text = msg.message or ""        # == raw_text (formatlanmagan)
        has_media = msg.media is not None

        # 1) Raw JSON (ixtiyoriy audit / qayta ishlash)
        if config.store_raw:
            try:
                await repo.insert_raw_message(
                    channel_id=job.db_channel_id,
                    tg_channel_id=job.tg_channel_id,
                    tg_message_id=msg.id,
                    raw_json=msg.to_json(),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("raw_message saqlanmadi: %s", exc)

        # 2) Post (idempotent upsert). Faqat matnli emas — media captionlari ham.
        grouped_id = job.grouped_id or getattr(msg, "grouped_id", None)
        caption = text if (has_media and text) else None
        post = await repo.upsert_post(
            channel_id=job.db_channel_id,
            tg_message_id=msg.id,
            text=text,
            posted_at=msg.date,
            caption=caption,
            has_media=has_media,
            grouped_id=grouped_id,
            is_forwarded=getattr(msg, "fwd_from", None) is not None,
            fwd_from_channel=_fwd_from(msg),
            reply_to_message_id=getattr(msg, "reply_to_msg_id", None),
        )
        post_id = post["id"]
        await repo.log_processing(post_id, job.db_channel_id, "ingest", "success")

        # 3) Media metadata + ixtiyoriy OCR/STT
        if has_media:
            await self._handle_media(job, msg, post_id)

    async def _handle_media(self, job: IngestJob, msg, post_id: int) -> None:
        media_type, unique_id = _media_info(msg)
        try:
            await repo.insert_media(
                post_id=post_id,
                channel_id=job.db_channel_id,
                tg_message_id=msg.id,
                file_id=str(unique_id) if unique_id else None,
                unique_file_id=str(unique_id) if unique_id else None,
                media_type=media_type,
                caption=msg.message or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("media metadata saqlanmadi: %s", exc)

        need_ocr = config.ocr_enabled and media_type == "photo"
        need_stt = config.stt_enabled and media_type in (
            "voice", "audio", "video", "video_note", "gif",
        )
        if not (need_ocr or need_stt):
            return

        data = await self._download(msg)
        if not data:
            return

        if need_ocr:
            try:
                ocr = await media.run_ocr(data)
                if ocr:
                    await repo.append_post_text_extra(post_id, ocr_text=ocr)
                    await repo.log_processing(post_id, job.db_channel_id, "ocr", "success")
                    metrics.ocr_total.inc()
            except Exception as exc:  # noqa: BLE001
                await repo.log_processing(post_id, job.db_channel_id, "ocr", "error", str(exc)[:200])

        if need_stt:
            try:
                fname = "audio.ogg" if media_type in ("voice", "audio") else "video.mp4"
                txt = await media.run_transcription(data, filename=fname)
                if txt:
                    await repo.append_post_text_extra(post_id, transcript=txt)
                    await repo.log_processing(post_id, job.db_channel_id, "whisper", "success")
                    metrics.stt_total.inc()
            except Exception as exc:  # noqa: BLE001
                await repo.log_processing(post_id, job.db_channel_id, "whisper", "error", str(exc)[:200])

    async def _download(self, msg) -> bytes | None:
        size = getattr(getattr(msg, "file", None), "size", None) or 0
        if size and size > self._max_media:
            logger.debug("Media juda katta (%d bayt) — o'tkazib yuborildi.", size)
            return None
        try:
            return await self.client.download_media(msg, file=bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Media yuklab olinmadi: %s", exc)
            return None
