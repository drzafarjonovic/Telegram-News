"""
Media qayta ishlash (Enterprise v2.0) — OCR (rasm) va Speech-to-Text (audio).

Ikkalasi ham IXTIYORIY va sekin degradatsiya qiladi:
  • Kutubxona/kalit bo'lmasa yoki xatolik bo'lsa — None qaytaradi, bot ishlayveradi.
  • OCR: pytesseract + Pillow (lokal, tizimda `tesseract-ocr` o'rnatilgan bo'lishi kerak).
  • STT: OpenAI-compatible Whisper API (config.stt_*). Alohida kutubxona shart emas —
    mavjud `openai` SDK ishlatiladi.
"""
from __future__ import annotations

import asyncio
import io
import logging

from config import config

logger = logging.getLogger(__name__)

_ocr_ready: bool | None = None


def _ocr_available() -> bool:
    global _ocr_ready
    if _ocr_ready is None:
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401

            _ocr_ready = True
        except Exception:  # noqa: BLE001
            _ocr_ready = False
            logger.info(
                "OCR kutubxonalari topilmadi (pytesseract/Pillow) — OCR o'chirildi."
            )
    return _ocr_ready


async def run_ocr(image_bytes: bytes) -> str | None:
    """Rasm baytlaridan matn ajratadi. OCR o'chiq/mavjud emas bo'lsa None."""
    if not config.ocr_enabled or not image_bytes or not _ocr_available():
        return None

    def _work() -> str:
        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(img, lang=config.ocr_langs)

    try:
        text = await asyncio.to_thread(_work)  # bloklovchi ishni alohida ipda
        text = (text or "").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR xatosi: %s", exc)
        return None


async def run_transcription(audio_bytes: bytes, filename: str = "audio.ogg") -> str | None:
    """Audio baytlarini matnga aylantiradi (Whisper API). O'chiq bo'lsa None."""
    if not config.stt_enabled or not audio_bytes:
        return None
    key = config.stt_api_key or config.ai_api_key
    if not key:
        return None
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=key, base_url=config.stt_base_url or None)
        resp = await client.audio.transcriptions.create(
            model=config.stt_model,
            file=(filename, io.BytesIO(audio_bytes)),
        )
        text = (getattr(resp, "text", "") or "").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Speech-to-text xatosi: %s", exc)
        return None
