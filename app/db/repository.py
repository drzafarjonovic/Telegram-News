"""
Ma'lumotlar bazasi bilan ishlovchi CRUD funksiyalari.

Barcha funksiyalar `db.pool` dan ulanish oladi va asyncpg.Record qaytaradi.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from .pool import db


# ============================================================
#  USERS
# ============================================================
async def upsert_user(
    user_id: int, username: Optional[str], first_name: Optional[str]
) -> None:
    """Foydalanuvchini yaratadi yoki ma'lumotini yangilaydi + faollikni belgilaydi."""
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (id, username, first_name, last_active_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (id) DO UPDATE
                SET username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_active_at = now()
            """,
            user_id,
            username,
            first_name,
        )


async def touch_user(user_id: int) -> None:
    """Foydalanuvchining oxirgi faollik vaqtini yangilaydi."""
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE users SET last_active_at = now() WHERE id = $1", user_id
        )


async def get_user(user_id: int):
    async with db.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)


async def is_banned(user_id: int) -> bool:
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_banned FROM users WHERE id = $1", user_id
        )
        return bool(row and row["is_banned"])


async def set_ban(user_id: int, banned: bool, by_admin: int) -> None:
    async with db.acquire() as conn:
        if banned:
            await conn.execute(
                """UPDATE users SET is_banned = TRUE, banned_at = now(),
                   banned_by = $2 WHERE id = $1""",
                user_id,
                by_admin,
            )
        else:
            await conn.execute(
                """UPDATE users SET is_banned = FALSE, banned_at = NULL,
                   banned_by = NULL WHERE id = $1""",
                user_id,
            )


async def set_max_channels(user_id: int, limit: Optional[int]) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE users SET max_channels = $2 WHERE id = $1", user_id, limit
        )


async def list_users(limit: int = 20, offset: int = 0):
    async with db.acquire() as conn:
        return await conn.fetch(
            """SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2""",
            limit,
            offset,
        )


async def search_users(query: str, limit: int = 20):
    async with db.acquire() as conn:
        if query.lstrip("-").isdigit():
            return await conn.fetch(
                "SELECT * FROM users WHERE id = $1", int(query)
            )
        q = query.lstrip("@").lower()
        return await conn.fetch(
            """SELECT * FROM users
               WHERE lower(username) LIKE '%' || $1 || '%'
                  OR lower(first_name) LIKE '%' || $1 || '%'
               ORDER BY created_at DESC LIMIT $2""",
            q,
            limit,
        )


# ============================================================
#  CHANNELS & SUBSCRIPTIONS
# ============================================================
async def upsert_channel(
    tg_channel_id: int,
    username: Optional[str],
    title: Optional[str],
    access_hash: Optional[int],
):
    """Kanalni yaratadi/yangilaydi va qatorini qaytaradi."""
    async with db.acquire() as conn:
        return await conn.fetchrow(
            """
            INSERT INTO channels (tg_channel_id, username, title, access_hash)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (tg_channel_id) DO UPDATE
                SET username = EXCLUDED.username,
                    title = EXCLUDED.title,
                    access_hash = EXCLUDED.access_hash,
                    is_active = TRUE
            RETURNING *
            """,
            tg_channel_id,
            username,
            title,
            access_hash,
        )


async def get_channel_by_tg_id(tg_channel_id: int):
    async with db.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM channels WHERE tg_channel_id = $1", tg_channel_id
        )


async def subscribe(user_id: int, channel_id: int) -> bool:
    """Obuna qo'shadi. True = yangi qo'shildi, False = allaqachon mavjud."""
    async with db.acquire() as conn:
        result = await conn.execute(
            """INSERT INTO subscriptions (user_id, channel_id)
               VALUES ($1, $2) ON CONFLICT DO NOTHING""",
            user_id,
            channel_id,
        )
        return result.endswith("1")


async def unsubscribe(user_id: int, channel_id: int) -> bool:
    async with db.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM subscriptions WHERE user_id = $1 AND channel_id = $2",
            user_id,
            channel_id,
        )
        return result.endswith("1")


async def count_subscriptions(user_id: int) -> int:
    async with db.acquire() as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM subscriptions WHERE user_id = $1", user_id
        )


async def get_user_channels(user_id: int):
    async with db.acquire() as conn:
        return await conn.fetch(
            """SELECT c.* FROM channels c
               JOIN subscriptions s ON s.channel_id = c.id
               WHERE s.user_id = $1
               ORDER BY c.title""",
            user_id,
        )


async def get_all_monitored_channels():
    """Kamida bitta obunachisi bor faol kanallar (userbot kuzatishi uchun)."""
    async with db.acquire() as conn:
        return await conn.fetch(
            """SELECT DISTINCT c.* FROM channels c
               JOIN subscriptions s ON s.channel_id = c.id
               WHERE c.is_active = TRUE"""
        )


async def get_subscribers(channel_id: int):
    async with db.acquire() as conn:
        return await conn.fetch(
            "SELECT user_id FROM subscriptions WHERE channel_id = $1", channel_id
        )


async def channel_subscriber_count(channel_id: int) -> int:
    async with db.acquire() as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM subscriptions WHERE channel_id = $1", channel_id
        )


async def list_channels_with_counts(limit: int = 30, offset: int = 0):
    async with db.acquire() as conn:
        return await conn.fetch(
            """SELECT c.*, count(s.id) AS subs
               FROM channels c
               LEFT JOIN subscriptions s ON s.channel_id = c.id
               GROUP BY c.id
               ORDER BY subs DESC, c.id
               LIMIT $1 OFFSET $2""",
            limit,
            offset,
        )


async def deactivate_channel(channel_id: int) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE channels SET is_active = FALSE WHERE id = $1", channel_id
        )


# ============================================================
#  SCHEDULES
# ============================================================
async def get_schedule(user_id: int):
    async with db.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM schedules WHERE user_id = $1", user_id
        )


async def set_interval_schedule(user_id: int, hours: int) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO schedules (user_id, mode, interval_hours, daily_times, is_active, updated_at)
            VALUES ($1, 'interval', $2, '{}', TRUE, now())
            ON CONFLICT (user_id) DO UPDATE
                SET mode = 'interval', interval_hours = EXCLUDED.interval_hours,
                    is_active = TRUE, updated_at = now()
            """,
            user_id,
            hours,
        )


async def set_daily_schedule(user_id: int, times: list[str]) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO schedules (user_id, mode, daily_times, is_active, updated_at)
            VALUES ($1, 'daily', $2, TRUE, now())
            ON CONFLICT (user_id) DO UPDATE
                SET mode = 'daily', daily_times = EXCLUDED.daily_times,
                    is_active = TRUE, updated_at = now()
            """,
            user_id,
            times,
        )


async def set_schedule_active(user_id: int, active: bool) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE schedules SET is_active = $2, updated_at = now() WHERE user_id = $1",
            user_id,
            active,
        )


async def update_last_run(user_id: int, when: datetime) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE schedules SET last_run_at = $2 WHERE user_id = $1",
            user_id,
            when,
        )


async def get_active_schedules():
    """Faol jadvallar (faqat bloklanmagan foydalanuvchilar)."""
    async with db.acquire() as conn:
        return await conn.fetch(
            """SELECT s.*, u.timezone FROM schedules s
               JOIN users u ON u.id = s.user_id
               WHERE s.is_active = TRUE AND u.is_banned = FALSE"""
        )


# ============================================================
#  POSTS
# ============================================================
async def insert_post(
    channel_id: int, tg_message_id: int, text: str, posted_at: datetime
) -> bool:
    """Postni saqlaydi. True = yangi qo'shildi."""
    async with db.acquire() as conn:
        result = await conn.execute(
            """INSERT INTO posts (channel_id, tg_message_id, text, posted_at)
               VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING""",
            channel_id,
            tg_message_id,
            text,
            posted_at,
        )
        return result.endswith("1")


