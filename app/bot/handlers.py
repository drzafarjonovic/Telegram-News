"""
Foydalanuvchi handlerlari (aiogram).

Buyruqlar: /start, /help, /add, /list, /remove, /time
Tugmalar orqali ham boshqariladi (MAIN_MENU).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import config
from app import userbot as userbot_mod
from app.db import repository as repo
from app.bot import keyboards as kb

logger = logging.getLogger(__name__)

user_router = Router(name="user")

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class AddChannel(StatesGroup):
    waiting_link = State()


class DailyTime(StatesGroup):
    waiting_times = State()


# ============================================================
#  Middleware: foydalanuvchini ro'yxatga olish + ban tekshirish
# ============================================================
class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        # Bloklangan foydalanuvchini to'xtatamiz
        if await repo.is_banned(user.id):
            if isinstance(event, Message):
                await event.answer("⛔️ Siz botdan foydalanish huquqidan mahrum qilingansiz.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔️ Bloklangansiz.", show_alert=True)
            return None

        await repo.upsert_user(user.id, user.username, user.first_name)
        return await handler(event, data)


# ============================================================
#  /start, /help
# ============================================================
WELCOME = (
    "👋 <b>Assalomu alaykum!</b>\n\n"
    "Men kanal yangiliklarini AI yordamida tahlil qilib beruvchi botman.\n\n"
    "📌 <b>Qanday ishlaydi?</b>\n"
    "1️⃣ Menga kuzatmoqchi bo'lgan <b>ochiq kanal</b> linkini yuboring "
    "(masalan <code>@kanal</code> yoki <code>https://t.me/kanal</code>).\n"
    "2️⃣ <b>⏰ Vaqt sozlash</b> orqali qanchalik tez-tez xulosa olishni tanlang.\n"
    "3️⃣ Belgilangan vaqtda men kanallardagi postlarni <b>mavzular bo'yicha</b> "
    "guruhlab, mazmunini yuboraman.\n\n"
    "Quyidagi tugmalardan foydalaning 👇"
)

HELP = (
    "ℹ️ <b>Yordam</b>\n\n"
    "<b>Buyruqlar:</b>\n"
    "/add <code>@kanal</code> — kanal qo'shish\n"
    "/list — kanallaringiz ro'yxati\n"
    "/remove — kanalni o'chirish\n"
    "/time — digest vaqtini sozlash\n"
    "/menu — boshqaruv menyusi (qiziqishlar, rejim, tarix)\n"
    "/help — yordam\n\n"
    "💡 Shunchaki kanal linkini yuborsangiz ham qo'shiladi.\n"
    "⚠️ Faqat <b>ochiq</b> kanallar qo'llab-quvvatlanadi."
)


@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME, parse_mode=ParseMode.HTML, reply_markup=kb.MAIN_MENU)


@user_router.message(Command("help"))
@user_router.message(F.text == "ℹ️ Yordam")
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, parse_mode=ParseMode.HTML, reply_markup=kb.MAIN_MENU)


# ============================================================
#  Kanal qo'shish
# ============================================================
@user_router.message(F.text == "➕ Kanal qo'shish")
async def ask_channel(message: Message, state: FSMContext) -> None:
    await state.set_state(AddChannel.waiting_link)
    await message.answer(
        "📥 Kanal linkini yuboring (masalan <code>@kanal</code> yoki "
        "<code>https://t.me/kanal</code>):",
        parse_mode=ParseMode.HTML,
    )


@user_router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await state.set_state(AddChannel.waiting_link)
        await message.answer("📥 Kanal linkini yuboring:")
        return
    await _do_add_channel(message, parts[1], state)


async def _do_add_channel(message: Message, link: str, state: FSMContext) -> None:
    await state.clear()
    user_id = message.from_user.id

    # Limit tekshirish
    user = await repo.get_user(user_id)
    limit = (user and user["max_channels"]) or config.max_channels_per_user
    if await repo.count_subscriptions(user_id) >= limit:
        await message.answer(
            f"⚠️ Siz maksimal {limit} ta kanal qo'sha olasiz. "
            "Avval bittasini /remove orqali o'chiring."
        )
        return

    if userbot_mod.userbot is None:
        await message.answer("⚙️ Tizim hali tayyor emas, birozdan so'ng urinib ko'ring.")
        return

    status = await message.answer("⏳ Kanal tekshirilmoqda...")
    result = await userbot_mod.userbot.add_channel(link)

    if not result["ok"]:
        await status.edit_text(f"❌ {result['error']}")
        return

    channel = result["channel"]
    is_new = await repo.subscribe(user_id, channel["id"])
    title = channel["title"] or channel["username"] or "kanal"

    if is_new:
        await status.edit_text(
            f"✅ <b>{title}</b> qo'shildi! Endi bu kanal kuzatiladi.",
            parse_mode=ParseMode.HTML,
        )
        await repo.log_audit(
            "add_channel", actor_id=user_id,
            details={"channel": title, "channel_id": channel["id"]},
        )
    else:
        await status.edit_text(f"ℹ️ <b>{title}</b> allaqachon ro'yxatingizda bor.",
                               parse_mode=ParseMode.HTML)


@user_router.message(StateFilter(AddChannel.waiting_link), F.text)
async def receive_link(message: Message, state: FSMContext) -> None:
    await _do_add_channel(message, message.text, state)


# ============================================================
#  Kanallar ro'yxati / o'chirish
# ============================================================
@user_router.message(Command("list"))
@user_router.message(Command("remove"))
@user_router.message(F.text == "📋 Mening kanallarim")
async def cmd_list(message: Message) -> None:
    channels = await repo.get_user_channels(message.from_user.id)
    if not channels:
        await message.answer(
            "📭 Hali kanal qo'shmagansiz. <b>➕ Kanal qo'shish</b> tugmasini bosing.",
            parse_mode=ParseMode.HTML,
        )
        return
    await message.answer(
        f"📋 <b>Sizning kanallaringiz ({len(channels)} ta):</b>\n"
        "O'chirish uchun kanal ustiga bosing 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.channels_keyboard(channels),
    )


@user_router.callback_query(F.data.startswith("rm:"))
async def cb_remove(callback: CallbackQuery) -> None:
    channel_id = int(callback.data.split(":")[1])
    removed = await repo.unsubscribe(callback.from_user.id, channel_id)
    if removed and userbot_mod.userbot is not None:
        await userbot_mod.userbot.refresh_monitored()
        await repo.log_audit(
            "remove_channel", actor_id=callback.from_user.id,
            details={"channel_id": channel_id},
        )
    channels = await repo.get_user_channels(callback.from_user.id)
    if channels:
        await callback.message.edit_reply_markup(
            reply_markup=kb.channels_keyboard(channels)
        )
    else:
        await callback.message.edit_text("📭 Barcha kanallar o'chirildi.")
    await callback.answer("O'chirildi" if removed else "Topilmadi")


@user_router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


# ============================================================
#  Vaqt sozlash
# ============================================================
def _format_schedule(schedule) -> str:
    if not schedule or not schedule["is_active"]:
        return "❌ Hozircha sozlanmagan (digest yuborilmaydi)."
    if schedule["mode"] == "interval":
        return f"🔁 Har <b>{schedule['interval_hours']} soatda</b>"
    times = ", ".join(schedule["daily_times"] or [])
    return f"🕘 Har kuni soat <b>{times}</b> (Toshkent vaqti)"


@user_router.message(Command("time"))
@user_router.message(F.text == "⏰ Vaqt sozlash")
async def cmd_time(message: Message) -> None:
    schedule = await repo.get_schedule(message.from_user.id)
    await message.answer(
        f"⏰ <b>Digest vaqti</b>\n\nJoriy sozlama: {_format_schedule(schedule)}\n\n"
        "Yangi oraliqni tanlang:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.time_keyboard(),
    )


@user_router.callback_query(F.data.startswith("time:interval:"))
async def cb_set_interval(callback: CallbackQuery) -> None:
    hours = int(callback.data.split(":")[2])
    await repo.set_interval_schedule(callback.from_user.id, hours)
    await repo.log_audit(
        "set_schedule", actor_id=callback.from_user.id,
        details={"mode": "interval", "hours": hours},
    )
    await callback.message.edit_text(
        f"✅ Tayyor! Endi har <b>{hours} soatda</b> yangiliklar xulosasini olasiz.",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@user_router.callback_query(F.data == "time:off")
async def cb_time_off(callback: CallbackQuery) -> None:
    await repo.set_schedule_active(callback.from_user.id, False)
    await callback.message.edit_text("⏸ Digest yuborish to'xtatildi.")
    await callback.answer()


@user_router.callback_query(F.data == "time:daily")
async def cb_time_daily(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DailyTime.waiting_times)
    await callback.message.edit_text(
        "🕘 <b>Aniq vaqt rejimi</b>\n\n"
        "Har kuni qaysi soat(lar)da xulosa kerakligini yozing.\n"
        "Masalan: <code>09:00</code> yoki <code>09:00, 18:00, 22:30</code>\n\n"
        "(Toshkent vaqti)",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@user_router.message(StateFilter(DailyTime.waiting_times), F.text)
async def receive_daily_times(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").replace(" ", "")
    times: list[str] = []
    for part in raw.split(","):
        if not part:
            continue
        if not _TIME_RE.match(part):
            await message.answer(
                f"❌ <code>{part}</code> noto'g'ri format. "
                "Vaqtni <code>HH:MM</code> ko'rinishida yozing (masalan 09:00).",
                parse_mode=ParseMode.HTML,
            )
            return
        # Normalizatsiya (9:0 -> 09:00)
        hh, mm = part.split(":")
        times.append(f"{int(hh):02d}:{int(mm):02d}")

    if not times:
        await message.answer("❌ Hech qanday vaqt kiritilmadi.")
        return

    times = sorted(set(times))
    await repo.set_daily_schedule(message.from_user.id, times)
    await repo.log_audit(
        "set_schedule", actor_id=message.from_user.id,
        details={"mode": "daily", "times": times},
    )
    await state.clear()
    await message.answer(
        f"✅ Tayyor! Har kuni soat <b>{', '.join(times)}</b> da "
        "(Toshkent vaqti) xulosa olasiz.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.MAIN_MENU,
    )


# ============================================================
#  FAZA 2 — Inline menyu (/menu)
# ============================================================
MENU_TEXT = "⚙️ <b>Boshqaruv menyusi</b>\nKerakli bo'limni tanlang:"


@user_router.message(Command("menu"))
@user_router.message(F.text == "⚙️ Menyu")
async def cmd_menu(message: Message) -> None:
    await message.answer(
        MENU_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb.main_menu_inline()
    )


# ============================================================
#  Linkka o'xshash matnni avtomatik qabul qilish (fallback)
# ============================================================
@user_router.message(F.text, StateFilter(None))
async def maybe_link(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    looks_like_link = text.startswith("@") or "t.me/" in text
    if looks_like_link and userbot_mod.parse_channel_link(text):
        await _do_add_channel(message, text, state)
    else:
        await message.answer(
            "🤔 Tushunmadim. Kanal linkini yuboring yoki tugmalardan foydalaning.",
            reply_markup=kb.MAIN_MENU,
        )



# ============================================================
#  FAZA 2 — Inline menyu callbacklari
# ============================================================
@user_router.callback_query(F.data == "m:menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        MENU_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb.main_menu_inline()
    )
    await callback.answer()


@user_router.callback_query(F.data == "m:add")
async def cb_menu_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddChannel.waiting_link)
    await callback.message.answer(
        "📥 Kanal linkini yuboring (masalan <code>@kanal</code>):",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@user_router.callback_query(F.data == "m:channels")
async def cb_menu_channels(callback: CallbackQuery) -> None:
    channels = await repo.get_user_channels(callback.from_user.id)
    if not channels:
        await callback.message.edit_text(
            "📭 Hali kanal qo'shmagansiz.",
            reply_markup=kb.back_menu(),
        )
    else:
        await callback.message.edit_text(
            f"📋 <b>Kanallaringiz ({len(channels)} ta)</b>\nO'chirish uchun bosing:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.channels_keyboard(channels),
        )
    await callback.answer()


@user_router.callback_query(F.data == "m:time")
async def cb_menu_time(callback: CallbackQuery) -> None:
    schedule = await repo.get_schedule(callback.from_user.id)
    await callback.message.edit_text(
        f"⏰ <b>Digest vaqti</b>\n\nJoriy: {_format_schedule(schedule)}\n\nYangi oraliqni tanlang:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.time_keyboard(),
    )
    await callback.answer()


@user_router.callback_query(F.data == "m:help")
async def cb_menu_help(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        HELP, parse_mode=ParseMode.HTML, reply_markup=kb.back_menu()
    )
    await callback.answer()


# ---------- Qiziqishlar (#7) ----------
async def _show_interests(callback: CallbackQuery) -> None:
    user = await repo.get_user(callback.from_user.id)
    selected = list(user["interests"]) if user and user["interests"] else []
    note = (
        "Hammasi (filtrlanmaydi)" if not selected else ", ".join(selected)
    )
    await callback.message.edit_text(
        "🎯 <b>Qiziqishlar</b>\n\n"
        "Faqat sizni qiziqtirgan kategoriyalarni tanlang. "
        "Hech narsa tanlanmasa — barcha yangiliklar keladi.\n\n"
        f"Joriy: <b>{note}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.interests_keyboard(selected),
    )


@user_router.callback_query(F.data == "m:interests")
async def cb_menu_interests(callback: CallbackQuery) -> None:
    await _show_interests(callback)
    await callback.answer()


@user_router.callback_query(F.data.startswith("int:"))
async def cb_toggle_interest(callback: CallbackQuery) -> None:
    value = callback.data.split(":", 1)[1]
    user = await repo.get_user(callback.from_user.id)
    selected = list(user["interests"]) if user and user["interests"] else []

    if value == "clear":
        selected = []
    elif value in selected:
        selected.remove(value)
    else:
        selected.append(value)

    await repo.set_interests(callback.from_user.id, selected)
    await repo.log_audit(
        "set_interests", actor_id=callback.from_user.id,
        details={"interests": selected},
    )
    await _show_interests(callback)
    await callback.answer()


# ---------- Muhimlik rejimi (#8) ----------
async def _show_mode(callback: CallbackQuery) -> None:
    user = await repo.get_user(callback.from_user.id)
    current = (user["importance_min"] if user else 1) or 1
    await callback.message.edit_text(
        "🔎 <b>Yangilik rejimi</b>\n\n"
        "📋 Hammasi — barcha yangiliklar\n"
        "⭐ Muhimlari — faqat muhim (3+)\n"
        "🔥 Eng muhimlari — faqat eng muhim (4+)\n",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.mode_keyboard(current),
    )


@user_router.callback_query(F.data == "m:mode")
async def cb_menu_mode(callback: CallbackQuery) -> None:
    await _show_mode(callback)
    await callback.answer()


@user_router.callback_query(F.data.startswith("mode:"))
async def cb_set_mode(callback: CallbackQuery) -> None:
    value = int(callback.data.split(":")[1])
    await repo.set_importance_min(callback.from_user.id, value)
    await repo.log_audit(
        "set_mode", actor_id=callback.from_user.id, details={"importance_min": value}
    )
    await _show_mode(callback)
    await callback.answer("Saqlandi ✅")


# ---------- Digest tarixi (#10) ----------
@user_router.callback_query(F.data == "m:history")
async def cb_menu_history(callback: CallbackQuery) -> None:
    digests = await repo.get_user_digests(callback.from_user.id, limit=10)
    if not digests:
        await callback.message.edit_text(
            "📭 Hali digest tarixi yo'q (oxirgi 7 kun).",
            reply_markup=kb.back_menu(),
        )
    else:
        await callback.message.edit_text(
            "📚 <b>Digest tarixi</b> (oxirgi 7 kun)\nKo'rish uchun tanlang:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.history_keyboard(digests),
        )
    await callback.answer()


@user_router.callback_query(F.data.startswith("hist:"))
async def cb_show_history(callback: CallbackQuery) -> None:
    from app.digest import split_for_telegram

    digest_id = int(callback.data.split(":")[1])
    row = await repo.get_digest(digest_id, callback.from_user.id)
    if not row or not row["content"]:
        await callback.answer("Topilmadi", show_alert=True)
        return
    await callback.answer()
    for part in split_for_telegram(row["content"]):
        await callback.message.answer(
            part, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
