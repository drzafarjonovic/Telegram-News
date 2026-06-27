"""
Userbot (Telethon) — ochiq kanallarni realtime kuzatadi.

Vazifalar:
  • Foydalanuvchi yuborgan kanal linkini hal qilish va kanalga qo'shilish.
  • Kuzatilayotgan kanallardagi har bir yangi postni Postgres'ga saqlash.
  • Kuzatiladigan kanallar ro'yxatini bazadan yangilab turish (cache).
"""
from __future__ import annotations

import asyncio
import logging
import re
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
from app.db import repository as repo

logger = logging.getLogger(__name__)

# Link formatlari: @username | https://t.me/username | t.me/username | username
_USERNAME_RE = re.compile(
    r"(?:https?://)?(?:t\.me/|telegram\.me/)?@?([A-Za-z][A-Za-z0-9_]{3,31})/?$"
)


def parse_channel_link(text: str) -> Optional[str]:
    """Matndan kanal username'ini ajratadi. Topilmasa None."""
    text = (text or "").strip()
    # Yopiq (invite) linklar qo'llab-quvvatlanmaydi
    if "t.me/+" in text or "joinchat" in text:
        return None
    m = _USERNAME_RE.match(text)
    if not m:
        return None
    username = m.group(1)
    # "joinchat", "share" kabi xizmat so'zlari emasligini tekshirish shart emas
    return username


class Userbot:
    """Telethon mijozini boshqaradi."""

    def __init__(self) -> None:
        self.client = TelegramClient(
            StringSession(config.string_session),
            config.api_id,
            config.api_hash,
        )
        # tg_channel_id (marked, -100...) -> db channel id
        self._monitored: dict[int, int] = {}
        self._started = False

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
        self.client.add_event_handler(self._on_new_message, events.NewMessage())
        await self.refresh_monitored()
        self._started = True
        me = await self.client.get_me()
        logger.info("Userbot ishga tushdi: %s", getattr(me, "username", me.id))

    async def stop(self) -> None:
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
        """
        Linkni hal qiladi, kanalga qo'shiladi va bazaga yozadi.
        Qaytaradi: {"ok": bool, "channel": Record|None, "error": str|None}
        """
        username = parse_channel_link(link)
        if not username:
            return {
                "ok": False,
                "channel": None,
                "error": "Noto'g'ri link. Faqat ochiq kanal qo'llab-quvvatlanadi "
                "(masalan @kanal yoki https://t.me/kanal).",
            }

        try:
            entity = await self.client.get_entity(username)
        except Exception:  # noqa: BLE001
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
        try:
            await self.client(JoinChannelRequest(entity))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Kanalga qo'shilishda ogohlantirish (%s): %s", username, exc)
            # Ba'zan allaqachon a'zo bo'lsa xato beradi — davom etamiz

        tg_id = utils.get_peer_id(entity)
        channel = await repo.upsert_channel(
            tg_channel_id=tg_id,
            username=getattr(entity, "username", None),
            title=getattr(entity, "title", None),
            access_hash=getattr(entity, "access_hash", None),
        )
        await self.refresh_monitored()
        return {"ok": True, "channel": channel, "error": None}

    # ----------------------------------------------------------
    #  Yangi post hodisasi
    # ----------------------------------------------------------
    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        try:
            chat_id = event.chat_id
            db_channel_id = self._monitored.get(chat_id)
            if db_channel_id is None:
                return  # kuzatilmaydigan chat

            text = event.message.message or ""
            if not text.strip():
                return  # faqat media — matnsiz postni o'tkazib yuboramiz

            await repo.insert_post(
                channel_id=db_channel_id,
                tg_message_id=event.message.id,
                text=text,
                posted_at=event.message.date,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Post saqlashda xatolik: %s", exc)

    # ----------------------------------------------------------
    #  Kanal "salomatligi" tekshiruvi (#4)
    # ----------------------------------------------------------
    async def check_channels(self, bot) -> None:
        """
        Har bir faol kanalni tekshiradi: o'chirilganmi, yopiq bo'lib qolganmi,
        username o'zgarganmi. Muammo bo'lsa adminlarni ogohlantiradi.
        """
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
