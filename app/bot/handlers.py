"""
Foydalanuvchi handlerlari (aiogram) — v3.0.

Yangi interfeys:
  • Bitta doimiy 🏠 Menyu tugmasi + o'z-o'zini yangilaydigan inline menyu.
  • Qadamli boshlang'ich sozlash (onboarding).
  • Kanal kartochkasi + o'chirishdan oldin tasdiqlash.
  • 📬 Hozir yuborish (on-demand digest, cheklov bilan).
  • Jadval menyusi: interval, aniq vaqt, aqlli rejim, jim soatlar,
    dam olish jadvali, shoshilinch xabarlar, bo'sh digest.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import config
from app import userbot as userbot_mod
from app import digest as digest_mod
from app.db import repository as repo
from app.bot import keyboards as kb

logger = logging.getLogger(__name__)

user_router = Router(name="user")

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_QUIET_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)\s*[-–]\s*([01]?\d|2[0-3]):([0-5]\d)$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AddChannel(StatesGroup):
    waiting_link = State()


class DailyTime(StatesGroup):
    waiting_times = State()
    waiting_weekend_times = State()


class QuietTime(StatesGroup):
    waiting_range = State()


class Onb(StatesGroup):
    channel = State()


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

        if await repo.is_banned(user.id):
            if isinstance(event, Message):
                await event.answer("⛔️ Siz botdan foydalanish huquqidan mahrum qilingansiz.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔️ Bloklangansiz.", show_alert=True)
            return None

        await repo.upsert_user(user.id, user.username, user.first_name)
        return await handler(event, data)


# ============================================================
#  Matnlar
# ============================================================
MENU_TEXT = "🏠 <b>Asosiy menyu</b>\nKerakli bo'limni tanlang:"

WELCOME = (
    "👋 <b>Assalomu alaykum!</b>\n\n"
    "Men Telegram kanallaridagi yangiliklarni AI yordamida tahlil qilib, "
    "siz uchun qisqa xulosalar (digest) tayyorlab beruvchi botman.\n\n"
    "Boshlash uchun quyidagi tugmani bosing 👇"
)

HELP = (
    "ℹ️ <b>Yordam</b>\n\n"
    "🏠 <b>Menyu</b> — barcha imkoniyatlar shu yerda.\n\n"
    "<b>Asosiy imkoniyatlar:</b>\n"
    "• ➕ <b>Kanal qo'shish</b> — bir nechta kanalni birdaniga qo'shish mumkin "
    "(har birini alohida qatorga yozing).\n"
    "• 📋 <b>Kanallarim</b> — kanal kartochkasi (post soni, holati) va o'chirish.\n"
    "• ⏰ <b>Jadval</b> — digest oralig'i, aniq vaqt, aqlli rejim, jim soatlar, "
    "dam olish jadvali, shoshilinch xabarlar.\n"
    "• 📬 <b>Hozir yuborish</b> — xulosani darhol olish.\n"
    "• 🎯 <b>Qiziqishlar</b> va 🔎 <b>Rejim</b> — nima kelishini boshqarish.\n\n"
    "<b>Buyruqlar:</b> /start /menu /add /list /time /now /help\n"
    "⚠️ Faqat <b>ochiq</b> kanallar qo'llab-quvvatlanadi."
)


# ============================================================
#  /start — onboarding yoki menyu
# ============================================================
@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await repo.get_user(message.from_user.id)
    onboarded = bool(user and user["onboarded"])
    if not onboarded:
        await message.answer(
            WELCOME, parse_mode=ParseMode.HTML, reply_markup=kb.MAIN_MENU
        )
        await message.answer(
            "🧭 <b>Keling, 3 qadamda sozlab olamiz:</b>\n"
            "1️⃣ Kanal qo'shish\n2️⃣ Qiziqishlar\n3️⃣ Qanchalik tez-tez\n\n"
            "Har qadamni o'tkazib yuborsangiz ham bo'ladi.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.onb_start_keyboard(),
        )
        return
    await message.answer(
        MENU_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb.MAIN_MENU
    )
    await message.answer(
        MENU_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb.main_menu_inline()
    )


@user_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, parse_mode=ParseMode.HTML, reply_markup=kb.MAIN_MENU)


@user_router.message(Command("menu"))
@user_router.message(F.text == "🏠 Menyu")
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        MENU_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb.main_menu_inline()
    )


@user_router.callback_query(F.data == "m:menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _safe_edit(callback, MENU_TEXT, kb.main_menu_inline())
    await callback.answer()


async def _safe_edit(callback: CallbackQuery, text: str, markup) -> None:
    """edit_text, agar imkoni bo'lmasa yangi xabar yuboradi."""
    try:
        await callback.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup,
            disable_web_page_preview=True,
        )
    except Exception:  # noqa: BLE001
        await callback.message.answer(
            text, parse_mode=ParseMode.HTML, reply_markup=markup,
            disable_web_page_preview=True,
        )


@user_router.callback_query(F.data == "m:help")
async def cb_menu_help(callback: CallbackQuery) -> None:
    await _safe_edit(callback, HELP, kb.back_menu())
    await callback.answer()


# ============================================================
#  Kanal qo'shish (bir nechta — har qatorda bittadan)
# ============================================================
ASK_CHANNEL = (
    "📥 Kanal linkini yuboring (masalan <code>@kanal</code> yoki "
    "<code>https://t.me/kanal</code>).\n\n"
    "💡 Bir nechta kanalni birdaniga qo'shish uchun har birini "
    "<b>alohida qatorga</b> yozing."
)


@user_router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await state.set_state(AddChannel.waiting_link)
        await message.answer(ASK_CHANNEL, parse_mode=ParseMode.HTML)
        return
    await _add_channels(message, parts[1], state)


@user_router.message(StateFilter(AddChannel.waiting_link), F.text)
async def receive_link(message: Message, state: FSMContext) -> None:
    await _add_channels(message, message.text, state)


async def _add_channels(message: Message, raw: str, state: FSMContext) -> None:
    """Bir yoki bir nechta kanalni qo'shadi (har qatorda bittadan)."""
    await state.clear()
    user_id = message.from_user.id
    links = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    if not links:
        await message.answer("❌ Kanal linki topilmadi.")
        return

    if userbot_mod.userbot is None:
        await message.answer("⚙️ Tizim hali tayyor emas, birozdan so'ng urinib ko'ring.")
        return

    user = await repo.get_user(user_id)
    limit = (user and user["max_channels"]) or config.max_channels_per_user

    status = await message.answer("⏳ Kanallar tekshirilmoqda...")
    added, skipped, failed = [], [], []

    for link in links:
        if await repo.count_subscriptions(user_id) >= limit:
            failed.append(f"{link} — limit ({limit} ta) to'ldi")
            continue
        result = await userbot_mod.userbot.add_channel(link)
        if not result["ok"]:
            failed.append(f"{link} — {result['error']}")
            continue
        channel = result["channel"]
        title = channel["title"] or channel["username"] or "kanal"
        is_new = await repo.subscribe(user_id, channel["id"])
        if is_new:
            added.append(title)
            await repo.log_audit(
                "add_channel", actor_id=user_id,
                details={"channel": title, "channel_id": channel["id"]},
            )
        else:
            skipped.append(title)

    lines = []
    if added:
        lines.append("✅ <b>Qo'shildi:</b> " + ", ".join(added))
    if skipped:
        lines.append("ℹ️ <b>Avval bor edi:</b> " + ", ".join(skipped))
    if failed:
        lines.append("❌ <b>Qo'shilmadi:</b>\n• " + "\n• ".join(failed))
    text = "\n\n".join(lines) or "❌ Hech nima qo'shilmadi."
    await status.edit_text(text, parse_mode=ParseMode.HTML)


@user_router.callback_query(F.data == "m:add")
async def cb_menu_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddChannel.waiting_link)
    await callback.message.answer(ASK_CHANNEL, parse_mode=ParseMode.HTML)
    await callback.answer()


# ============================================================
#  Kanallar ro'yxati + kartochka + xavfsiz o'chirish
# ============================================================
@user_router.message(Command("list"))
@user_router.message(Command("remove"))
async def cmd_list(message: Message) -> None:
    channels = await repo.get_user_channels(message.from_user.id)
    if not channels:
        await message.answer(
            "📭 Hali kanal qo'shmagansiz. ➕ tugmasi orqali qo'shing.",
            reply_markup=kb.main_menu_inline(),
        )
        return
    await message.answer(
        f"📋 <b>Kanallaringiz ({len(channels)} ta)</b>\nKartochkani ochish uchun bosing:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.channels_keyboard(channels),
    )


@user_router.callback_query(F.data == "m:channels")
async def cb_menu_channels(callback: CallbackQuery) -> None:
    channels = await repo.get_user_channels(callback.from_user.id)
    if not channels:
        await _safe_edit(callback, "📭 Hali kanal qo'shmagansiz.", kb.channels_keyboard([]))
    else:
        await _safe_edit(
            callback,
            f"📋 <b>Kanallaringiz ({len(channels)} ta)</b>\nKartochkani ochish uchun bosing:",
            kb.channels_keyboard(channels),
        )
    await callback.answer()


def _health_emoji(status: str | None) -> str:
    return {"ok": "🟢", "warning": "🟡", "error": "🔴"}.get(status or "ok", "🟢")


@user_router.callback_query(F.data.startswith("ch:"))
async def cb_channel_card(callback: CallbackQuery) -> None:
    channel_id = int(callback.data.split(":")[1])
    card = await repo.get_channel_card(callback.from_user.id, channel_id)
    if not card:
        await callback.answer("Topilmadi", show_alert=True)
        return
    title = card["title"] or card["username"] or str(channel_id)
    uname = f"@{card['username']}" if card["username"] else "—"
    last_post = card["last_post_at"].strftime("%d.%m.%Y %H:%M") if card["last_post_at"] else "—"
    text = (
        f"📰 <b>{title}</b>\n\n"
        f"🔗 Username: {uname}\n"
        f"🗂 Postlar (bazada): <b>{card['post_count']}</b>\n"
        f"🕒 Oxirgi post: {last_post}\n"
        f"{_health_emoji(card['health_status'])} Holati: {card['health_status'] or 'ok'}"
    )
    await _safe_edit(callback, text, kb.channel_card_keyboard(channel_id))
    await callback.answer()


@user_router.callback_query(F.data.startswith("rmask:"))
async def cb_remove_ask(callback: CallbackQuery) -> None:
    channel_id = int(callback.data.split(":")[1])
    await _safe_edit(
        callback,
        "❗ <b>Rostdan ham bu kanalni o'chirmoqchimisiz?</b>\n"
        "Kanal kuzatuvdan olib tashlanadi.",
        kb.confirm_remove_keyboard(channel_id),
    )
    await callback.answer()


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
        await _safe_edit(
            callback,
            f"🗑 O'chirildi.\n\n📋 <b>Kanallaringiz ({len(channels)} ta)</b>:",
            kb.channels_keyboard(channels),
        )
    else:
        await _safe_edit(callback, "📭 Barcha kanallar o'chirildi.", kb.channels_keyboard([]))
    await callback.answer("O'chirildi" if removed else "Topilmadi")


@user_router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


# ============================================================
#  📬 Hozir yuborish (on-demand digest)
# ============================================================
@user_router.message(Command("now"))
async def cmd_now(message: Message) -> None:
    await _send_now(message.from_user.id, message)


@user_router.callback_query(F.data == "m:now")
async def cb_now(callback: CallbackQuery) -> None:
    await callback.answer("⏳ Tayyorlanmoqda...")
    await _send_now(callback.from_user.id, callback.message)


