"""
AI tahlil qatlami (Faza 1 — multi-provider + strukturali tahlil).

OpenAI-compatible API orqali ishlaydi. Bir nechta provayder (Groq → Gemini →
OpenAI) ketma-ket sinab ko'riladi: biri ishlamasa, avtomatik keyingisiga o'tadi
(config.ai_providers() tartibida).

Asosiy vazifa — `analyze_story`: bitta yangilik matnini tahlil qilib,
qisqa mazmun, kategoriya, muhimlik bali va sentimentni JSON ko'rinishida qaytaradi.
Bu Bosqich A (umumiy cache) uchun ishlatiladi — har yangilik uchun FAQAT bir marta.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from openai import AsyncOpenAI

from config import CATEGORIES, config
from app.db import repository as repo

logger = logging.getLogger(__name__)

_LANG_NAMES = {
    "uz": "o'zbek tilida",
    "ru": "rus tilida (на русском языке)",
    "en": "in English",
}

_VALID_SENTIMENT = {"positive", "negative", "neutral"}
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Optional[dict]:
    """Model javobidan JSON obyektini ajratib oladi (code-fence va h.k.dan)."""
    if not text:
        return None
    match = _JSON_RE.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


class AIAnalyzer:
    """Bir nechta OpenAI-compatible provayder bilan ishlaydi (fallback bilan)."""

    def __init__(self) -> None:
        self.providers: list[dict] = []
        for p in config.ai_providers():
            kwargs: dict = {"api_key": p["api_key"]}
            if p["base_url"]:
                kwargs["base_url"] = p["base_url"]
            self.providers.append(
                {
                    "name": p["name"],
                    "model": p["model"],
                    "client": AsyncOpenAI(**kwargs),
                }
            )
        if not self.providers:
            logger.error("Hech qanday AI provayder sozlanmagan!")

    @property
    def primary_name(self) -> str:
        return self.providers[0]["name"] if self.providers else "—"

    @property
    def primary_model(self) -> str:
        return self.providers[0]["model"] if self.providers else "—"

    async def _chat(self, messages: list[dict], user_id: Optional[int] = None, **kwargs):
        """
        Provayderlarni navbat bilan sinaydi. Birinchi muvaffaqiyatli javobni
        qaytaradi: (provider_name, model, response). Hammasi ishlamasa — None.
        """
        last_error: Optional[Exception] = None
        for prov in self.providers:
            try:
                response = await prov["client"].chat.completions.create(
                    model=prov["model"], messages=messages, **kwargs
                )
                # Token sarfini kuzatish
                await self._log_usage(prov, response, user_id)
                return prov["name"], prov["model"], response
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "AI provayder '%s' ishlamadi, keyingisiga o'tilmoqda: %s",
                    prov["name"], exc,
                )
                continue
        if last_error:
            logger.error("Barcha AI provayderlar ishlamadi: %s", last_error)
            await repo.log_audit(
                "error", actor_id=user_id,
                details={"where": "ai_chat", "error": str(last_error)},
            )
        return None

    @staticmethod
    async def _log_usage(prov: dict, response, user_id: Optional[int]) -> None:
        try:
            usage = getattr(response, "usage", None)
            if usage:
                await repo.log_ai_usage(
                    user_id,
                    prov["name"],
                    prov["model"],
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                )
        except Exception:  # noqa: BLE001
            pass

    def _story_system_prompt(self) -> str:
        lang = _LANG_NAMES.get(config.analysis_language, "o'zbek tilida")
        cats = ", ".join(CATEGORIES)
        return (
            "Sen yangiliklar tahlilchisisan. Senga bitta yangilik (Telegram post) "
            "matni beriladi. Uni tahlil qilib, FAQAT quyidagi JSON ko'rinishida "
            "javob qaytar (boshqa hech narsa yozma):\n"
            "{\n"
            '  "summary": "...",\n'
            '  "category": "...",\n'
            '  "importance": 3,\n'
            '  "sentiment": "neutral"\n'
            "}\n\n"
            f"• summary — yangilik mazmuni {lang}, 1-3 qisqa gap. Reklama bo'lsa bo'sh qoldir.\n"
            f"• category — FAQAT shulardan biri: {cats}\n"
            "• importance — 1 dan 5 gacha butun son (5 = juda muhim/favqulodda, "
            "1 = oddiy/ahamiyatsiz).\n"
            "• sentiment — positive, negative yoki neutral.\n"
        )

    async def analyze_story(
        self, text: str, user_id: Optional[int] = None
    ) -> Optional[dict]:
        """
        Bitta yangilik matnini tahlil qiladi.
        Qaytaradi: {summary, category, importance, sentiment} yoki None.
        """
        if not self.providers:
            return None
        result = await self._chat(
            messages=[
                {"role": "system", "content": self._story_system_prompt()},
                {"role": "user", "content": text[:4000]},
            ],
            user_id=user_id,
            temperature=0.2,
            max_tokens=400,
        )
        if result is None:
            return None
        _, _, response = result
        if not response.choices:
            return None

        data = _extract_json(response.choices[0].message.content or "")
        if not data:
            return None  # AI/parse xatosi -> keyinroq qayta urinish

        # Validatsiya / normalizatsiya
        summary = str(data.get("summary", "")).strip()
        if not summary:
            return {"skip": True}  # reklama/ahamiyatsiz -> story yaratilmaydi
        category = str(data.get("category", "Boshqa")).strip()
        if category not in CATEGORIES:
            category = "Boshqa"
        try:
            importance = int(data.get("importance", 3))
        except (TypeError, ValueError):
            importance = 3
        importance = max(1, min(5, importance))
        sentiment = str(data.get("sentiment", "neutral")).strip().lower()
        if sentiment not in _VALID_SENTIMENT:
            sentiment = "neutral"

        return {
            "summary": summary,
            "category": category,
            "importance": importance,
            "sentiment": sentiment,
        }

    async def ping(self) -> bool:
        """AI ulanishini tekshiradi (admin /status uchun)."""
        result = await self._chat(
            messages=[{"role": "user", "content": "ping"}], max_tokens=5
        )
        return result is not None


# Global yagona obyekt (main.py da yaratiladi)
analyzer: Optional[AIAnalyzer] = None


def init_analyzer() -> AIAnalyzer:
    global analyzer
    analyzer = AIAnalyzer()
    return analyzer