async def get_posts_for_user(user_id: int, since: Optional[datetime], until: datetime):
    """
    Foydalanuvchi obuna bo'lgan kanallardagi [since, until] oralig'idagi postlar.
    `since` None bo'lsa, until'gacha bo'lgan barchasi olinadi.
    """
    async with db.acquire() as conn:
        if since is None:
            return await conn.fetch(
                """SELECT p.text, p.posted_at, c.title, c.username
                   FROM posts p
                   JOIN channels c ON c.id = p.channel_id
                   JOIN subscriptions s ON s.channel_id = c.id
                   WHERE s.user_id = $1 AND p.posted_at <= $2
                     AND p.text IS NOT NULL AND length(trim(p.text)) > 0
                   ORDER BY p.posted_at""",
                user_id,
                until,
            )
        return await conn.fetch(
            """SELECT p.text, p.posted_at, c.title, c.username
               FROM posts p
               JOIN channels c ON c.id = p.channel_id
               JOIN subscriptions s ON s.channel_id = c.id
               WHERE s.user_id = $1 AND p.posted_at > $2 AND p.posted_at <= $3
                 AND p.text IS NOT NULL AND length(trim(p.text)) > 0
               ORDER BY p.posted_at""",
            user_id,
            since,
            until,
        )


async def cleanup_old_posts(days: int = 7) -> int:
    """Eski postlarni o'chiradi (bazani toza tutish uchun)."""
    async with db.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM posts WHERE collected_at < now() - ($1 || ' days')::interval",
            str(days),
        )
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0


# ============================================================
#  DIGESTS
# ============================================================
async def log_digest(
    user_id: int,
    period_start: Optional[datetime],
    period_end: datetime,
    post_count: int,
    content: str,
) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO digests (user_id, period_start, period_end, post_count, content)
               VALUES ($1, $2, $3, $4, $5)""",
            user_id,
            period_start,
            period_end,
            post_count,
            content,
        )


async def count_user_digests(user_id: int) -> int:
    async with db.acquire() as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM digests WHERE user_id = $1", user_id
        )


# ============================================================
#  AUDIT LOG
# ============================================================
async def log_audit(
    action: str,
    actor_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO audit_logs (actor_id, target_user_id, action, details)
               VALUES ($1, $2, $3, $4)""",
            actor_id,
            target_user_id,
            action,
            json.dumps(details, ensure_ascii=False) if details else None,
        )


async def get_audit_logs(
    limit: int = 20, offset: int = 0, action: Optional[str] = None
):
    async with db.acquire() as conn:
        if action:
            return await conn.fetch(
                """SELECT * FROM audit_logs WHERE action = $3
                   ORDER BY created_at DESC LIMIT $1 OFFSET $2""",
                limit,
                offset,
                action,
            )
        return await conn.fetch(
            """SELECT * FROM audit_logs
               ORDER BY created_at DESC LIMIT $1 OFFSET $2""",
            limit,
            offset,
        )


# ============================================================
#  AI USAGE
# ============================================================
async def log_ai_usage(
    user_id: Optional[int],
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO ai_usage (user_id, provider, model, tokens_in, tokens_out)
               VALUES ($1, $2, $3, $4, $5)""",
            user_id,
            provider,
            model,
            tokens_in,
            tokens_out,
        )


# ============================================================
#  BROADCASTS
# ============================================================
async def log_broadcast(
    admin_id: int, message: str, total: int, delivered: int, failed: int
) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO broadcasts (admin_id, message, total, delivered, failed)
               VALUES ($1, $2, $3, $4, $5)""",
            admin_id,
            message,
            total,
            delivered,
            failed,
        )


async def get_all_user_ids(only_active: bool = True) -> list[int]:
    async with db.acquire() as conn:
        if only_active:
            rows = await conn.fetch("SELECT id FROM users WHERE is_banned = FALSE")
        else:
            rows = await conn.fetch("SELECT id FROM users")
        return [r["id"] for r in rows]