async def _send_now(user_id: int, message: Message) -> None:
    user = await repo.get_user(user_id)
    cd = max(0, config.manual_digest_cooldown_min)
    last = user["last_manual_digest_at"] if user else None
    if last and cd:
        elapsed = _now() - last
        if elapsed < timedelta(minutes=cd):
            left = cd - int(elapsed.total_seconds() // 60)
            await message.answer(
                f"⏳ Yaqinda xulosa oldingiz. Iltimos, yana <b>{max(1, left)} daqiqa</b> kuting.",
                parse_mode=ParseMode.HTML,
            )
            return

    since = last or (_now() - timedelta(hours=6))
    result = await digest_mod.build_digest(user_id, since, _now())
    await repo.touch_manual_digest(user_id)

    if result is None:
        await message.answer("🔕 Oxirgi yuborilgandan beri yangi muhim yangilik yo'q.")
        return
    for part in digest_mod.split_for_telegram(result["content"]):
        await message.answer(
            part, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )


# ============================================================
#  ⏰ Jadval menyusi
# ============================================================
def _fmt_interval(schedule) -> str:
    minutes = schedule["interval_minutes"] or ((schedule["interval_hours"] or 6) * 60)
    if minutes % 60 == 0:
        return f"{minutes // 60} soat"
    return f"{minutes} daqiqa"


def _schedule_text(schedule) -> str:
    if not schedule:
        return (
            "⏰ <b>Jadval</b>\n\nHozircha sozlanmagan.\n"
            "Quyidan oraliq yoki aniq vaqtni tanlang."
        )
    if not schedule["is_active"]:
        base = "⏸ <b>To'xtatilgan</b> (digest yuborilmaydi)."
    elif schedule["mode"] == "interval":
        base = f"🔁 Har <b>{_fmt_interval(schedule)}da</b>"
    else:
        times = ", ".join(schedule["daily_times"] or [])
        base = f"🕘 Har kuni soat <b>{times}</b> (Toshkent)"

    extras = []
    if schedule["smart_mode"]:
        extras.append(f"🧠 aqlli ({schedule['smart_min_stories']}+ muhim)")
    if schedule["breaking_enabled"]:
        extras.append("⚡ shoshilinch")
    if schedule["quiet_enabled"]:
        extras.append(f"🌙 jim {schedule['quiet_start']}–{schedule['quiet_end']}")
    if schedule["weekend_enabled"]:
        extras.append("📅 dam olish jadvali")
    tail = ("\n\n" + " · ".join(extras)) if extras else ""
    return f"⏰ <b>Jadval</b>\n\nJoriy: {base}{tail}\n\nSozlamalar 👇"


async def _show_schedule(message: Message, user_id: int, edit_cb: CallbackQuery | None = None) -> None:
    schedule = await repo.get_schedule(user_id)
    text = _schedule_text(schedule)
    markup = kb.schedule_menu_keyboard(schedule)
    if edit_cb is not None:
        await _safe_edit(edit_cb, text, markup)
    else:
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


@user_router.message(Command("time"))
async def cmd_time(message: Message) -> None:
    await _show_schedule(message, message.from_user.id)


@user_router.callback_query(F.data == "m:time")
async def cb_menu_time(callback: CallbackQuery) -> None:
    await _show_schedule(callback.message, callback.from_user.id, edit_cb=callback)
    await callback.answer()


@user_router.callback_query(F.data == "sc:back")
async def cb_sc_back(callback: CallbackQuery) -> None:
    await _show_schedule(callback.message, callback.from_user.id, edit_cb=callback)
    await callback.answer()


@user_router.callback_query(F.data == "sc:interval")
async def cb_sc_interval(callback: CallbackQuery) -> None:
    await _safe_edit(
        callback,
        "⏱ <b>Oraliqni tanlang</b> — shu vaqtda bir marta xulosa keladi:",
        kb.interval_keyboard(prefix="time:min", back="sc:back"),
    )
    await callback.answer()


@user_router.callback_query(F.data.startswith("time:min:"))
async def cb_set_interval(callback: CallbackQuery) -> None:
    minutes = int(callback.data.split(":")[2])
    await repo.set_interval_minutes(callback.from_user.id, minutes)
    await repo.log_audit(
        "set_schedule", actor_id=callback.from_user.id,
        details={"mode": "interval", "minutes": minutes},
    )
    await callback.answer("Saqlandi ✅")
    await _show_schedule(callback.message, callback.from_user.id, edit_cb=callback)


@user_router.callback_query(F.data == "sc:wkndint")
async def cb_sc_wkndint(callback: CallbackQuery) -> None:
    await _safe_edit(
        callback,
        "🛋 <b>Dam olish kunlari oralig'i</b> (shanba/yakshanba):",
        kb.interval_keyboard(prefix="time:wmin", back="sc:back"),
    )
    await callback.answer()


@user_router.callback_query(F.data.startswith("time:wmin:"))
async def cb_set_weekend_interval(callback: CallbackQuery) -> None:
    minutes = int(callback.data.split(":")[2])
    await repo.set_weekend_schedule(
        callback.from_user.id, enabled=True, mode="interval", interval_minutes=minutes
    )
    await callback.answer("Saqlandi ✅")
    await _show_schedule(callback.message, callback.from_user.id, edit_cb=callback)


@user_router.callback_query(F.data == "sc:daily")
async def cb_sc_daily(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DailyTime.waiting_times)
    await _safe_edit(
        callback,
        "🕘 <b>Aniq vaqt rejimi</b>\n\n"
        "Har kuni qaysi soat(lar)da xulosa kerakligini yozing.\n"
        "Masalan: <code>09:00</code> yoki <code>09:00, 18:00, 22:30</code>\n\n"
        "(Toshkent vaqti)",
        kb.back_menu(),
    )
    await callback.answer()


def _parse_times(raw: str) -> list[str] | None:
    cleaned = (raw or "").replace(" ", "")
    times: list[str] = []
    for part in cleaned.split(","):
        if not part:
            continue
        if not _TIME_RE.match(part):
            return None
        hh, mm = part.split(":")
        times.append(f"{int(hh):02d}:{int(mm):02d}")
    return sorted(set(times)) if times else None


@user_router.message(StateFilter(DailyTime.waiting_times), F.text)
async def receive_daily_times(message: Message, state: FSMContext) -> None:
    times = _parse_times(message.text)
    if times is None:
        await message.answer(
            "❌ Noto'g'ri format. Vaqtni <code>HH:MM</code> ko'rinishida yozing (masalan 09:00).",
            parse_mode=ParseMode.HTML,
        )
        return
    await repo.set_daily_schedule(message.from_user.id, times)
    await repo.log_audit(
        "set_schedule", actor_id=message.from_user.id,
        details={"mode": "daily", "times": times},
    )
    await state.clear()
    await message.answer(
        f"✅ Tayyor! Har kuni soat <b>{', '.join(times)}</b> (Toshkent) xulosa olasiz.",
        parse_mode=ParseMode.HTML,
    )
    await _show_schedule(message, message.from_user.id)


@user_router.callback_query(F.data == "sc:smart")
async def cb_sc_smart(callback: CallbackQuery) -> None:
    schedule = await repo.get_schedule(callback.from_user.id)
    new_val = not (schedule and schedule["smart_mode"])
    await repo.set_smart_mode(callback.from_user.id, new_val)
    await callback.answer("🧠 Aqlli rejim " + ("yoqildi" if new_val else "o'chirildi"))
    await _show_schedule(callback.message, callback.from_user.id, edit_cb=callback)


@user_router.callback_query(F.data == "sc:breaking")
async def cb_sc_breaking(callback: CallbackQuery) -> None:
    schedule = await repo.get_schedule(callback.from_user.id)
    cur = schedule["breaking_enabled"] if schedule else True
    new_val = not cur
    await repo.set_breaking_enabled(callback.from_user.id, new_val)
    await callback.answer("⚡ Shoshilinch " + ("yoqildi" if new_val else "o'chirildi"))
    await _show_schedule(callback.message, callback.from_user.id, edit_cb=callback)


@user_router.callback_query(F.data == "sc:quiet")
async def cb_sc_quiet(callback: CallbackQuery) -> None:
    schedule = await repo.get_schedule(callback.from_user.id)
    cur = schedule["quiet_enabled"] if schedule else True
    new_val = not cur
    await repo.set_quiet(callback.from_user.id, new_val)
    await callback.answer("🌙 Jim soatlar " + ("yoqildi" if new_val else "o'chirildi"))
    await _show_schedule(callback.message, callback.from_user.id, edit_cb=callback)


@user_router.callback_query(F.data == "sc:quiettime")
async def cb_sc_quiettime(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(QuietTime.waiting_range)
    await _safe_edit(
        callback,
        "🕒 <b>Jim soatlar oralig'i</b>\n\n"
        "Formatda yozing: <code>23:00-07:00</code> (Toshkent vaqti).\n"
        "Shu oraliqda oddiy digestlar kechiktiriladi "
        "(shoshilinch xabarlar baribir keladi).",
        kb.back_menu(),
    )
    await callback.answer()


@user_router.message(StateFilter(QuietTime.waiting_range), F.text)
async def receive_quiet_range(message: Message, state: FSMContext) -> None:
    m = _QUIET_RE.match((message.text or "").replace(" ", ""))
    if not m:
        await message.answer(
            "❌ Noto'g'ri format. Masalan: <code>23:00-07:00</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    start = f"{int(m.group(1)):02d}:{m.group(2)}"
    end = f"{int(m.group(3)):02d}:{m.group(4)}"
    await repo.set_quiet(message.from_user.id, True, start, end)
    await state.clear()
    await message.answer(
        f"✅ Jim soatlar: <b>{start}–{end}</b> (Toshkent).",
        parse_mode=ParseMode.HTML,
    )
    await _show_schedule(message, message.from_user.id)


@user_router.callback_query(F.data == "sc:weekend")
async def cb_sc_weekend(callback: CallbackQuery) -> None:
    schedule = await repo.get_schedule(callback.from_user.id)
    cur = schedule["weekend_enabled"] if schedule else False
    new_val = not cur
    minutes = (schedule and schedule["weekend_interval_minutes"]) or 720
    await repo.set_weekend_schedule(
        callback.from_user.id, enabled=new_val, mode="interval", interval_minutes=minutes
    )
    await callback.answer("📅 Dam olish jadvali " + ("yoqildi" if new_val else "o'chirildi"))
    await _show_schedule(callback.message, callback.from_user.id, edit_cb=callback)


@user_router.callback_query(F.data == "sc:skipempty")
async def cb_sc_skipempty(callback: CallbackQuery) -> None:
    schedule = await repo.get_schedule(callback.from_user.id)
    cur = schedule["skip_empty"] if schedule else True
    new_val = not cur
    await repo.set_skip_empty(callback.from_user.id, new_val)
    await callback.answer(
        "Bo'sh digest " + ("yubormaydi" if new_val else "yuboradi")
    )
    await _show_schedule(callback.message, callback.from_user.id, edit_cb=callback)


@user_router.callback_query(F.data == "sc:off")
async def cb_sc_off(callback: CallbackQuery) -> None:
    await repo.set_schedule_active(callback.from_user.id, False)
    await callback.answer("⏸ To'xtatildi")
    await _show_schedule(callback.message, callback.from_user.id, edit_cb=callback)


@user_router.callback_query(F.data == "sc:on")
async def cb_sc_on(callback: CallbackQuery) -> None:
    await repo.set_schedule_active(callback.from_user.id, True)
    await callback.answer("▶️ Yoqildi")
    await _show_schedule(callback.message, callback.from_user.id, edit_cb=callback)


# ============================================================
#  Qiziqishlar
# ============================================================
async def _show_interests(callback: CallbackQuery) -> None:
    user = await repo.get_user(callback.from_user.id)
    selected = list(user["interests"]) if user and user["interests"] else []
    note = "Hammasi (filtrlanmaydi)" if not selected else ", ".join(selected)
    await _safe_edit(
        callback,
        "🎯 <b>Qiziqishlar</b>\n\n"
        "Faqat sizni qiziqtirgan kategoriyalarni tanlang. "
        "Hech narsa tanlanmasa — barcha yangiliklar keladi.\n\n"
        f"Joriy: <b>{note}</b>",
        kb.interests_keyboard(selected),
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


# ============================================================
#  Muhimlik rejimi
# ============================================================
async def _show_mode(callback: CallbackQuery) -> None:
    user = await repo.get_user(callback.from_user.id)
    current = (user["importance_min"] if user else 1) or 1
    await _safe_edit(
        callback,
        "🔎 <b>Yangilik rejimi</b>\n\n"
        "📋 Hammasi — barcha yangiliklar\n"
        "⭐ Muhimlari — faqat muhim (3+)\n"
        "🔥 Eng muhimlari — faqat eng muhim (4+)",
        kb.mode_keyboard(current),
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


# ============================================================
#  Digest tarixi
# ============================================================
@user_router.callback_query(F.data == "m:history")
async def cb_menu_history(callback: CallbackQuery) -> None:
    digests = await repo.get_user_digests(callback.from_user.id, limit=10)
    if not digests:
        await _safe_edit(callback, "📭 Hali digest tarixi yo'q (oxirgi 7 kun).", kb.back_menu())
    else:
        await _safe_edit(
            callback,
            "📚 <b>Digest tarixi</b> (oxirgi 7 kun)\nKo'rish uchun tanlang:",
            kb.history_keyboard(digests),
        )
    await callback.answer()


@user_router.callback_query(F.data.startswith("hist:"))
async def cb_show_history(callback: CallbackQuery) -> None:
    digest_id = int(callback.data.split(":")[1])
    row = await repo.get_digest(digest_id, callback.from_user.id)
    if not row or not row["content"]:
        await callback.answer("Topilmadi", show_alert=True)
        return
    await callback.answer()
    for part in digest_mod.split_for_telegram(row["content"]):
        await callback.message.answer(
            part, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )


# ============================================================
#  Onboarding (qadamli boshlang'ich sozlash)
# ============================================================
async def _onb_finish(message: Message, user_id: int) -> None:
    await repo.set_onboarded(user_id, True)
    await message.answer(
        "🎉 <b>Tayyor!</b> Sozlash yakunlandi.\n"
        "Xohlagan vaqtingiz 🏠 Menyu orqali o'zgartirasiz.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.MAIN_MENU,
    )
    await message.answer(
        MENU_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb.main_menu_inline()
    )


async def _onb_step2(callback_or_msg, user_id: int, cb: CallbackQuery | None) -> None:
    """2-qadam: qiziqishlar."""
    user = await repo.get_user(user_id)
    selected = list(user["interests"]) if user and user["interests"] else []
    text = (
        "🎯 <b>2/3 — Qiziqishlar</b>\n\n"
        "Sizni qiziqtirgan kategoriyalarni tanlang (ixtiyoriy). "
        "Hech narsa tanlamasangiz, barcha yangiliklar keladi."
    )
    markup = kb.interests_keyboard(selected, prefix="oint")
    if cb is not None:
        await _safe_edit(cb, text, markup)
    else:
        await callback_or_msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def _onb_step3(callback_or_msg, cb: CallbackQuery | None) -> None:
    """3-qadam: jadval oralig'i."""
    text = (
        "⏰ <b>3/3 — Qanchalik tez-tez?</b>\n\n"
        "Digest qanday oraliqda kelishini tanlang:"
    )
    markup = kb.onb_interval_keyboard()
    if cb is not None:
        await _safe_edit(cb, text, markup)
    else:
        await callback_or_msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


@user_router.callback_query(F.data == "onb:start")
async def cb_onb_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Onb.channel)
    await _safe_edit(
        callback,
        "📥 <b>1/3 — Kanal qo'shish</b>\n\n"
        "Kuzatmoqchi bo'lgan kanal linkini yuboring (masalan <code>@kanal</code>).\n"
        "Bir nechta bo'lsa — har birini alohida qatorga yozing.",
        kb.onb_step1_keyboard(),
    )
    await callback.answer()


@user_router.callback_query(F.data == "onb:skipall")
async def cb_onb_skipall(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await repo.set_onboarded(callback.from_user.id, True)
    await _safe_edit(callback, MENU_TEXT, kb.main_menu_inline())
    await callback.answer("Keyinroq sozlashingiz mumkin")


@user_router.callback_query(F.data == "onb:s1skip")
async def cb_onb_s1skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _onb_step2(callback.message, callback.from_user.id, cb=callback)
    await callback.answer()


@user_router.message(StateFilter(Onb.channel), F.text)
async def onb_receive_channel(message: Message, state: FSMContext) -> None:
    await _add_channels(message, message.text, state)
    await _onb_step2(message, message.from_user.id, cb=None)


@user_router.callback_query(F.data.startswith("oint:"))
async def cb_onb_interest(callback: CallbackQuery) -> None:
    value = callback.data.split(":", 1)[1]
    user = await repo.get_user(callback.from_user.id)
    selected = list(user["interests"]) if user and user["interests"] else []
    if value in selected:
        selected.remove(value)
    else:
        selected.append(value)
    await repo.set_interests(callback.from_user.id, selected)
    await _onb_step2(callback.message, callback.from_user.id, cb=callback)
    await callback.answer()


@user_router.callback_query(F.data == "onb:s2next")
async def cb_onb_s2next(callback: CallbackQuery) -> None:
    await _onb_step3(callback.message, cb=callback)
    await callback.answer()


@user_router.callback_query(F.data.startswith("onbint:"))
async def cb_onb_interval(callback: CallbackQuery, state: FSMContext) -> None:
    minutes = int(callback.data.split(":")[1])
    await repo.set_interval_minutes(callback.from_user.id, minutes)
    await state.clear()
    await callback.answer("Saqlandi ✅")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await _onb_finish(callback.message, callback.from_user.id)


# ============================================================
#  Fallback: linkka o'xshash matn yoki tushunilmagan xabar
# ============================================================
@user_router.message(F.text, StateFilter(None))
async def maybe_link(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    looks_like_link = text.startswith("@") or "t.me/" in text
    if looks_like_link and userbot_mod.parse_channel_link(text.splitlines()[0]):
        await _add_channels(message, text, state)
    else:
        await message.answer(
            "🤔 Tushunmadim. Kanal linkini yuboring yoki 🏠 Menyu tugmasini bosing.",
            reply_markup=kb.MAIN_MENU,
        )
