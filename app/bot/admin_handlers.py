"""
Admin paneli (aiogram).

Imkoniyatlar:
  1. /admin    — statistika / dashboard
  2. /users    — foydalanuvchilar ro'yxati, qidirish, profil, ban/unban, limit
  3. /audit    — audit jurnali
  4. /broadcast— barcha foydalanuvchilarga e'lon
  5. /channels — kuzatilayotgan kanallar
  6. /status   — tizim holati
  7. /settings — global sozlamalar

Faqat config.admin_ids ro'yxatidagi foydalanuvchilar uchun (IsAdmin filtri).
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import config
from app import runtime
from app import ai_analyzer
from app import userbot as userbot_mod
from app.db import repository as repo

logger = logging.getLogger(__name__)

admin_router = Router(name="admin")

_PAGE = 10


def esc(text) -> str:
    return html.escape(str(text)) if text is not None else "—"


# ============================================================
#  Admin filtri
# ============================================================
class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and config.is_admin(user.id))


admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())


# ============================================================
#  FSM
# ============================================================
class AdminFSM(StatesGroup):
    search_user = State()
    broadcast = State()
    set_limit = State()


# ============================================================
#  /admin — dashboard
# ============================================================
def _admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="adm:users:0"),
                InlineKeyboardButton(text="📡 Kanallar", callback_data="adm:channels:0"),
            ],
            [
                InlineKeyboardButton(text="📜 Audit", callback_data="adm:audit:0"),
                InlineKeyboardButton(text="🩺 Status", callback_data="adm:status"),
            ],
            [
                InlineKeyboardButton(text="📢 Broadcast", callback_data="adm:broadcast"),
                InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="adm:settings"),
            ],
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="adm:dashboard")],
        ]
    )


async def _dashboard_text() -> str:
    s = await repo.get_stats()
    top = "\n".join(
        f"   {i}. {esc(c['title'] or c['username'])} — {c['subs']} obuna"
        for i, c in enumerate(s["top_channels"], 1)
    ) or "   —"
    return (
        "👑 <b>Admin paneli — Statistika</b>\n"
        f"{'─' * 22}\n"
        f"👥 Foydalanuvchilar: <b>{s['total_users']}</b> "
        f"(bloklangan: {s['banned_users']})\n"
        f"📡 Faol kanallar: <b>{s['total_channels']}</b>\n"
        f"📨 Yig'ilgan postlar: <b>{s['total_posts']}</b>\n"
        f"📰 Yuborilgan digestlar: <b>{s['total_digests']}</b>\n\n"
        f"📈 <b>Yangi foydalanuvchilar:</b>\n"
        f"   • Bugun: {s['new_today']}\n"
        f"   • Hafta: {s['new_week']}\n"
        f"   • Oy: {s['new_month']}\n\n"
        f"🤖 <b>AI sarfi:</b>\n"
        f"   • Chaqiruvlar: {s['ai_calls']}\n"
        f"   • Tokenlar: {s['ai_tokens']}\n\n"
        f"🔝 <b>TOP kanallar:</b>\n{top}"
    )


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        await _dashboard_text(), parse_mode=ParseMode.HTML, reply_markup=_admin_menu()
    )


@admin_router.callback_query(F.data == "adm:dashboard")
async def cb_dashboard(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        await _dashboard_text(), parse_mode=ParseMode.HTML, reply_markup=_admin_menu()
    )
    await callback.answer("Yangilandi")


# ============================================================
#  Foydalanuvchilar
# ============================================================
def _users_kb(users, page: int) -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        flag = "⛔️" if u["is_banned"] else "👤"
        name = u["username"] or u["first_name"] or u["id"]
        rows.append(
            [InlineKeyboardButton(text=f"{flag} {name}", callback_data=f"adm:u:{u['id']}")]
        )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:users:{page-1}"))
    nav.append(InlineKeyboardButton(text="🔍 Qidirish", callback_data="adm:usearch"))
    if len(users) == _PAGE:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:users:{page+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm:dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@admin_router.callback_query(F.data.startswith("adm:users:"))
async def cb_users(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[2])
    users = await repo.list_users(limit=_PAGE, offset=page * _PAGE)
    text = f"👥 <b>Foydalanuvchilar</b> (sahifa {page + 1})"
    if not users and page == 0:
        text = "👥 Hali foydalanuvchi yo'q."
    await callback.message.edit_text(
        text, parse_mode=ParseMode.HTML, reply_markup=_users_kb(users, page)
    )
    await callback.answer()


@admin_router.callback_query(F.data == "adm:usearch")
async def cb_usearch(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFSM.search_user)
    await callback.message.answer("🔍 ID yoki username yuboring:")
    await callback.answer()


@admin_router.message(StateFilter(AdminFSM.search_user), F.text)
async def do_search(message: Message, state: FSMContext) -> None:
    await state.clear()
    users = await repo.search_users(message.text.strip())
    if not users:
        await message.answer("Topilmadi.")
        return
    if len(users) == 1:
        await message.answer(
            await _user_profile_text(users[0]["id"]),
            parse_mode=ParseMode.HTML,
            reply_markup=_user_profile_kb(users[0]),
        )
        return
    await message.answer(
        f"🔍 {len(users)} ta natija:",
        reply_markup=_users_kb(users[:_PAGE], 0),
    )


async def _user_profile_text(user_id: int) -> str:
    u = await repo.get_user(user_id)
    if not u:
        return "Foydalanuvchi topilmadi."
    channels = await repo.get_user_channels(user_id)
    schedule = await repo.get_schedule(user_id)
    digest_count = await repo.count_user_digests(user_id)
    limit = u["max_channels"] or config.max_channels_per_user

    if not schedule or not schedule["is_active"]:
        sched_str = "sozlanmagan"
    elif schedule["mode"] == "interval":
        sched_str = f"har {schedule['interval_hours']} soatda"
    else:
        sched_str = "har kuni " + ", ".join(schedule["daily_times"] or [])

    ch_list = "\n".join(
        f"   • {esc(c['title'] or c['username'])}" for c in channels
    ) or "   —"

    status = "⛔️ BLOKLANGAN" if u["is_banned"] else "✅ Faol"
    return (
        f"👤 <b>Foydalanuvchi profili</b>\n"
        f"{'─' * 22}\n"
        f"🆔 ID: <code>{u['id']}</code>\n"
        f"👤 Username: @{esc(u['username'])}\n"
        f"📛 Ism: {esc(u['first_name'])}\n"
        f"📊 Holat: {status}\n"
        f"📅 Ro'yxatdan o'tgan: {u['created_at']:%d.%m.%Y %H:%M}\n"
        f"🕐 Oxirgi faollik: {u['last_active_at']:%d.%m.%Y %H:%M}\n"
        f"⏰ Digest: {sched_str}\n"
        f"📰 Qabul qilgan digestlar: {digest_count}\n"
        f"📡 Kanal limiti: {limit}\n"
        f"📋 Kanallari ({len(channels)}):\n{ch_list}"
    )


def _user_profile_kb(u) -> InlineKeyboardMarkup:
    uid = u["id"]
    if u["is_banned"]:
        ban_btn = InlineKeyboardButton(text="✅ Blokdan chiqarish", callback_data=f"adm:unban:{uid}")
    else:
        ban_btn = InlineKeyboardButton(text="⛔️ Bloklash", callback_data=f"adm:ban:{uid}")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ban_btn, InlineKeyboardButton(text="📊 Limit", callback_data=f"adm:limit:{uid}")],
            [InlineKeyboardButton(text="⬅️ Ro'yxat", callback_data="adm:users:0")],
        ]
    )


@admin_router.callback_query(F.data.startswith("adm:u:"))
async def cb_user_profile(callback: CallbackQuery) -> None:
    user_id = int(callback.data.split(":")[2])
    u = await repo.get_user(user_id)
    await callback.message.edit_text(
        await _user_profile_text(user_id),
        parse_mode=ParseMode.HTML,
        reply_markup=_user_profile_kb(u) if u else None,
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("adm:ban:"))
async def cb_ban(callback: CallbackQuery) -> None:
    user_id = int(callback.data.split(":")[2])
    await repo.set_ban(user_id, True, callback.from_user.id)
    await repo.log_audit("ban", actor_id=callback.from_user.id, target_user_id=user_id)
    u = await repo.get_user(user_id)
    await callback.message.edit_text(
        await _user_profile_text(user_id),
        parse_mode=ParseMode.HTML,
        reply_markup=_user_profile_kb(u),
    )
    await callback.answer("Bloklandi ⛔️")


@admin_router.callback_query(F.data.startswith("adm:unban:"))
async def cb_unban(callback: CallbackQuery) -> None:
    user_id = int(callback.data.split(":")[2])
    await repo.set_ban(user_id, False, callback.from_user.id)
    await repo.log_audit("unban", actor_id=callback.from_user.id, target_user_id=user_id)
    u = await repo.get_user(user_id)
    await callback.message.edit_text(
        await _user_profile_text(user_id),
        parse_mode=ParseMode.HTML,
        reply_markup=_user_profile_kb(u),
    )
    await callback.answer("Blokdan chiqarildi ✅")


@admin_router.callback_query(F.data.startswith("adm:limit:"))
async def cb_limit(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":")[2])
    await state.set_state(AdminFSM.set_limit)
    await state.update_data(target=user_id)
    await callback.message.answer(
        f"📊 <code>{user_id}</code> uchun yangi kanal limitini yuboring (raqam):",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@admin_router.message(StateFilter(AdminFSM.set_limit), F.text)
async def do_set_limit(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    target = data.get("target")
    if not message.text.strip().isdigit():
        await message.answer("❌ Raqam kiriting.")
        return
    limit = int(message.text.strip())
    await repo.set_max_channels(target, limit)
    await repo.log_audit(
        "set_limit", actor_id=message.from_user.id, target_user_id=target,
        details={"limit": limit},
    )
    await message.answer(f"✅ <code>{target}</code> limiti {limit} ga o'rnatildi.",
                         parse_mode=ParseMode.HTML)


# ============================================================
#  Audit
# ============================================================
@admin_router.callback_query(F.data.startswith("adm:audit:"))
async def cb_audit(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[2])
    logs = await repo.get_audit_logs(limit=_PAGE, offset=page * _PAGE)
    lines = []
    for lg in logs:
        when = lg["created_at"].strftime("%d.%m %H:%M")
        details = lg["details"] or ""
        lines.append(
            f"<code>{when}</code> | <b>{esc(lg['action'])}</b> | "
            f"actor:{lg['actor_id']} {esc(details)[:50]}"
        )
    text = "📜 <b>Audit jurnali</b>\n" + ("\n".join(lines) or "Bo'sh")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:audit:{page-1}"))
    if len(logs) == _PAGE:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:audit:{page+1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm:dashboard")])
    await callback.message.edit_text(
        text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await callback.answer()


# ============================================================
#  Kanallar
# ============================================================
@admin_router.callback_query(F.data.startswith("adm:channels:"))
async def cb_channels(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[2])
    channels = await repo.list_channels_with_counts(limit=_PAGE, offset=page * _PAGE)
    lines = [
        f"• {esc(c['title'] or c['username'])} "
        f"(@{esc(c['username'])}) — <b>{c['subs']}</b> obuna"
        for c in channels
    ]
    text = f"📡 <b>Kanallar</b> (sahifa {page + 1})\n" + ("\n".join(lines) or "Bo'sh")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:channels:{page-1}"))
    if len(channels) == _PAGE:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:channels:{page+1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm:dashboard")])
    await callback.message.edit_text(
        text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await callback.answer()


# ============================================================
#  Status
# ============================================================
@admin_router.callback_query(F.data == "adm:status")
async def cb_status(callback: CallbackQuery) -> None:
    await callback.answer("Tekshirilmoqda...")
    ub_ok = userbot_mod.userbot is not None and userbot_mod.userbot.is_connected()
    sched = runtime.scheduler_ref
    sched_ok = bool(sched and sched.scheduler.running)
    ai_ok = ai_analyzer.analyzer is not None and await ai_analyzer.analyzer.ping()

    # DB tekshirish
    try:
        await repo.get_stats()
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False

    uptime = datetime.now(timezone.utc) - runtime.started_at
    hours, rem = divmod(int(uptime.total_seconds()), 3600)
    minutes = rem // 60

    def mark(ok: bool) -> str:
        return "🟢 ishlayapti" if ok else "🔴 muammo"

    text = (
        "🩺 <b>Tizim holati</b>\n"
        f"{'─' * 22}\n"
        f"🤖 Bot: 🟢 ishlayapti\n"
        f"👤 Userbot: {mark(ub_ok)}\n"
        f"⏰ Scheduler: {mark(sched_ok)}\n"
        f"🗄 Baza (Supabase): {mark(db_ok)}\n"
        f"🧠 AI ({config.ai_provider}/{config.model_name}): {mark(ai_ok)}\n\n"
        f"⏱ Uptime: {hours} soat {minutes} daqiqa"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Yangilash", callback_data="adm:status")],
                [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm:dashboard")],
            ]
        ),
    )


# ============================================================
#  Sozlamalar
# ============================================================
@admin_router.callback_query(F.data == "adm:settings")
async def cb_settings(callback: CallbackQuery) -> None:
    text = (
        "⚙️ <b>Global sozlamalar</b>\n"
        f"{'─' * 22}\n"
        f"🧠 AI provayder: <b>{config.ai_provider}</b>\n"
        f"🤖 Model: <code>{config.model_name}</code>\n"
        f"🌐 Tahlil tili: {config.analysis_language}\n"
        f"🕐 Vaqt mintaqasi: {config.timezone}\n"
        f"📡 Max kanal/foydalanuvchi: {config.max_channels_per_user}\n"
        f"📦 Max post/chunk: {config.max_posts_per_chunk}\n"
        f"👑 Adminlar: {len(config.admin_ids)} ta\n\n"
        "<i>Bu qiymatlar .env / Railway Variables orqali o'zgartiriladi.</i>"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm:dashboard")]]
        ),
    )
    await callback.answer()


# ============================================================
#  Broadcast
# ============================================================
@admin_router.callback_query(F.data == "adm:broadcast")
async def cb_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFSM.broadcast)
    await callback.message.answer(
        "📢 Barcha faol foydalanuvchilarga yuboriladigan xabarni yozing.\n"
        "(Bekor qilish: /cancel)"
    )
    await callback.answer()


@admin_router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminFSM.broadcast)
    await message.answer("📢 Yubormoqchi bo'lgan xabaringizni yozing (/cancel — bekor):")


@admin_router.message(StateFilter(AdminFSM.broadcast), Command("cancel"))
async def cancel_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Bekor qilindi.")


@admin_router.message(StateFilter(AdminFSM.broadcast), F.text)
async def do_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    text = message.text
    user_ids = await repo.get_all_user_ids(only_active=True)
    await message.answer(f"📤 {len(user_ids)} ta foydalanuvchiga yuborilmoqda...")

    delivered = failed = 0
    for uid in user_ids:
        try:
            await message.bot.send_message(uid, text)
            delivered += 1
        except Exception:  # noqa: BLE001
            failed += 1
        await asyncio.sleep(0.05)  # flood limitdan saqlanish

    await repo.log_broadcast(message.from_user.id, text, len(user_ids), delivered, failed)
    await repo.log_audit(
        "broadcast", actor_id=message.from_user.id,
        details={"total": len(user_ids), "delivered": delivered, "failed": failed},
    )
    await message.answer(
        f"✅ Yuborildi!\n📬 Yetkazildi: {delivered}\n❌ Xato: {failed}"
    )