# ============================================================
#  STATISTIKA (admin dashboard)
# ============================================================
async def get_stats() -> dict[str, Any]:
    async with db.acquire() as conn:
        total_users = await conn.fetchval("SELECT count(*) FROM users")
        banned_users = await conn.fetchval(
            "SELECT count(*) FROM users WHERE is_banned = TRUE"
        )
        total_channels = await conn.fetchval(
            "SELECT count(*) FROM channels WHERE is_active = TRUE"
        )
        total_posts = await conn.fetchval("SELECT count(*) FROM posts")
        total_digests = await conn.fetchval("SELECT count(*) FROM digests")
        new_today = await conn.fetchval(
            "SELECT count(*) FROM users WHERE created_at >= now() - interval '1 day'"
        )
        new_week = await conn.fetchval(
            "SELECT count(*) FROM users WHERE created_at >= now() - interval '7 days'"
        )
        new_month = await conn.fetchval(
            "SELECT count(*) FROM users WHERE created_at >= now() - interval '30 days'"
        )
        ai_calls = await conn.fetchval("SELECT count(*) FROM ai_usage")
        ai_tokens = await conn.fetchval(
            "SELECT COALESCE(sum(tokens_in + tokens_out), 0) FROM ai_usage"
        )
        top_channels = await conn.fetch(
            """SELECT c.title, c.username, count(s.id) AS subs
               FROM channels c
               JOIN subscriptions s ON s.channel_id = c.id
               WHERE c.is_active = TRUE
               GROUP BY c.id ORDER BY subs DESC LIMIT 5"""
        )
        return {
            "total_users": total_users,
            "banned_users": banned_users,
            "total_channels": total_channels,
            "total_posts": total_posts,
            "total_digests": total_digests,
            "new_today": new_today,
            "new_week": new_week,
            "new_month": new_month,
            "ai_calls": ai_calls,
            "ai_tokens": ai_tokens,
            "top_channels": top_channels,
        }



# ============================================================
#  FAZA 1 — STORIES (cache pipeline) & DEDUP
# ============================================================
async def get_unprocessed_posts(limit: int = 25):
    """Hali tahlil qilinmagan postlar (matn, OCR yoki audio-transkript bo'lsa)."""
    async with db.acquire() as conn:
        return await conn.fetch(
            """SELECT id, channel_id, text, ocr_text, transcript, posted_at
               FROM posts
               WHERE processed = FALSE
                 AND (
                       (text IS NOT NULL AND length(trim(text)) > 0)
                    OR (ocr_text IS NOT NULL AND length(trim(ocr_text)) > 0)
                    OR (transcript IS NOT NULL AND length(trim(transcript)) > 0)
                 )
               ORDER BY posted_at
               LIMIT $1""",
            limit,
        )


async def get_recent_stories(hours: int = 24):
    """Dedup uchun so'nggi storylar (id + keywords)."""
    async with db.acquire() as conn:
        return await conn.fetch(
            """SELECT id, keywords
               FROM stories
               WHERE created_at >= now() - ($1 || ' hours')::interval
                 AND keywords IS NOT NULL""",
            str(hours),
        )


async def create_story(
    summary: str,
    category: str,
    importance: int,
    sentiment: str,
    lang: str,
    keywords: str,
    first_posted_at,
) -> int:
    """Yangi story yaratadi va id qaytaradi (post_count=1)."""
    async with db.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO stories
               (summary, category, importance, sentiment, lang,
                keywords, first_posted_at, post_count)
               VALUES ($1, $2, $3, $4, $5, $6, $7, 1)
               RETURNING id""",
            summary,
            category,
            importance,
            sentiment,
            lang,
            keywords,
            first_posted_at,
        )


async def mark_post_processed(post_id: int, story_id: int | None) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE posts SET processed = TRUE, story_id = $2 WHERE id = $1",
            post_id,
            story_id,
        )


async def increment_story(story_id: int, posted_at) -> None:
    """Dublikat post qo'shilganda story hisobini oshiradi va eng erta vaqtni saqlaydi."""
    async with db.acquire() as conn:
        await conn.execute(
            """UPDATE stories
               SET post_count = post_count + 1,
                   first_posted_at = LEAST(first_posted_at, $2)
               WHERE id = $1""",
            story_id,
            posted_at,
        )


async def get_stories_for_user(
    user_id: int,
    since,
    until,
    importance_min: int = 1,
    interests: list[str] | None = None,
):
    """
    Foydalanuvchi obuna bo'lgan kanallardagi postlardan tashkil topgan,
    [since, until] oralig'idagi storylar — manbalari (sources) bilan.

    Filtrlar (Faza 2):
      • importance_min — minimal muhimlik bali
      • interests — kategoriyalar ro'yxati (bo'sh = barcha kategoriyalar)

    AI chaqirilmaydi; tayyor cache qaytariladi.
    """
    interests = interests or []
    base = """
        SELECT st.id, st.summary, st.category, st.importance, st.sentiment,
               array_agg(DISTINCT
                   CASE
                       WHEN c.username IS NOT NULL AND c.username <> ''
                           THEN '<a href="https://t.me/' || c.username || '/' || p.tg_message_id::text
                                || '">@' || c.username || '</a>'
                       ELSE replace(replace(replace(
                                COALESCE(c.title, 'Kanal'),
                                '&', '&amp;'), '<', '&lt;'), '>', '&gt;')
                   END
               ) AS sources
        FROM stories st
        JOIN posts p ON p.story_id = st.id
        JOIN subscriptions s ON s.channel_id = p.channel_id
        JOIN channels c ON c.id = p.channel_id
        WHERE s.user_id = $1 AND p.posted_at <= $2
          AND st.importance >= $3
          AND (cardinality($4::text[]) = 0 OR st.category = ANY($4))
          {since_clause}
        GROUP BY st.id
        ORDER BY st.importance DESC, st.first_posted_at
    """
    async with db.acquire() as conn:
        if since is None:
            return await conn.fetch(
                base.format(since_clause=""),
                user_id, until, importance_min, interests,
            )
        return await conn.fetch(
            base.format(since_clause="AND p.posted_at > $5"),
            user_id, until, importance_min, interests, since,
        )


async def set_interests(user_id: int, interests: list[str]) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE users SET interests = $2 WHERE id = $1", user_id, interests
        )


async def set_importance_min(user_id: int, value: int) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE users SET importance_min = $2 WHERE id = $1", user_id, value
        )


async def get_user_digests(user_id: int, limit: int = 10):
    """Oxirgi digestlar (tarix uchun) — id, sana, post soni."""
    async with db.acquire() as conn:
        return await conn.fetch(
            """SELECT id, period_start, period_end, post_count, sent_at
               FROM digests
               WHERE user_id = $1 AND sent_at >= now() - interval '7 days'
               ORDER BY sent_at DESC
               LIMIT $2""",
            user_id,
            limit,
        )


async def get_digest(digest_id: int, user_id: int):
    """Bitta digestning to'liq matni (faqat egasiga)."""
    async with db.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM digests WHERE id = $1 AND user_id = $2",
            digest_id,
            user_id,
        )


async def cleanup_old_stories(days: int = 7) -> int:
    async with db.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM stories WHERE created_at < now() - ($1 || ' days')::interval",
            str(days),
        )
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0


# ============================================================
#  FAZA 1 — CHANNEL HEALTH CHECK
# ============================================================
async def get_all_active_channels():
    async with db.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM channels WHERE is_active = TRUE ORDER BY id"
        )


async def update_channel_health(channel_id: int, status: str, error: str | None) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """UPDATE channels
               SET health_status = $2, last_error = $3, last_checked_at = now()
               WHERE id = $1""",
            channel_id,
            status,
            error,
        )


async def update_channel_identity(
    channel_id: int, username: str | None, title: str | None
) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE channels SET username = $2, title = $3 WHERE id = $1",
            channel_id,
            username,
            title,
        )


# ============================================================
#  ENTERPRISE v2.0 — RAW, POSTS(upsert), MEDIA, EDIT/DELETE,
#                     BACKFILL, PROCESSING LOGS
# ============================================================
async def insert_raw_message(
    *, channel_id: int, tg_channel_id: int, tg_message_id: int, raw_json: str
) -> bool:
    """Xabarning xom JSON ko'rinishini idempotent saqlaydi. True = yangi qo'shildi."""
    async with db.acquire() as conn:
        result = await conn.execute(
            """INSERT INTO raw_messages
                   (channel_id, tg_channel_id, tg_message_id, raw_data)
               VALUES ($1, $2, $3, $4::jsonb)
               ON CONFLICT (tg_channel_id, tg_message_id) DO NOTHING""",
            channel_id,
            tg_channel_id,
            tg_message_id,
            raw_json,
        )
        return result.endswith("1")


