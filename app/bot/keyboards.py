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
        [KeyboardButton(text="⏰ Vaqt sozlash"), KeyboardButton(text="ℹ️ Yordam")],
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
