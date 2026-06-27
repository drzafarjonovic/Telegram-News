"""
Digest tayyorlash moduli — BOSQICH B (shaxsiy, AI'siz).

Bosqich A allaqachon postlarni "story"larga aylantirib, AI tahlilini
cache'lab qo'ygan. Bu modul shunchaki foydalanuvchi obuna bo'lgan kanallardagi
tayyor storylarni olib, kategoriya bo'yicha guruhlab, muhimlik va manba bilan
formatlaydi. AI CHAQIRILMAYDI — tez va token tejamkor.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from config import config
from app.db import repository as repo

logger = logging.getLogger(__name__)

# Telegram bitta xabar uchun chegara (~4096); xavfsiz bo'lish uchun
_TG_LIMIT = 3800

_SENTIMENT_EMOJI = {"positive": "🟢", "negative": "🔴", "neutral": "⚪️"}
_SENTIMENT_UZ = {"positive": "ijobiy", "negative": "salbiy", "neutral": "betaraf"}


def _tashkent(dt: datetime) -> str:
    """UTC vaqtni foydalanuvchi mintaqasida formatlaydi."""
    try:
        tz = ZoneInfo(config.timezone)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%d.%m.%Y %H:%M")


def _importance_mark(importance: int) -> str:
    stars = "⭐" * max(1, min(5, importance))
    flag = "🔥" if importance >= 4 else "▫️"
    return f"{flag} {stars}"


def _format_story(story) -> str:
    summary = (story["summary"] or "").strip()
    sources = story["sources"] or []
    sources_str = ", ".join(s for s in sources if s) or "—"
    sentiment = story["sentiment"] or "neutral"
    sent_emoji = _SENTIMENT_EMOJI.get(sentiment, "⚪️")
    sent_uz = _SENTIMENT_UZ.get(sentiment, "betaraf")
    return (
        f"{_importance_mark(story['importance'])}\n"
        f"{summary}\n"
        f"{sent_emoji} {sent_uz} · <i>Manba: {sources_str}</i>\n"
    )


async def build_digest(
    user_id: int, since: Optional[datetime], until: datetime
) -> Optional[dict]:
    """
    Foydalanuvchi uchun cache'langan storylardan digest tayyorlaydi.
    Qaytaradi: {"content": str, "post_count": int} yoki None (yangilik yo'q).
    """
    stories = await repo.get_stories_for_user(user_id, since, until)
    if not stories:
        return None  # yangilik yo'q -> jim qolamiz

    # Kategoriya bo'yicha guruhlash (kirish muhimlik bo'yicha tartiblangan,
    # shuning uchun eng muhim kategoriya birinchi keladi)
    groups: dict[str, list] = {}
    order: list[str] = []
    for st in stories:
        cat = st["category"] or "Boshqa"
        if cat not in groups:
            groups[cat] = []
            order.append(cat)
        groups[cat].append(st)

    period = (
        f"{_tashkent(since)} — {_tashkent(until)}" if since else f"{_tashkent(until)} gacha"
    )
    parts = [
        "📰 <b>Yangiliklar mazmuni</b>",
        f"🕐 {period}",
        f"📊 {len(stories)} ta yangilik",
        "─" * 20,
    ]
    for cat in order:
        parts.append(f"\n📁 <b>{cat}</b>")
        for st in groups[cat]:
            parts.append(_format_story(st))

    content = "\n".join(parts)
    return {"content": content, "post_count": len(stories)}


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
            while len(paragraph) > _TG_LIMIT:
                chunks.append(paragraph[:_TG_LIMIT])
                paragraph = paragraph[_TG_LIMIT:]
            current = paragraph + "\n\n"
        else:
            current += paragraph + "\n\n"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks
