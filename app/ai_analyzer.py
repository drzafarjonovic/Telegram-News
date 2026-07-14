"""
AI tahlil qatlami (v3.0 — ko'p kalitli round-robin pool + cooldown).

OpenAI-compatible API orqali ishlaydi. Endi har provayder uchun BIR NECHTA
API kalit qo'llab-quvvatlanadi (masalan GROQ_API_KEY=k1,k2,k3). Kalitlar
`config.ai_key_pool()` tartibida bitta umumiy poolga yig'iladi:

  • mixed rejimi  — Groq va Gemini kalitlari NAVBAT bilan aylanadi (yuk teng).
  • priority rejimi — avval asosiy provayder, keyin fallbacklar.

Har so'rov navbatdagi kalitga yuboriladi (round-robin). Biror kalit rate-limit
(429 / quota) qaytarsa, u vaqtincha "dam"ga qo'yiladi (Retry-After yoki
config.ai_cooldown_sec) va so'rov darhol keyingi kalitga o'tadi. Barcha kalit
band bo'lsa — dam olayotganlari ham oxirgi chora sifatida sinab ko'riladi.

Asosiy vazifa — `analyze_story`: bitta yangilik matnini tahlil qilib,
qisqa mazmun, kategoriya, muhimlik bali va sentimentni JSON ko'rinishida qaytaradi.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

from openai import AsyncOpenAI

from config import CATEGORIES, config
from app.db import repository as repo

logger = logging.getLogger(__name__)

# Rate-limit xatosini aniqlash uchun (SDK versiyasiga bog'liq emas)
try:
    from openai import RateLimitError as _RateLimitError
except Exception:  # noqa: BLE001
    _RateLimitError = None  # type: ignore

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


def _is_rate_limit(exc: Exception) -> bool:
    """Xato rate-limit / quota tugashi bilan bog'liqmi?"""
    if _RateLimitError is not None and isinstance(exc, _RateLimitError):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == 429:
        return True
    msg = str(exc).lower()
    return any(
        s in msg
        for s in ("rate limit", "429", "quota", "resource_exhausted", "too many requests")
    )


def _retry_after(exc: Exception, default: int) -> float:
    """Server bergan Retry-After (soniya) yoki standart cooldown."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            ra = resp.headers.get("retry-after")
            if ra:
                return max(1.0, min(300.0, float(ra)))
        except Exception:  # noqa: BLE001
            pass
    return float(default)


class AIAnalyzer:
    """Ko'p kalitli round-robin pool bilan ishlaydi (cooldown + fallback)."""

    def __init__(self) -> None:
        self.pool: list[dict] = []
        for p in config.ai_key_pool():
            kwargs: dict = {"api_key": p["api_key"]}
            if p["base_url"]:
                kwargs["base_url"] = p["base_url"]
            key = p["api_key"] or ""
            self.pool.append(
                {
                    "name": p["name"],
                    "model": p["model"],
                    "client": AsyncOpenAI(**kwargs),
                    "key_tail": key[-4:] if len(key) >= 4 else "****",
                    "requests": 0,
                    "rate_limits": 0,
                }
            )
        self._rr = 0  # round-robin ko'rsatkichi
        self._cooldown_until: dict[int, float] = {}
        self._cooldown_sec = max(5, config.ai_cooldown_sec)
        if not self.pool:
            logger.error("Hech qanday AI kaliti sozlanmagan!")
        else:
            names = ", ".join(
                f"{n}×{c}"
                for n, c in self._provider_counts().items()
            )
            logger.info(
                "AI pool tayyor: %d kalit (%s), rejim=%s.",
                len(self.pool), names, config.ai_pool_mode,
            )

    def _provider_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.pool:
            counts[p["name"]] = counts.get(p["name"], 0) + 1
        return counts

    @property
    def primary_name(self) -> str:
        return self.pool[0]["name"] if self.pool else "—"

    @property
    def primary_model(self) -> str:
        return self.pool[0]["model"] if self.pool else "—"

    def pool_status(self) -> str:
        """Admin /status uchun qisqa hisobot."""
        if not self.pool:
            return "AI pool bo'sh."
        now = time.monotonic()
        lines = []
        for i, p in enumerate(self.pool):
            cooling = self._cooldown_until.get(i, 0) > now
            state = "😴 dam" if cooling else "🟢"
            lines.append(
                f"{state} {p['name']} …{p['key_tail']} — "
                f"{p['requests']} so'rov, {p['rate_limits']} limit"
            )
        return "\n".join(lines)

    def _order(self) -> list[int]:
        """Kalit indekslari tartibi.

        • priority — FAILOVER: har doim 1-kalitdan (asosiy provayder) boshlanadi;
          faqat u limit/xato bersa keyingisiga (zaxira) o'tadi. Shu tufayli deyarli
          BARCHA yangiliklar bir xil (eng aqlli) model bilan tahlil qilinadi.
        • mixed — round-robin: yuk barcha kalitlarga teng taqsimlanadi.
        """
        n = len(self.pool)
        if config.ai_pool_mode == "priority":
            return list(range(n))
        return [(self._rr + i) % n for i in range(n)]

    async def _chat(self, messages: list[dict], user_id: Optional[int] = None, **kwargs):
        """
        Kalitlarni round-robin bilan sinaydi. Birinchi muvaffaqiyatli javobni
        qaytaradi: (provider_name, model, response). Hammasi ishlamasa — None.
        """
        if not self.pool:
            return None

        order = self._order()
        # mixed rejimda keyingi chaqiruv navbatdagi kalitdan boshlanadi (teng taqsimot).
        # priority rejimda ko'rsatkich siljimaydi — doim asosiy (eng aqlli) kalit birinchi.
        if config.ai_pool_mode != "priority":
            self._rr = (self._rr + 1) % len(self.pool)

        last_error: Optional[Exception] = None
        # 1-o'tish: faqat dam olmayotgan kalitlar. 2-o'tish: oxirgi chora sifatida hammasi.
        for allow_cooling in (False, True):
            for idx in order:
                now = time.monotonic()
                if not allow_cooling and self._cooldown_until.get(idx, 0) > now:
                    continue
                prov = self.pool[idx]
                try:
                    response = await prov["client"].chat.completions.create(
                        model=prov["model"], messages=messages, **kwargs
                    )
                    prov["requests"] += 1
                    await self._log_usage(prov, response, user_id)
                    return prov["name"], prov["model"], response
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if _is_rate_limit(exc):
                        prov["rate_limits"] += 1
                        wait = _retry_after(exc, self._cooldown_sec)
                        self._cooldown_until[idx] = time.monotonic() + wait
                        logger.warning(
                            "AI kalit #%d (%s …%s) limitga uchradi — %.0fs dam.",
                            idx, prov["name"], prov["key_tail"], wait,
                        )
                    else:
                        logger.warning(
                            "AI kalit #%d (%s …%s) xatosi: %s",
                            idx, prov["name"], prov["key_tail"], exc,
                        )
                    continue
            # 1-o'tishda hech biri ishlamasa (hammasi dam yoki xato) — 2-o'tishga
            if last_error is None:
                break

        if last_error is not None:
            logger.error("Barcha AI kalitlari ishlamadi: %s", last_error)
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
            f"• summary — yangilik mazmuni {lang}, 1-3 qisqa gap. Reklama/e'lon bo'lsa bo'sh qoldir.\n"
            f"• category — FAQAT shulardan biri: {cats}\n"
            "• importance — yangilikning ahamiyati (1-5 butun son). Bu mezon HAR QANDAY "
            "soha uchun bir xil ishlaydi: yangilikni O'Z SOHASI ichida bahola "
            "(siyosat, iqtisod, sport, kino/media, texnologiya, jamiyat va h.k.). "
            "Har bir sohada ham 5, ham 1 bo'lishi mumkin.\n"
            "   5 = Favqulodda/tarixiy: o'z sohasida juda kam uchraydigan, katta ta'sirli yoki "
            "tezkor voqea. Masalan — siyosat: urush, saylov/iste'fo, yirik xalqaro kelishuv; "
            "iqtisod: valyuta yoki bozor shoki, inqiroz; sport: JCh/Olimpiada finali yoki jahon "
            "rekordi; kino/media: Oskar kabi yirik mukofot natijasi yoki juda kutilgan yirik "
            "premyera; texnologiya: sohani o'zgartiruvchi yirik e'lon.\n"
            "   4 = Yuqori: sohada jiddiy, keng muhokama qilinadigan yangilik. Masalan — muhim "
            "qonun/qaror; yirik musobaqa o'yini natijasi yoki katta transfer; mashhur filmning "
            "premyerasi/treyleri yoki nufuzli kasting; muhim mahsulot chiqishi.\n"
            "   3 = O'rta: e'tiborga arziydigan, lekin ta'siri cheklangan oddiy yangilik.\n"
            "   2 = Past: mayda, mahalliy yoki yengil/ko'ngilochar xabar.\n"
            "   1 = Ahamiyatsiz: reklama, e'lon, takroriy yoki kam qiymatli kontent.\n"
            "   Baholashda hisobga ol: voqea o'z sohasida qanchalik kam uchraydigan/kutilmagan, "
            "nechta odamni qiziqtiradi, ta'sir doirasi va shoshilinchligi. 5-darajani faqat "
            "chinakam kam uchraydigan, katta voqealarga ber (ortiqcha breaking chiqmasin).\n"
            "   Muhim: O'zbekiston va Markaziy Osiyoga oid yangiliklarni bir pog'ona yuqoriroq bahola.\n"
            "• sentiment — positive, negative yoki neutral.\n"
        )

    async def analyze_story(
        self, text: str, user_id: Optional[int] = None
    ) -> Optional[dict]:
        """
        Bitta yangilik matnini tahlil qiladi.
        Qaytaradi: {summary, category, importance, sentiment} yoki None.
        """
        if not self.pool:
            return None
        result = await self._chat(
            messages=[
                {"role": "system", "content": self._story_system_prompt()},
                {"role": "user", "content": text[:4000]},
            ],
            user_id=user_id,
            temperature=0.2,
            max_tokens=600,
            response_format={"type": "json_object"},
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