async def upsert_post(
    *,
    channel_id: int,
    tg_message_id: int,
    text: str,
    posted_at,
    caption: Optional[str] = None,
    has_media: bool = False,
    grouped_id: Optional[int] = None,
    is_forwarded: bool = False,
    fwd_from_channel: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
) -> dict:
    """
    Postni idempotent saqlaydi/yangilaydi va {id, inserted} qaytaradi.
    `inserted` True bo'lsa — yangi qo'shildi, False bo'lsa — mavjudi yangilandi.
    (xmax = 0) hiylasi orqali insert/update ajratiladi.
    """
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO posts
                   (channel_id, tg_message_id, text, posted_at, caption,
                    has_media, grouped_id, is_forwarded, fwd_from_channel,
                    reply_to_message_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (channel_id, tg_message_id) DO UPDATE
                   SET text = EXCLUDED.text,
                       caption = EXCLUDED.caption,
                       has_media = EXCLUDED.has_media,
                       grouped_id = COALESCE(EXCLUDED.grouped_id, posts.grouped_id),
                       is_forwarded = EXCLUDED.is_forwarded,
                       fwd_from_channel = EXCLUDED.fwd_from_channel,
                       reply_to_message_id = EXCLUDED.reply_to_message_id
               RETURNING id, (xmax = 0) AS inserted""",
            channel_id,
            tg_message_id,
            text,
            posted_at,
            caption,
            has_media,
            grouped_id,
            is_forwarded,
            fwd_from_channel,
            reply_to_message_id,
        )
        return {"id": row["id"], "inserted": row["inserted"]}


async def insert_media(
    *,
    post_id: int,
    channel_id: int,
    tg_message_id: int,
    file_id: Optional[str],
    unique_file_id: Optional[str],
    media_type: str,
    caption: Optional[str] = None,
) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO media
                   (post_id, channel_id, tg_message_id, file_id,
                    unique_file_id, media_type, caption)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (channel_id, tg_message_id, unique_file_id) DO NOTHING""",
            post_id,
            channel_id,
            tg_message_id,
            file_id,
            unique_file_id,
            media_type,
            caption,
        )


async def append_post_text_extra(
    post_id: int, *, ocr_text: Optional[str] = None, transcript: Optional[str] = None
) -> None:
    """Postga OCR/transkript matnini qo'shadi (media jadvaliga ham)."""
    async with db.acquire() as conn:
        await conn.execute(
            """UPDATE posts
               SET ocr_text = COALESCE($2, ocr_text),
                   transcript = COALESCE($3, transcript)
               WHERE id = $1""",
            post_id,
            ocr_text,
            transcript,
        )
        await conn.execute(
            """UPDATE media
               SET ocr_text = COALESCE($2, ocr_text),
                   transcript = COALESCE($3, transcript)
               WHERE post_id = $1""",
            post_id,
            ocr_text,
            transcript,
        )


async def mark_post_edited(
    channel_id: int, tg_message_id: int, new_text: str, edited_at
) -> None:
    """Tahrirlangan xabar: matnni yangilaydi va qayta tahlil uchun belgilaydi."""
    async with db.acquire() as conn:
        await conn.execute(
            """UPDATE posts
               SET text = $3, edited_at = $4, processed = FALSE, story_id = NULL
               WHERE channel_id = $1 AND tg_message_id = $2""",
            channel_id,
            tg_message_id,
            new_text,
            edited_at,
        )


async def mark_post_deleted(channel_id: int, tg_message_id: int, when) -> None:
    """O'chirilgan xabarni tomb-stone qiladi (digestlarga tushmaydi)."""
    async with db.acquire() as conn:
        await conn.execute(
            """UPDATE posts SET deleted_at = $3
               WHERE channel_id = $1 AND tg_message_id = $2""",
            channel_id,
            tg_message_id,
            when,
        )


async def get_max_message_id(channel_id: int) -> Optional[int]:
    """Backfill uchun: kanaldagi eng katta saqlangan tg_message_id."""
    async with db.acquire() as conn:
        return await conn.fetchval(
            "SELECT max(tg_message_id) FROM posts WHERE channel_id = $1", channel_id
        )


async def set_channel_backfilled(channel_id: int) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE channels SET last_backfilled_at = now() WHERE id = $1", channel_id
        )


