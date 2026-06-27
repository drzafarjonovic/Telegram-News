"""
Digest tayyorlash moduli.

Foydalanuvchi obuna bo'lgan kanallardan ma'lum oraliqdagi postlarni yig'adi,
AI yordamida mavzularga guruhlaydi va yuborishga tayyor matn qaytaradi.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from config import config
from app.db import repository as repo
from app import ai_analyzer

logger = logging.getLogger(__name__)

# Bitta postdan AI ga yuboriladigan maksimal belgi (juda uzunlarni qisqartirish)
_MAX_POST_LEN = 1500
# Telegram bitta xabar uchun chegara (~4096); xavfsiz bo'lish uchun
_TG_LIMIT = 3800


def _fmt_source(title: Optional[str], username: Optional[str]) -> str:
    if username:
        return f"@{username}"
    return title or "noma'lum kanal"


def _build_posts_block(posts) -> str:
    """Postlarni AI uchun bitta matn blokiga aylantiradi."""
    lines: list[str] = []
    for i, p in enumerate(posts, 1):
        source = _fmt_source(p["title"], p["username"])
        text = (p["text"] or "").strip()
        if len(text) > _MAX_POST_LEN:
            text = text[:_MAX_POST_LEN] + "…"
        lines.append(f"[{i}] Manba: {source}\n{text}\n")
    return "\n".join(lines)


def _chunk(posts, size: int):
    for i in range(0, len(posts), size):
        yield posts[i : i + size]


def _tashkent(dt: datetime) -> str:
    """UTC vaqtni foydalanuvchi mintaqasida formatlaydi."""
    try:
        tz = ZoneInfo(config.timezone)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%d.%m.%Y %H:%M")


async def build_digest(
    user_id: int, since: Optional[datetime], until: datetime
) -> Optional[dict]:
    """
    Foydalanuvchi uchun digest tayyorlaydi.

    Qaytaradi: {"content": str, "post_count": int} yoki None (post yo'q / xato).
    """
    posts = await repo.get_posts_for_user(user_id, since, until)
    if not posts:
        return None  # post yo'q -> jim qolamiz

    if ai_analyzer.analyzer is None:
        logger.error("AI analyzer ishga tushirilmagan.")
        return None

    # Chunking: ko'p post bo'lsa, bo'lib-bo'lib tahlil qilamiz
    chunk_size = config.max_posts_per_chunk
    parts: list[str] = []
    for chunk in _chunk(posts, chunk_size):
        block = _build_posts_block(chunk)
        result = await ai_analyzer.analyzer.analyze(block, user_id=user_id)
        if result:
            parts.append(result)

    if not parts:
        return None  # AI xatosi

    body = "\n\n".join(parts)

    # Sarlavha
    period = (
        f"{_tashkent(since)} — {_tashkent(until)}" if since else f"{_tashkent(until)} gacha"
    )
    header = (
        f"📰 <b>Yangiliklar mazmuni</b>\n"
        f"🕐 {period}\n"
        f"📊 {len(posts)} ta post tahlil qilindi\n"
        f"{'─' * 20}\n\n"
    )

    content = header + body
    return {"content": content, "post_count": len(posts)}


def split_for_telegram(text: str) -> list[str]:
    """Uzun digestni Telegram chegarasiga moslab bo'laklarga ajratadi."""
    if len(text) <= _TG_LIMIT:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > _TG_LIMIT:
            if current:
                chunks.append(current.rstrip())
            # Agar bitta paragraf juda uzun bo'lsa, majburiy kesamiz
            while len(paragraph) > _TG_LIMIT:
                chunks.append(paragraph[:_TG_LIMIT])
                paragraph = paragraph[_TG_LIMIT:]
            current = paragraph + "\n\n"
        else:
            current += paragraph + "\n\n"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks
