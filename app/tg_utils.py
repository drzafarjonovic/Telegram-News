"""Telethon yordamchi funksiyalari — FloodWait bilan xavfsiz chaqiruv (Enterprise v2.0)."""
from __future__ import annotations

import asyncio
import logging

from telethon.errors import FloodWaitError

from app import metrics

logger = logging.getLogger(__name__)

_MAX_WAIT = 300  # sekund — juda uzun kutishlarni cheklaymiz


async def safe_call(factory, *, retries: int = 3, default=None):
    """
    Berilgan async chaqiruvni (`factory`: () -> coroutine) FloodWait bilan
    xavfsiz bajaradi. FloodWait bo'lsa `e.seconds` kutadi va qayta urinadi.
    Boshqa xatoda `default` qaytaradi (bot uzilmaydi).

    Namuna:
        entity = await safe_call(lambda: client.get_entity(username))
    """
    for attempt in range(1, retries + 1):
        try:
            return await factory()
        except FloodWaitError as exc:
            metrics.floodwait_total.inc()
            wait = min(int(getattr(exc, "seconds", 5)), _MAX_WAIT)
            logger.warning(
                "FloodWait: %ss kutilyapti (urinish %d/%d).", wait, attempt, retries
            )
            await asyncio.sleep(wait + 1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("safe_call xatosi: %s", exc)
            return default
    return default
