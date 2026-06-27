"""
AI tahlil qatlami.

OpenAI-compatible API orqali ishlaydi, shuning uchun bitta kod bilan
Groq, OpenAI va Gemini provayderlariga ulanish mumkin (config.AI_PROVIDER).

Asosiy vazifa: berilgan postlar to'plamini MAVZULARGA guruhlab,
har bir mavzu mazmunini va manba kanalini ko'rsatib beradi.
"""
from __future__ import annotations

import logging
from typing import Optional

from openai import AsyncOpenAI

from config import config
from app.db import repository as repo

logger = logging.getLogger(__name__)

_LANG_NAMES = {
    "uz": "o'zbek tilida",
    "ru": "rus tilida (на русском языке)",
    "en": "in English",
}


class AIAnalyzer:
    """OpenAI-compatible mijoz orqali postlarni tahlil qiladi."""

    def __init__(self) -> None:
        kwargs: dict = {"api_key": config.ai_api_key}
        if config.ai_base_url:
            kwargs["base_url"] = config.ai_base_url
        self.client = AsyncOpenAI(**kwargs)
        self.model = config.model_name
        self.provider = config.ai_provider

    def _system_prompt(self) -> str:
        lang = _LANG_NAMES.get(config.analysis_language, "o'zbek tilida")
        return (
            "Sen Telegram kanal postlarini tahlil qiluvchi yordamchisan. "
            f"Javobingni {lang} yoz.\n\n"
            "Senga bir nechta kanaldan to'plangan postlar beriladi. Vazifang:\n"
            "1. Postlarni MAVZULAR (mavzu/voqea) bo'yicha guruhlab chiq.\n"
            "2. Bir xil voqea haqidagi turli kanal postlarini BITTA mavzuga birlashtir.\n"
            "3. Har bir mavzu uchun qisqa, aniq mazmunini (2-4 gap) yoz.\n"
            "4. Har bir mavzu oxirida manba kanal(lar)ni ko'rsat.\n"
            "5. Reklama, takroriy yoki ahamiyatsiz postlarni tashlab yubor.\n\n"
            "Formatlash (Telegram HTML):\n"
            "• Har mavzuni <b>qalin sarlavha</b> bilan boshla.\n"
            "• Mazmunni oddiy matn bilan yoz.\n"
            "• Manbani kursivda: <i>Manba: @kanal</i>\n"
            "• Mavzular orasiga bo'sh qator qoldir.\n"
            "Ortiqcha kirish so'zlari yozma, to'g'ridan-to'g'ri mavzulardan boshla."
        )

    async def analyze(
        self, posts_block: str, user_id: Optional[int] = None
    ) -> Optional[str]:
        """
        Tayyorlangan postlar matnini AI ga yuboradi va guruhlangan
        tahlilni qaytaradi. Xatolikda None qaytaradi.
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": posts_block},
                ],
                temperature=0.3,
                max_tokens=2000,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("AI tahlilida xatolik: %s", exc)
            await repo.log_audit(
                "error", actor_id=user_id, details={"where": "ai_analyze", "error": str(exc)}
            )
            return None

        # Token sarfini kuzatish
        try:
            usage = response.usage
            if usage:
                await repo.log_ai_usage(
                    user_id,
                    self.provider,
                    self.model,
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                )
        except Exception:  # noqa: BLE001
            pass

        if not response.choices:
            return None
        content = response.choices[0].message.content
        return content.strip() if content else None

    async def ping(self) -> bool:
        """AI ulanishini tekshiradi (admin /status uchun)."""
        try:
            await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("AI ping muvaffaqiyatsiz: %s", exc)
            return False


# Global yagona obyekt (main.py da yaratiladi)
analyzer: Optional[AIAnalyzer] = None


def init_analyzer() -> AIAnalyzer:
    global analyzer
    analyzer = AIAnalyzer()
    return analyzer
