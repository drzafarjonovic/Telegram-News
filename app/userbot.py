"""
Userbot (Telethon) — Enterprise v2.0.

Yangiliklar (oldingi versiyaga nisbatan):
  • Hodisalar: events.NewMessage + events.Album + MessageEdited + MessageDeleted
  • Barcha kiruvchi xabarlar ingest navbatiga (IngestPipeline) yo'naltiriladi;
    bir nechta asinxron worker ularni idempotent saqlaydi.
  • Startup + davriy backfill (iter_messages/get_messages) bo'shliqlarni to'ldiradi.
  • FloodWait xavfsiz chaqiruvlar (app.tg_utils.safe_call).
  • Media (rasm/audio), forward va reply ma'lumotlari ham saqlanadi.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from telethon import TelegramClient, events, utils
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import Channel

from config import config
from app import metrics
from app.db import repository as repo
from app.ingest import IngestJob, IngestPipeline
from app.tg_utils import safe_call

logger = logging.getLogger(__name__)

# Link formatlari: @username | https://t.me/username | t.me/username | username
_USERNAME_RE = re.compile(
    r"(?:https?://)?(?:t\.me/|telegram\.me/)?@?([A-Za-z][A-Za-z0-9_]{3,31})/?$"
)


def parse_channel_link(text: str) -> Optional[str]:
    """Matndan kanal username'ini ajratadi. Topilmasa None."""
    text = (text or "").strip()
    if "t.me/+" in text or "joinchat" in text:
        return None
    m = _USERNAME_RE.match(text)
    if not m:
        return None
    return m.group(1)


