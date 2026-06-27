"""Inline va reply klaviaturalar."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Asosiy menyu (reply tugmalar)
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Kanal qo'shish"), KeyboardButton(text="📋 Mening kanallarim")],
        [KeyboardButton(text="⏰ Vaqt sozlash"), KeyboardButton(text="⚙️ Menyu")],
        [KeyboardButton(text="ℹ️ Yordam")],
    ],
    resize_keyboard=True,
)


def time_keyboard() -> InlineKeyboardMarkup:
    """Digest oralig'ini tanlash."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 soatda", callback_data="time:interval:1"),
                InlineKeyboardButton(text="3 soatda", callback_data="time:interval:3"),
                InlineKeyboardButton(text="6 soatda", callback_data="time:interval:6"),
            ],
            [
                InlineKeyboardButton(text="12 soatda", callback_data="time:interval:12"),
                InlineKeyboardButton(text="24 soatda", callback_data="time:interval:24"),
            ],
            [
                InlineKeyboardButton(
                    text="🕘 Aniq vaqt (har kuni)", callback_data="time:daily"
                ),
            ],
            [
                InlineKeyboardButton(text="⏸ To'xtatish", callback_data="time:off"),
            ],
        ]
    )


def channels_keyboard(channels) -> InlineKeyboardMarkup:
    """Kanallar ro'yxati + har biriga o'chirish tugmasi."""
    rows = []
    for ch in channels:
        label = f"❌ {ch['title'] or ch['username'] or ch['tg_channel_id']}"
        rows.append(
            [InlineKeyboardButton(text=label[:60], callback_data=f"rm:{ch['id']}")]
        )
    if not rows:
        rows.append(
            [InlineKeyboardButton(text="Kanal yo'q", callback_data="noop")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)



# ============================================================
#  FAZA 2 — Inline menyu, qiziqishlar, rejim, tarix
# ============================================================
from config import CATEGORIES  # noqa: E402

_IMPORTANCE_MODES = {
    1: "📋 Hammasi",
    3: "⭐ Muhimlari",
    4: "🔥 Eng muhimlari",
}


def main_menu_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="m:add"),
                InlineKeyboardButton(text="📋 Kanallar", callback_data="m:channels"),
            ],
            [
                InlineKeyboardButton(text="⏰ Jadval", callback_data="m:time"),
                InlineKeyboardButton(text="🎯 Qiziqishlar", callback_data="m:interests"),
            ],
            [
                InlineKeyboardButton(text="🔎 Rejim", callback_data="m:mode"),
                InlineKeyboardButton(text="📚 Tarix", callback_data="m:history"),
            ],
            [InlineKeyboardButton(text="ℹ️ Yordam", callback_data="m:help")],
        ]
    )


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Menyu", callback_data="m:menu")]]
    )


def interests_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    """Kategoriyalar — tanlanганlarida ✅."""
    sel = set(selected or [])
    rows = []
    row = []
    for i, cat in enumerate(CATEGORIES, 1):
        mark = "✅ " if cat in sel else ""
        row.append(InlineKeyboardButton(text=f"{mark}{cat}", callback_data=f"int:{cat}"))
        if i % 2 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🗑 Tozalash (hammasi)", callback_data="int:clear")])
    rows.append([InlineKeyboardButton(text="⬅️ Menyu", callback_data="m:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mode_keyboard(current_min: int) -> InlineKeyboardMarkup:
    rows = []
    for value, label in _IMPORTANCE_MODES.items():
        mark = "🔘 " if value == current_min else "⚪️ "
        rows.append(
            [InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"mode:{value}")]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Menyu", callback_data="m:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_keyboard(digests) -> InlineKeyboardMarkup:
    rows = []
    for d in digests:
        when = d["sent_at"].strftime("%d.%m %H:%M")
        label = f"📰 {when} · {d['post_count']} ta"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"hist:{d['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Menyu", callback_data="m:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
