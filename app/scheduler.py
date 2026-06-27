"""
Digest jadvalini boshqaruvchi scheduler (APScheduler).

Har daqiqada barcha faol jadvallarni tekshiradi va vaqti kelganlarga
digest yuboradi. Interval (har N soat) va daily (aniq vaqt) rejimlarini
qo'llab-quvvatlaydi. Vaqt mintaqasi — har foydalanuvchining timezone'i.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db import repository as repo
from app import digest

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _user_tz(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _is_due(schedule, now: datetime) -> bool:
    """Berilgan jadval hozir ishga tushishi kerakmi?"""
    last_run = schedule["last_run_at"]
    mode = schedule["mode"]

    if mode == "interval":
        hours = schedule["interval_hours"] or 6
        if last_run is None:
            return True  # birinchi marta
        return now - last_run >= timedelta(hours=hours)

    if mode == "daily":
        times = schedule["daily_times"] or []
        if not times:
            return False
        tz = _user_tz(schedule["timezone"])
        local_now = now.astimezone(tz)
        for t_str in times:
            try:
                hh, mm = map(int, t_str.split(":"))
            except (ValueError, AttributeError):
                continue
            scheduled_local = local_now.replace(
                hour=hh, minute=mm, second=0, microsecond=0
            )
            scheduled_utc = scheduled_local.astimezone(timezone.utc)
            # Vaqt o'tgan bo'lsa va bugun shu vaqtda hali yuborilmagan bo'lsa
            if now >= scheduled_utc and (
                last_run is None or last_run < scheduled_utc
            ):
                return True
        return False

    return False


class DigestScheduler:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        # Har daqiqada due jadvallarni tekshirish
        self.scheduler.add_job(
            self._tick, "interval", minutes=1, id="digest_tick", max_instances=1
        )
        # Har kuni yarim tunda eski postlarni tozalash
        self.scheduler.add_job(
            self._cleanup, "cron", hour=3, minute=0, id="cleanup"
        )
        self.scheduler.start()
        logger.info("Scheduler ishga tushdi.")

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def _tick(self) -> None:
        now = _now_utc()
        try:
            schedules = await repo.get_active_schedules()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Jadvallarni olishda xatolik: %s", exc)
            return

        for schedule in schedules:
            try:
                if _is_due(schedule, now):
                    await self._send_digest(schedule, now)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Digest yuborishda xatolik (user %s): %s",
                    schedule["user_id"],
                    exc,
                )

    async def _send_digest(self, schedule, now: datetime) -> None:
        user_id = schedule["user_id"]
        since = schedule["last_run_at"]

        result = await digest.build_digest(user_id, since, now)

        # last_run_at ni har doim yangilaymiz (post bo'lmasa ham — keyingi oraliq uchun)
        await repo.update_last_run(user_id, now)

        if result is None:
            return  # post yo'q -> jim

        content = result["content"]
        post_count = result["post_count"]

        # Uzun bo'lsa bo'laklarga ajratamiz
        for part in digest.split_for_telegram(content):
            try:
                await self.bot.send_message(
                    user_id, part, parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Digest yuborilmadi (user %s): %s", user_id, exc)
                return

        await repo.log_digest(user_id, since, now, post_count, content)
        await repo.log_audit(
            "digest_sent", actor_id=user_id, details={"posts": post_count}
        )

    async def _cleanup(self) -> None:
        try:
            deleted = await repo.cleanup_old_posts(days=7)
            logger.info("Eski postlar tozalandi: %d ta", deleted)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tozalashda xatolik: %s", exc)
