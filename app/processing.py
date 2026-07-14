"""
Bosqich A — UMUMIY qayta ishlash (cache pipeline yadrosi).

Yangi (hali tahlil qilinmagan) postlarni oladi:
  1. Jaccard o'xshashligi orqali dublikatlarni aniqlaydi (turli kanallardagi
     bir xil yangilik).
  2. Dublikat bo'lsa — mavjud story'ga biriktiradi (AI chaqirilmaydi).
  3. Yangi yangilik bo'lsa — AI BIR MARTA tahlil qiladi (mazmun, kategoriya,
     muhimlik, sentiment) va natijani story sifatida cache'laydi.

Shunday qilib AI har yangilik uchun faqat bir marta ishlaydi va natija
barcha obunachilarga qayta ishlatiladi (70-95% token tejaladi).
"""
from __future__ import annotations

import asyncio
import logging

from config import config
from app.db import repository as repo
from app import text_similarity as sim

logger = logging.getLogger(__name__)

# AI chaqiruvlari orasidagi pauza (Groq rate-limitidan saqlanish)
_THROTTLE_SEC = 0.4


def _find_similar_story(post_tokens: set[str], recent_stories: list[dict]) -> int | None:
    """Mavjud storylar ichidan eng yaqin (dublikat) story id'sini topadi."""
    best_id: int | None = None
    best_score = config.dedup_similarity
    for st in recent_stories:
        score = sim.jaccard(post_tokens, st["tokens"])
        if score >= config.dedup_similarity and score >= best_score:
            best_score = score
            best_id = st["id"]
    return best_id


async def process_new_posts(analyzer) -> int:
    """
    Yangi postlarni qayta ishlaydi. Qayta ishlangan postlar sonini qaytaradi.
    """
    if analyzer is None:
        return 0

    posts = await repo.get_unprocessed_posts(limit=config.process_batch_size)
    if not posts:
        return 0

    # Dedup uchun so'nggi storylar (kalit so'zlarni to'plamga aylantiramiz)
    recent = [
        {"id": r["id"], "tokens": set((r["keywords"] or "").split())}
        for r in await repo.get_recent_stories(hours=24)
    ]

    processed = 0
    for post in posts:
        text = (post["text"] or "").strip()

        # 0) Matn umuman yo'q (captionsiz media + OCR/STT o'chiq yoki muvaffaqiyatsiz).
        #    Story yaratmasdan "qayta ishlangan" deb belgilaymiz (qayta skaner qilinmasin).
        if not text:
            await repo.mark_post_processed(post["id"], None)
            processed += 1
            continue

        tokens = sim.tokenize(text)

        # 1) Dublikat tekshiruvi
        match_id = _find_similar_story(tokens, recent)
        if match_id is not None:
            await repo.mark_post_processed(post["id"], match_id)
            await repo.increment_story(match_id, post["posted_at"])
            processed += 1
            continue

        # 2) Yangi yangilik — AI tahlili (bir marta)
        analysis = await analyzer.analyze_story(text)
        await asyncio.sleep(_THROTTLE_SEC)

        if analysis is None:
            # AI vaqtincha ishlamadi — bu postni keyingi siklga qoldiramiz
            logger.warning(
                "AI tahlili muvaffaqiyatsiz, post %s keyinroq qayta ishlanadi.",
                post["id"],
            )
            break  # butun batchni keyingi tick'ga qoldiramiz

        if analysis.get("skip"):
            # Reklama/ahamiyatsiz — story yaratmasdan "qayta ishlangan" deb belgilaymiz
            await repo.mark_post_processed(post["id"], None)
            processed += 1
            continue

        keywords = sim.keywords_str(text)
        story_id = await repo.create_story(
            summary=analysis["summary"],
            category=analysis["category"],
            importance=analysis["importance"],
            sentiment=analysis["sentiment"],
            lang=config.analysis_language,
            keywords=keywords,
            first_posted_at=post["posted_at"],
        )
        await repo.mark_post_processed(post["id"], story_id)
        recent.append({"id": story_id, "tokens": set(keywords.split())})
        processed += 1

    if processed:
        logger.info("Bosqich A: %d ta post qayta ishlandi.", processed)
    return processed