async def log_processing(
    post_id: Optional[int],
    channel_id: Optional[int],
    stage: str,
    status: str,
    error_msg: Optional[str] = None,
) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO processing_logs
                   (post_id, channel_id, stage, status, error_msg)
               VALUES ($1,$2,$3,$4,$5)""",
            post_id,
            channel_id,
            stage,
            status,
            error_msg,
        )


# ============================================================
#  v3.0 — Aqlli jadval, jim soatlar, dam olish, breaking, onboarding
# ============================================================
async def set_interval_minutes(user_id: int, minutes: int) -> None:
    """Interval rejimini daqiqada saqlaydi (30/45 daq va h.k.)."""
    hours = max(1, round(minutes / 60)) if minutes else 6
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO schedules (user_id, mode, interval_hours, interval_minutes,
                                   daily_times, is_active, updated_at)
            VALUES ($1, 'interval', $2, $3, '{}', TRUE, now())
            ON CONFLICT (user_id) DO UPDATE
                SET mode = 'interval', interval_hours = EXCLUDED.interval_hours,
                    interval_minutes = EXCLUDED.interval_minutes,
                    is_active = TRUE, updated_at = now()
            """,
            user_id, hours, minutes,
        )


async def set_smart_mode(user_id: int, enabled: bool, min_stories: int | None = None) -> None:
    async with db.acquire() as conn:
        if min_stories is None:
            await conn.execute(
                """INSERT INTO schedules (user_id, smart_mode, updated_at)
                   VALUES ($1, $2, now())
                   ON CONFLICT (user_id) DO UPDATE
                       SET smart_mode = EXCLUDED.smart_mode, updated_at = now()""",
                user_id, enabled,
            )
        else:
            await conn.execute(
                """INSERT INTO schedules (user_id, smart_mode, smart_min_stories, updated_at)
                   VALUES ($1, $2, $3, now())
                   ON CONFLICT (user_id) DO UPDATE
                       SET smart_mode = EXCLUDED.smart_mode,
                           smart_min_stories = EXCLUDED.smart_min_stories,
                           updated_at = now()""",
                user_id, enabled, max(1, min(50, min_stories)),
            )


async def set_skip_empty(user_id: int, enabled: bool) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO schedules (user_id, skip_empty, updated_at)
               VALUES ($1, $2, now())
               ON CONFLICT (user_id) DO UPDATE
                   SET skip_empty = EXCLUDED.skip_empty, updated_at = now()""",
            user_id, enabled,
        )


async def set_breaking_enabled(user_id: int, enabled: bool) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO schedules (user_id, breaking_enabled, updated_at)
               VALUES ($1, $2, now())
               ON CONFLICT (user_id) DO UPDATE
                   SET breaking_enabled = EXCLUDED.breaking_enabled, updated_at = now()""",
            user_id, enabled,
        )


async def set_quiet(user_id: int, enabled: bool, start: str | None = None, end: str | None = None) -> None:
    async with db.acquire() as conn:
        if start is not None and end is not None:
            await conn.execute(
                """INSERT INTO schedules (user_id, quiet_enabled, quiet_start, quiet_end, updated_at)
                   VALUES ($1, $2, $3, $4, now())
                   ON CONFLICT (user_id) DO UPDATE
                       SET quiet_enabled = EXCLUDED.quiet_enabled,
                           quiet_start = EXCLUDED.quiet_start,
                           quiet_end = EXCLUDED.quiet_end, updated_at = now()""",
                user_id, enabled, start, end,
            )
        else:
            await conn.execute(
                """INSERT INTO schedules (user_id, quiet_enabled, updated_at)
                   VALUES ($1, $2, now())
                   ON CONFLICT (user_id) DO UPDATE
                       SET quiet_enabled = EXCLUDED.quiet_enabled, updated_at = now()""",
                user_id, enabled,
            )