class Userbot:
    """Telethon mijozini va ingest pipeline'ni boshqaradi."""

    def __init__(self) -> None:
        self.client = TelegramClient(
            StringSession(config.string_session),
            config.api_id,
            config.api_hash,
        )
        # tg_channel_id (marked, -100...) -> db channel id
        self._monitored: dict[int, int] = {}
        self._started = False
        self.pipeline = IngestPipeline(self.client)

    # ----------------------------------------------------------
    #  Hayot sikli
    # ----------------------------------------------------------
    async def start(self) -> None:
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError(
                "Userbot avtorizatsiyadan o'tmagan. STRING_SESSION noto'g'ri yoki "
                "muddati o'tgan. login.py orqali yangi sessiya yarating."
            )
        # 1) Ingest workerlarini ishga tushiramiz
        self.pipeline.start()
        # 2) Hodisa handlerlari
        self.client.add_event_handler(self._on_new_message, events.NewMessage())
        self.client.add_event_handler(self._on_album, events.Album())
        self.client.add_event_handler(self._on_edit, events.MessageEdited())
        self.client.add_event_handler(self._on_delete, events.MessageDeleted())
        await self.refresh_monitored()
        self._started = True
        me = await self.client.get_me()
        logger.info("Userbot ishga tushdi: %s", getattr(me, "username", me.id))

    async def stop(self) -> None:
        await self.pipeline.stop()
        await self.client.disconnect()

    def is_connected(self) -> bool:
        return self.client.is_connected()

    # ----------------------------------------------------------
    #  Kuzatiladigan kanallar cache'i
    # ----------------------------------------------------------
    async def refresh_monitored(self) -> None:
        rows = await repo.get_all_monitored_channels()
        self._monitored = {row["tg_channel_id"]: row["id"] for row in rows}
        logger.info("Kuzatilayotgan kanallar: %d ta", len(self._monitored))

    # ----------------------------------------------------------
    #  Kanal qo'shish (bot handleridan chaqiriladi)
    # ----------------------------------------------------------
    async def add_channel(self, link: str) -> dict:
        username = parse_channel_link(link)
        if not username:
            return {
                "ok": False,
                "channel": None,
                "error": "Noto'g'ri link. Faqat ochiq kanal qo'llab-quvvatlanadi "
                "(masalan @kanal yoki https://t.me/kanal).",
            }

        entity = await safe_call(lambda: self.client.get_entity(username))
        if entity is None:
            return {
                "ok": False,
                "channel": None,
                "error": f"@{username} topilmadi yoki ochiq kanal emas.",
            }

        if not isinstance(entity, Channel) or getattr(entity, "broadcast", False) is False:
            return {
                "ok": False,
                "channel": None,
                "error": "Bu havola kanal emas (guruh yoki foydalanuvchi).",
            }

        # Kanalga qo'shilish (postlarni realtime olish uchun zarur)
        await safe_call(lambda: self.client(JoinChannelRequest(entity)))

        tg_id = utils.get_peer_id(entity)
        channel = await repo.upsert_channel(
            tg_channel_id=tg_id,
            username=getattr(entity, "username", None),
            title=getattr(entity, "title", None),
            access_hash=getattr(entity, "access_hash", None),
        )
        await self.refresh_monitored()
        # Yangi kanaldan so'nggi postlarni darhol backfill qilamiz (fon rejimida)
        if config.backfill_enabled:
            asyncio.create_task(self._safe_backfill_channel(channel, config.backfill_limit))
        return {"ok": True, "channel": channel, "error": None}

    # ----------------------------------------------------------
    #  Hodisa handlerlari (barchasi navbatga yo'naltiradi)
    # ----------------------------------------------------------
    async def _on_new_message(self, event) -> None:
        try:
            db_channel_id = self._monitored.get(event.chat_id)
            if db_channel_id is None:
                return  # kuzatilmaydigan chat
            msg = event.message
            # Albumlar events.Album orqali keladi — bu yerda o'tkazib yuboramiz (dublikatni oldini olish)
            if getattr(msg, "grouped_id", None):
                return
            metrics.messages_received.inc()
            await self.pipeline.enqueue(
                IngestJob("message", [msg], db_channel_id, event.chat_id)
            )
        except Exception as exc:  # noqa: BLE001
            metrics.ingest_errors.inc()
            logger.exception("NewMessage handler xatosi: %s", exc)

    async def _on_album(self, event) -> None:
        try:
            db_channel_id = self._monitored.get(event.chat_id)
            if db_channel_id is None:
                return
            msgs = list(event.messages)
            metrics.messages_received.inc(len(msgs))
            await self.pipeline.enqueue(
                IngestJob(
                    "album", msgs, db_channel_id, event.chat_id,
                    grouped_id=getattr(event, "grouped_id", None),
                )
            )
        except Exception as exc:  # noqa: BLE001
            metrics.ingest_errors.inc()
            logger.exception("Album handler xatosi: %s", exc)

    async def _on_edit(self, event) -> None:
        try:
            db_channel_id = self._monitored.get(event.chat_id)
            if db_channel_id is None:
                return
            msg = event.message
            when = getattr(msg, "edit_date", None) or datetime.now(timezone.utc)
            await repo.mark_post_edited(db_channel_id, msg.id, msg.message or "", when)
            metrics.edits_total.inc()
        except Exception as exc:  # noqa: BLE001
            logger.exception("MessageEdited handler xatosi: %s", exc)

    async def _on_delete(self, event) -> None:
        try:
            db_channel_id = self._monitored.get(event.chat_id) if event.chat_id else None
            if db_channel_id is None:
                return
            when = datetime.now(timezone.utc)
            for mid in event.deleted_ids:
                await repo.mark_post_deleted(db_channel_id, mid, when)
            metrics.deletes_total.inc(len(event.deleted_ids))
        except Exception as exc:  # noqa: BLE001
            logger.exception("MessageDeleted handler xatosi: %s", exc)

    # ----------------------------------------------------------
    #  Backfill (GetHistory) — bo'shliqlarni to'ldirish
    # ----------------------------------------------------------
    async def backfill_all(self, per_channel_limit: int | None = None) -> int:
        limit = per_channel_limit or config.backfill_limit
        channels = await repo.get_all_monitored_channels()
        total = 0
        logger.info("Backfill boshlandi: %d ta kanal (limit=%d).", len(channels), limit)
        for ch in channels:
            total += await self._safe_backfill_channel(ch, limit)
            await asyncio.sleep(0.5)  # flood limitdan saqlanish
        logger.info("Backfill yakunlandi: %d ta xabar navbatga qo'yildi.", total)
        return total

    async def _safe_backfill_channel(self, ch, limit: int) -> int:
        try:
            return await self._backfill_channel(ch, limit)
        except FloodWaitError as exc:
            metrics.floodwait_total.inc()
            logger.warning("Backfill flood-wait: %ss", exc.seconds)
            await asyncio.sleep(min(exc.seconds, 300) + 1)
            return 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("Backfill xatosi (%s): %s", ch.get("username"), exc)
            return 0

    async def _backfill_channel(self, ch, limit: int) -> int:
        """
        Kanaldagi oxirgi saqlangan xabardan keyingi (yangi) postlarni oladi.

        Ikki rejim:
          • Yangi kanal (last_id == 0) — butun tarixni emas, faqat eng so'nggi
            `limit` ta postni olamiz (tez va arzon).
          • Mavjud kanal (last_id > 0) — last_id dan keyingi BARCHA yangi postlar
            `reverse=True` bilan ESKIDAN-YANGIGA olinadi. Telethon o'zi sahifalaydi,
            shuning uchun `limit` cheklovi YO'Q — juda faol kanalda ham (bir sikl
            oralig'ida `limit` dan ko'p post kelsa) BO'SHLIQ QOLMAYDI.
            (Eski bug: `limit` bilan cheklangani uchun oradagilar tushib qolardi.)
        """
        last_id = await repo.get_max_message_id(ch["id"]) or 0
        ident = ch["username"] or ch["tg_channel_id"]
        count = 0

        if last_id <= 0:
            # Yangi kanal — eng so'nggi `limit` ta post (yangidan eskiga).
            iterator = self.client.iter_messages(ident, limit=limit)
        else:
            # Mavjud kanal — bo'shliqni to'liq to'ldiramiz (eskidan yangiga).
            # 0 => cheksiz; aks holda xavfsizlik shifti (bir siklda maks).
            cap = config.backfill_max_total or None
            iterator = self.client.iter_messages(
                ident, min_id=last_id, reverse=True, limit=cap
            )

        async for msg in iterator:
            if not (msg.message or msg.media):
                continue
            await self.pipeline.enqueue(
                IngestJob(
                    "message", [msg], ch["id"], ch["tg_channel_id"],
                    grouped_id=getattr(msg, "grouped_id", None),
                    source="backfill",
                )
            )
            count += 1
            metrics.backfill_messages.inc()
        await repo.set_channel_backfilled(ch["id"])
        return count

    # ----------------------------------------------------------
    #  Kanal "salomatligi" tekshiruvi
    # ----------------------------------------------------------
    async def check_channels(self, bot) -> None:
        channels = await repo.get_all_active_channels()
        logger.info("Health check: %d ta kanal tekshirilmoqda.", len(channels))
        for ch in channels:
            status = "ok"
            error: Optional[str] = None
            try:
                ident = ch["username"] or ch["tg_channel_id"]
                entity = await self.client.get_entity(ident)
                new_username = getattr(entity, "username", None)
                new_title = getattr(entity, "title", None)
                if new_username != ch["username"]:
                    await repo.update_channel_identity(ch["id"], new_username, new_title)
                    status = "renamed"
                    error = f"username o'zgardi: @{ch['username']} → @{new_username}"
                elif new_title != ch["title"]:
                    await repo.update_channel_identity(ch["id"], new_username, new_title)
            except ChannelPrivateError:
                status, error = "private", "kanal yopiq (private) bo'lib qoldi"
            except (UsernameNotOccupiedError, UsernameInvalidError, ValueError):
                status, error = "deleted", "kanal topilmadi yoki o'chirilgan"
            except FloodWaitError as exc:
                metrics.floodwait_total.inc()
                logger.warning("Health check flood-wait: %ss", exc.seconds)
                await asyncio.sleep(min(exc.seconds, 60))
                continue
            except Exception as exc:  # noqa: BLE001
                status, error = "error", str(exc)[:200]

            await repo.update_channel_health(ch["id"], status, error)
            if status != "ok":
                await self._notify_admins(bot, ch, status, error)
            await asyncio.sleep(0.5)  # flood limitdan saqlanish

    async def _notify_admins(self, bot, ch, status: str, error: Optional[str]) -> None:
        title = ch["title"] or ch["username"] or ch["tg_channel_id"]
        text = (
            "⚠️ <b>Kanal muammosi aniqlandi</b>\n\n"
            f"📡 Kanal: {title}\n"
            f"🔖 @{ch['username']}\n"
            f"📊 Holat: <b>{status}</b>\n"
            f"💬 {error or ''}"
        )
        for admin_id in config.admin_ids:
            try:
                await bot.send_message(admin_id, text)
            except Exception:  # noqa: BLE001
                pass
        await repo.log_audit(
            "channel_health",
            details={"channel_id": ch["id"], "status": status, "error": error},
        )


# Global yagona obyekt (main.py da yaratiladi)
userbot: Optional[Userbot] = None


def init_userbot() -> Userbot:
    global userbot
    userbot = Userbot()
    return userbot
