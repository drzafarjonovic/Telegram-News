"""
Digest jadvalini boshqaruvchi scheduler (APScheduler) — v3.0.

Har daqiqada:
  • yangi postlarni story'larga aylantiradi (Bosqich A);
  • vaqti kelgan foydalanuvchilarga digest yuboradi (Bosqich B);
  • aqlli rejim: yetarlicha muhim yangilik yig'ilsa, jadvaldan oldin yuboradi;
  • jim soatlarda oddiy digestni kechiktiradi (breaking bundan mustasno);
  • ish kuni / dam olish uchun alohida jadvalni qo'llaydi.

Har daqiqada alohida shoshilinch (breaking) tekshiruvi ham ishlaydi:
  • importance = 5 storylar darhol yuboriladi (jim soatlar ham to'sib qolmaydi).

Vaqt mintaqasi — har foydalanuvchining timezone'i.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import config
from app.db import repository as repo
from app import ai_analyzer, digest, processing
from app import userbot as userbot_mod

logger = logging.getLogger(__name__)

_WEEKEND_DAYS = {5, 6}  # Monday=0 ... Saturday=5, Sunday=6


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _user_tz(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        hh, mm = map(int, str(value).split(":"))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except (ValueError, AttributeError):
        pass
    return None


def _effective_schedule(schedule, now: datetime) -> dict:
    """Bugungi kunga (ish kuni yoki dam olish) tegishli amaldagi jadval."""
    tz = _user_tz(schedule["timezone"])
    local_weekday = now.astimezone(tz).weekday()
    is_weekend = local_weekday in _WEEKEND_DAYS

    if is_weekend and schedule["weekend_enabled"]:
        mode = schedule["weekend_mode"] or "interval"
        interval_min = schedule["weekend_interval_minutes"] or (
            (schedule["interval_hours"] or 6) * 60
        )
        daily_times = schedule["weekend_daily_times"] or []
    else:
        mode = schedule["mode"]
        interval_min = schedule["interval_minutes"] or (
            (schedule["interval_hours"] or 6) * 60
        )
        daily_times = schedule["daily_times"] or []

    return {"mode": mode, "interval_min": max(1, interval_min), "daily_times": daily_times}


def _time_due(eff: dict, last_run, now: datetime, tz_name: str) -> bool:
    """Vaqt jihatidan digest yuborish kerakmi (aqlli rejimdan tashqari)?"""
    if eff["mode"] == "interval":
        if last_run is None:
            return True
        return now - last_run >= timedelta(minutes=eff["interval_min"])

    if eff["mode"] == "daily":
        times = eff["daily_times"]
        if not times:
            return False
        tz = _user_tz(tz_name)
        local_now = now.astimezone(tz)
        for t_str in times:
            hm = _parse_hhmm(t_str)
            if not hm:
                continue
            scheduled_local = local_now.replace(
                hour=hm[0], minute=hm[1], second=0, microsecond=0
            )
            scheduled_utc = scheduled_local.astimezone(timezone.utc)
            if now >= scheduled_utc and (last_run is None or last_run < scheduled_utc):
                return True
        return False

    return False


def _in_quiet_hours(schedule, now: datetime) -> bool:
    """Hozir foydalanuvchining jim soatlari ichidami?"""
    if not schedule["quiet_enabled"]:
        return False
    start = _parse_hhmm(schedule["quiet_start"] or "23:00")
    end = _parse_hhmm(schedule["quiet_end"] or "07:00")
    if not start or not end or start == end:
        return False
    tz = _user_tz(schedule["timezone"])
    local = now.astimezone(tz)
    cur = local.hour * 60 + local.minute
    s = start[0] * 60 + start[1]
    e = end[0] * 60 + end[1]
    if s < e:
        return s <= cur < e
    # Tunab qoladigan oraliq (masalan 23:00–07:00)
    return cur >= s or cur < e


class DigestScheduler:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        # Har daqiqada: (1) yangi postlarni qayta ishlash, (2) due digestlar
        self.scheduler.add_job(
            self._tick, "interval", minutes=1, id="digest_tick", max_instances=1
        )
        # Har daqiqada: shoshilinch (breaking) tekshiruvi
        self.scheduler.add_job(
            self._breaking_tick, "interval", minutes=1, id="breaking_tick",
            max_instances=1,
        )
        # Har 6 soatda kanal salomatligini tekshirish
        self.scheduler.add_job(
            self._health_check, "interval", hours=6, id="health_check",
            max_instances=1,
        )
        # Har kuni eski post va storylarni tozalash
        self.scheduler.add_job(
            self._cleanup, "cron", hour=3, minute=0, id="cleanup"
        )
        # Har N daqiqada backfill
        if config.backfill_enabled:
            self.scheduler.add_job(
                self._backfill, "interval",
                minutes=max(5, config.backfill_interval_min),
                id="backfill", max_instances=1,
            )
        self.scheduler.start()
        logger.info("Scheduler ishga tushdi (v3.0: aqlli + jim + breaking).")

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def _tick(self) -> None:
        # Bosqich A — yangi postlarni story'larga aylantirish
        try:
            await processing.process_new_posts(ai_analyzer.analyzer)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bosqich A (processing) xatosi: %s", exc)

        # Bosqich B — due foydalanuvchilarga digest
        now = _now_utc()
        try:
            schedules = await repo.get_active_schedules()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Jadvallarni olishda xatolik: %s", exc)
            return

        for schedule in schedules:
            try:
                await self._maybe_send(schedule, now)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Digest yuborishda xatolik (user %s): %s",
                    schedule["user_id"], exc,
                )

    async def _maybe_send(self, schedule, now: datetime) -> None:
        user_id = schedule["user_id"]
        last_run = schedule["last_run_at"]
        eff = _effective_schedule(schedule, now)

        due = _time_due(eff, last_run, now, schedule["timezone"])
        smart_triggered = False

        # Aqlli rejim: interval hali kelmagan bo'lsa ham, yetarli muhim yangilik bo'lsa
        if not due and eff["mode"] == "interval" and schedule["smart_mode"]:
            min_stories = schedule["smart_min_stories"] or 5
            try:
                cnt = await repo.count_important_stories_for_user(
                    user_id, last_run, now, 3
                )
            except Exception:  # noqa: BLE001
                cnt = 0
            if cnt >= min_stories:
                due = True
                smart_triggered = True

        if not due:
            return

        # Jim soatlar: oddiy digestni kechiktiramiz (last_run'ni SURMAYMIZ,
        # shunda jim tugagach darhol yuboriladi). Breaking alohida job orqali o'tadi.
        if _in_quiet_hours(schedule, now):
            logger.debug("Jim soat: digest kechiktirildi (user %s).", user_id)
            return

        await self._send_digest(schedule, now, smart=smart_triggered)

    async def _send_digest(self, schedule, now: datetime, smart: bool = False) -> None:
        user_id = schedule["user_id"]
        since = schedule["last_run_at"]
        skip_empty = schedule["skip_empty"]

        result = await digest.build_digest(user_id, since, now)

        # last_run_at ni yangilaymiz (keyingi oraliq uchun)
        await repo.update_last_run(user_id, now)

        if result is None:
            if skip_empty:
                return  # yangilik yo'q -> jim
            try:
                await self.bot.send_message(
                    user_id,
                    "🔕 Belgilangan davrda yangi muhim yangilik bo'lmadi.",
                )
            except Exception:  # noqa: BLE001
                pass
            return

        content = result["content"]
        post_count = result["post_count"]
        if smart:
            content = "🧠 <b>Aqlli digest</b> — muhim yangiliklar yig'ildi\n\n" + content

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
            "digest_sent", actor_id=user_id,
            details={"posts": post_count, "smart": smart},
        )

    async def _breaking_tick(self) -> None:
        """Shoshilinch (importance=5) yangiliklarni darhol yuboradi (jim soatlardan qat'i nazar)."""
        try:
            rows = await repo.get_breaking_candidates(within_minutes=60, min_importance=5)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Breaking nomzodlarini olishda xatolik: %s", exc)
            return

        for row in rows:
            user_id = row["user_id"]
            story_id = row["story_id"]
            text = (
                "🚨 <b>SHOSHILINCH XABAR</b>\n\n"
                f"🗂 {row['category']}\n"
                f"{row['summary']}"
            )
            try:
                await self.bot.send_message(
                    user_id, text, parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Breaking yuborilmadi (user %s): %s", user_id, exc)
            # Yuborilgan (yoki bloklangan) — takrorlamaslik uchun belgilaymiz
            try:
                await repo.mark_breaking_delivered(user_id, story_id)
            except Exception:  # noqa: BLE001
                pass

    async def _health_check(self) -> None:
        if userbot_mod.userbot is None:
            return
        try:
            await userbot_mod.userbot.check_channels(self.bot)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Health check xatosi: %s", exc)

    async def _backfill(self) -> None:
        if userbot_mod.userbot is None:
            return
        try:
            await userbot_mod.userbot.backfill_all()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Backfill xatosi: %s", exc)

    async def _cleanup(self) -> None:
        try:
            deleted_posts = await repo.cleanup_old_posts(days=7)
            deleted_stories = await repo.cleanup_old_stories(days=7)
            logger.info(
                "Tozalandi: %d post, %d story.", deleted_posts, deleted_stories
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tozalashda xatolik: %s", exc)
