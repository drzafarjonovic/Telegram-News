"""
Ishga tushirish vaqtidagi global havolalar (admin /status uchun).

main.py bu qiymatlarni to'ldiradi, admin handlerlari o'qiydi.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

started_at: datetime = datetime.now(timezone.utc)
scheduler_ref: Optional[Any] = None
