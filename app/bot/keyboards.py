"""Inline va reply klaviaturalar (v3.0 — soddalashtirilgan, qulay interfeys)."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from config import CATEGORIES

# Doimiy pastki tugma — bitta 🏠 Menyu (hammasi inline menyu ichida)
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🏠 Menyu")]],
    resize_keyboard=True,
    is_persistent=True,
)

_IMPORTANCE_MODES = {
    1: "📋 Hammasi",
    3: "⭐ Muhimlari",
    4: "🔥 Eng muhimlari",
}

# Interval variantlari (daqiqada)
_INTERVALS = [
    ("30 daqiqa", 30), ("45 daqiqa", 45),
    ("1 soat", 60), ("2 soat", 120), ("3 soat", 180),
    ("6 soat", 360), ("8 soat", 480), ("12 soat", 720),
    ("24 soat", 1440),
]


def _onoff(v: bool) -> str:
    return "✅" if v else "❌"


# ============================================================
#  Asosiy hub menyusi
# ============================================================
def main_menu_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="m:add"),
                InlineKeyboardButton(text="📋 Kanallarim", callback_data="m:channels"),
            ],
            [
                InlineKeyboardButton(text="⏰ Jadval", callback_data="m:time"),
                InlineKeyboardButton(text="📬 Hozir yuborish", callback_data="m:now"),
            ],
            [
                InlineKeyboardButton(text="🎯 Qiziqishlar", callback_data="m:interests"),
                InlineKeyboardButton(text="🔎 Rejim", callback_data="m:mode"),
            ],
            [
                InlineKeyboardButton(text="📚 Tarix", callback_data="m:history"),
                InlineKeyboardButton(text="ℹ️ Yordam", callback_data="m:help"),
            ],
        ]
    )


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Menyu", callback_data="m:menu")]]
    )


# ============================================================
#  Kanallar — ro'yxat + kartochka + xavfsiz o'chirish
# ============================================================
def channels_keyboard(channels) -> InlineKeyboardMarkup:
    """Kanallar ro'yxati — har biri kartochkasini ochadi (o'chirmaydi)."""
    rows = []
    for ch in channels:
        label = ch["title"] or ch["username"] or str(ch["tg_channel_id"])
        rows.append(
            [InlineKeyboardButton(text=f"📰 {label}"[:60], callback_data=f"ch:{ch['id']}")]
        )
    rows.append([InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="m:add")])
    rows.append([InlineKeyboardButton(text="⬅️ Menyu", callback_data="m:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def channel_card_keyboard(channel_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"rmask:{channel_id}")],
            [InlineKeyboardButton(text="⬅️ Kanallar", callback_data="m:channels")],
        ]
    )


def confirm_remove_keyboard(channel_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, o'chirilsin", callback_data=f"rm:{channel_id}"),
                InlineKeyboardButton(text="❌ Yo'q", callback_data=f"ch:{channel_id}"),
            ],
        ]
    )


# ============================================================
#  Jadval menyusi (interval / aniq vaqt / aqlli / jim / dam olish / breaking)
# ============================================================
def schedule_menu_keyboard(schedule) -> InlineKeyboardMarkup:
    def g(key, default):
        try:
            v = schedule[key]
            return default if v is None else v
        except Exception:  # noqa: BLE001
            return default

    active = bool(g("is_active", False)) if schedule else False
    smart = bool(g("smart_mode", False))
    weekend = bool(g("weekend_enabled", False))
    breaking = bool(g("breaking_enabled", True))
    quiet = bool(g("quiet_enabled", True))
    skip_empty = bool(g("skip_empty", True))

    rows = [
        [
            InlineKeyboardButton(text="⏱ Oraliq", callback_data="sc:interval"),
            InlineKeyboardButton(text="🕘 Aniq vaqt", callback_data="sc:daily"),
        ],
        [InlineKeyboardButton(text=f"🧠 Aqlli rejim: {_onoff(smart)}", callback_data="sc:smart")],
        [InlineKeyboardButton(text=f"⚡ Shoshilinch xabar: {_onoff(breaking)}", callback_data="sc:breaking")],
        [InlineKeyboardButton(text=f"🌙 Jim soatlar: {_onoff(quiet)}", callback_data="sc:quiet")],
        [InlineKeyboardButton(text="🕒 Jim soat oralig'ini o'zgartirish", callback_data="sc:quiettime")],
        [InlineKeyboardButton(text=f"📅 Dam olish jadvali: {_onoff(weekend)}", callback_data="sc:weekend")],
    ]
    if weekend:
        rows.append(
            [InlineKeyboardButton(text="🛋 Dam olish oralig'i", callback_data="sc:wkndint")]
        )
    rows.append(
        [InlineKeyboardButton(
            text=f"🚫 Bo'sh digest: {'yubormaydi' if skip_empty else 'yuboradi'}",
            callback_data="sc:skipempty",
        )]
    )
    if active:
        rows.append([InlineKeyboardButton(text="⏸ To'xtatish", callback_data="sc:off")])
    else:
        rows.append([InlineKeyboardButton(text="▶️ Yoqish", callback_data="sc:on")])
    rows.append([InlineKeyboardButton(text="⬅️ Menyu", callback_data="m:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def interval_keyboard(prefix: str = "time:min", back: str = "sc:back") -> InlineKeyboardMarkup:
    """Oraliq tanlash. prefix: 'time:min' (ish kuni) yoki 'time:wmin' (dam olish)."""
    rows, row = [], []
    for i, (label, minutes) in enumerate(_INTERVALS, 1):
        row.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{minutes}"))
        if i % 3 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
#  Qiziqishlar / rejim / tarix
# ============================================================
def interests_keyboard(selected: list[str], back: str = "m:menu", prefix: str = "int") -> InlineKeyboardMarkup:
    sel = set(selected or [])
    rows, row = [], []
    for i, cat in enumerate(CATEGORIES, 1):
        mark = "✅ " if cat in sel else ""
        row.append(InlineKeyboardButton(text=f"{mark}{cat}", callback_data=f"{prefix}:{cat}"))
        if i % 2 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if prefix == "int":
        rows.append([InlineKeyboardButton(text="🗑 Tozalash (hammasi)", callback_data="int:clear")])
        rows.append([InlineKeyboardButton(text="⬅️ Menyu", callback_data=back)])
    else:
        rows.append([InlineKeyboardButton(text="▶️ Davom etish", callback_data="onb:s2next")])
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


# ============================================================
#  Onboarding (qadamli boshlang'ich sozlash)
# ============================================================
def onb_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Sozlashni boshlash", callback_data="onb:start")],
            [InlineKeyboardButton(text="⏭ Keyinroq", callback_data="onb:skipall")],
        ]
    )


def onb_step1_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="onb:s1skip")],
        ]
    )


def onb_interval_keyboard() -> InlineKeyboardMarkup:
    picks = [("1 soat", 60), ("3 soat", 180), ("6 soat", 360), ("12 soat", 720), ("24 soat", 1440)]
    rows, row = [], []
    for i, (label, minutes) in enumerate(picks, 1):
        row.append(InlineKeyboardButton(text=label, callback_data=f"onbint:{minutes}"))
        if i % 3 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✅ Standart (6 soat) va yakunlash", callback_data="onbint:360")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
