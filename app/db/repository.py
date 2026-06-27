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