async def set_weekend_schedule(
    user_id: int,
    enabled: bool,
    mode: str = "interval",
    interval_minutes: int | None = None,
    times: list[str] | None = None,
) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO schedules (user_id, weekend_enabled, weekend_mode,
                                     weekend_interval_minutes, weekend_daily_times, updated_at)
               VALUES ($1, $2, $3, $4, $5, now())
               ON CONFLICT (user_id) DO UPDATE
                   SET weekend_enabled = EXCLUDED.weekend_enabled,
                       weekend_mode = EXCLUDED.weekend_mode,
                       weekend_interval_minutes = EXCLUDED.weekend_interval_minutes,
                       weekend_daily_times = EXCLUDED.weekend_daily_times,
                       updated_at = now()""",
            user_id, enabled, mode, interval_minutes, times or [],
        )


async def set_onboarded(user_id: int, value: bool = True) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE users SET onboarded = $2 WHERE id = $1", user_id, value
        )


async def touch_manual_digest(user_id: int) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE users SET last_manual_digest_at = now() WHERE id = $1", user_id
        )


async def get_channel_card(user_id: int, channel_id: int):
    """Kanal kartochkasi: sarlavha, @username, post soni, oxirgi post, sog'liq."""
    async with db.acquire() as conn:
        return await conn.fetchrow(
            """SELECT c.id, c.title, c.username, c.health_status, c.last_checked_at,
                      count(p.id) AS post_count, max(p.posted_at) AS last_post_at
               FROM channels c
               JOIN subscriptions s ON s.channel_id = c.id AND s.user_id = $2
               LEFT JOIN posts p ON p.channel_id = c.id
               WHERE c.id = $1
               GROUP BY c.id""",
            channel_id, user_id,
        )


async def count_important_stories_for_user(
    user_id: int, since, until, min_importance: int = 3
) -> int:
    """Aqlli rejim uchun: foydalanuvchi filtrlariga mos, muhim storylar soni."""
    async with db.acquire() as conn:
        return await conn.fetchval(
            """SELECT count(DISTINCT st.id)
               FROM stories st
               JOIN posts p ON p.story_id = st.id
               JOIN subscriptions s ON s.channel_id = p.channel_id
               JOIN users u ON u.id = s.user_id
               WHERE s.user_id = $1
                 AND p.posted_at <= $3
                 AND ($2::timestamptz IS NULL OR p.posted_at > $2)
                 AND st.importance >= GREATEST($4, u.importance_min)
                 AND (cardinality(u.interests) = 0 OR st.category = ANY(u.interests))""",
            user_id, since, until, min_importance,
        ) or 0


async def get_breaking_candidates(within_minutes: int = 60, min_importance: int = 5):
    """
    Hali yuborilmagan shoshilinch storylar + ularni oladigan foydalanuvchilar.
    Foydalanuvchi filtrlarga (qiziqish, ban, breaking yoqilgan) mos bo'lishi shart.
    """
    async with db.acquire() as conn:
        return await conn.fetch(
            """
            SELECT st.id AS story_id, st.summary, st.category,
                   st.importance, s.user_id,
                   array_agg(DISTINCT
                       CASE
                           WHEN c.username IS NOT NULL AND c.username <> ''
                               THEN '<a href="https://t.me/' || c.username || '/' || p.tg_message_id::text
                                    || '">@' || c.username || '</a>'
                           ELSE replace(replace(replace(
                                    COALESCE(c.title, 'Kanal'),
                                    '&', '&amp;'), '<', '&lt;'), '>', '&gt;')
                       END
                   ) AS sources
            FROM stories st
            JOIN posts p ON p.story_id = st.id
            JOIN subscriptions s ON s.channel_id = p.channel_id
            JOIN channels c ON c.id = p.channel_id
            JOIN users u ON u.id = s.user_id
            JOIN schedules sc ON sc.user_id = s.user_id
            WHERE st.importance >= $2
              AND st.created_at >= now() - ($1 || ' minutes')::interval
              AND p.posted_at >= now() - interval '6 hours'
              AND u.is_banned = FALSE
              AND sc.is_active = TRUE
              AND sc.breaking_enabled = TRUE
              AND (cardinality(u.interests) = 0 OR st.category = ANY(u.interests))
              AND NOT EXISTS (
                  SELECT 1 FROM breaking_deliveries bd
                  WHERE bd.user_id = s.user_id AND bd.story_id = st.id
              )
            GROUP BY st.id, st.summary, st.category, st.importance, s.user_id
            ORDER BY st.id
            """,
            str(within_minutes), min_importance,
        )


async def mark_breaking_delivered(user_id: int, story_id: int) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO breaking_deliveries (user_id, story_id)
               VALUES ($1, $2) ON CONFLICT DO NOTHING""",
            user_id, story_id,
        )
