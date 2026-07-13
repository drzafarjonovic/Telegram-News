"""
Loyiha konfiguratsiyasi — barcha sozlamalar .env (yoki Railway Variables) dan o'qiladi.
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_id_list(name: str) -> list[int]:
    raw = os.getenv(name, "")
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


# Har bir provayder uchun standart model
DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
}

# Har bir provayder uchun OpenAI-compatible bazaviy URL
BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": None,  # OpenAI standart URL (rasmiy SDK default)
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}


# Mavjud kategoriyalar (AI shu ro'yxatdan tanlaydi)
CATEGORIES = [
    "Siyosat",
    "Iqtisod",
    "Sport",
    "Texnologiya",
    "IT",
    "AI",
    "Media",
    "Xalqaro",
    "Jamiyat",
    "Sog'liq",
    "Ta'lim",
    "Boshqa",
]


@dataclass
class Config:
    # Bot
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admin_ids: tuple[int, ...] = tuple(_get_id_list("ADMIN_IDS"))

    # Userbot
    api_id: int = _get_int("API_ID", 0)
    api_hash: str = os.getenv("API_HASH", "")
    string_session: str = os.getenv("STRING_SESSION", "")

    # Ma'lumotlar bazasi
    database_url: str = os.getenv("DATABASE_URL", "")
    # Postgres schema (boshqa loyiha bilan bitta Supabase'ni baham ko'rish uchun)
    db_schema: str = os.getenv("DB_SCHEMA", "tgnews").strip() or "tgnews"

    # AI — asosiy provayder
    ai_provider: str = os.getenv("AI_PROVIDER", "groq").strip().lower()
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_model: str = os.getenv("AI_MODEL", "").strip()

    # AI — fallback (zaxira) provayderlar va per-provider kalitlar
    ai_fallbacks_raw: str = os.getenv("AI_FALLBACKS", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    # Tahlil
    analysis_language: str = os.getenv("ANALYSIS_LANGUAGE", "uz").strip().lower()

    # Cache pipeline / dedup
    dedup_similarity: float = _get_float("DEDUP_SIMILARITY", 0.5)
    process_batch_size: int = _get_int("PROCESS_BATCH_SIZE", 25)

    # Boshqa
    timezone: str = os.getenv("TIMEZONE", "Asia/Tashkent")
    max_channels_per_user: int = _get_int("MAX_CHANNELS_PER_USER", 10)
    max_posts_per_chunk: int = _get_int("MAX_POSTS_PER_CHUNK", 40)

    # ---- Enterprise v2.0: ingest pipeline (navbat + workerlar) ----
    ingest_workers: int = _get_int("INGEST_WORKERS", 4)
    ingest_queue_max: int = _get_int("INGEST_QUEUE_MAX", 5000)
    store_raw: bool = os.getenv("STORE_RAW_MESSAGES", "true").strip().lower() in ("1", "true", "yes", "on")

    # ---- Enterprise v2.0: backfill (GetHistory, bo'shliqlarni to'ldirish) ----
    backfill_enabled: bool = os.getenv("BACKFILL_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
    backfill_limit: int = _get_int("BACKFILL_LIMIT", 100)
    backfill_interval_min: int = _get_int("BACKFILL_INTERVAL_MIN", 60)

    # ---- Enterprise v2.0: media (OCR / Speech-to-Text) ----
    ocr_enabled: bool = os.getenv("OCR_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    ocr_langs: str = os.getenv("OCR_LANGS", "eng").strip() or "eng"
    stt_enabled: bool = os.getenv("STT_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    stt_api_key: str = os.getenv("STT_API_KEY", "")
    stt_base_url: str = os.getenv("STT_BASE_URL", "").strip()
    stt_model: str = os.getenv("STT_MODEL", "whisper-1").strip() or "whisper-1"
    media_download_max_mb: int = _get_int("MEDIA_DOWNLOAD_MAX_MB", 15)

    # ---- Enterprise v2.0: monitoring (Prometheus metrikslari) ----
    metrics_enabled: bool = os.getenv("METRICS_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
    metrics_port: int = _get_int("METRICS_PORT", 9101)

    # ---- v3.0: AI kalitlar pooli (round-robin + cooldown) ----
    # AI_POOL_MODE: 'mixed' = barcha provayder kalitlari bitta navbatda (round-robin),
    #              'priority' = avval asosiy provayder kalitlari, keyin fallbacklar.
    ai_pool_mode: str = os.getenv("AI_POOL_MODE", "mixed").strip().lower()
    # Limitga (429) uchragan kalit necha soniya "dam" oladi (Retry-After bo'lmasa).
    ai_cooldown_sec: int = _get_int("AI_COOLDOWN_SEC", 60)

    # ---- v3.0: "Hozir yuborish" cheklovi (spamdan himoya) ----
    manual_digest_cooldown_min: int = _get_int("MANUAL_DIGEST_COOLDOWN_MIN", 10)

    @property
    def ai_base_url(self) -> str | None:
        return BASE_URLS.get(self.ai_provider)

    @property
    def model_name(self) -> str:
        return self.ai_model or DEFAULT_MODELS.get(self.ai_provider, "gpt-4o-mini")

    @staticmethod
    def _split_keys(raw: str) -> list[str]:
        """Vergul/nuqta-vergul/yangi qator bilan ajratilgan kalitlarni ro'yxatga aylantiradi."""
        keys: list[str] = []
        for part in (raw or "").replace(";", ",").replace("\n", ",").split(","):
            k = part.strip()
            if k and k not in keys:
                keys.append(k)
        return keys

    def _provider_keys(self, name: str) -> list[str]:
        """Bitta provayderning BARCHA kalitlari (ko'p kalit qo'llab-quvvatlanadi)."""
        specific = {
            "groq": self.groq_api_key,
            "gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
        }.get(name, "")
        keys = self._split_keys(specific)
        # Asosiy provayder uchun umumiy AI_API_KEY(lar) ham qo'shiladi
        if name == self.ai_provider:
            for k in self._split_keys(self.ai_api_key):
                if k not in keys:
                    keys.append(k)
        return keys

    def _provider_order(self) -> list[str]:
        """Asosiy provayder + fallbacklar tartibi."""
        order: list[str] = [self.ai_provider]
        for part in self.ai_fallbacks_raw.replace(";", ",").split(","):
            p = part.strip().lower()
            if p and p in DEFAULT_MODELS and p not in order:
                order.append(p)
        return order

    def ai_providers(self) -> list[dict]:
        """
        Provayderlar ro'yxati (har biriga BITTA vakil kalit) — asosan validate va
        status ko'rsatish uchun. Kaliti bor provayderlar qaytariladi.
        """
        result: list[dict] = []
        for name in self._provider_order():
            keys = self._provider_keys(name)
            if not keys:
                continue
            model = self.ai_model if (name == self.ai_provider and self.ai_model) else DEFAULT_MODELS[name]
            result.append(
                {
                    "name": name,
                    "api_key": keys[0],
                    "key_count": len(keys),
                    "base_url": BASE_URLS.get(name),
                    "model": model,
                }
            )
        return result

    def ai_key_pool(self) -> list[dict]:
        """
        Rotatsiya uchun to'liq kalitlar pooli — har element bitta (provayder, kalit).

        • mixed   — provayderlar orasida navbatlashadi (groq_k1, gemini_kA,
                    groq_k2, gemini_kB, ...): yuk hammasiga teng taqsimlanadi.
        • priority — avval asosiy provayderning barcha kalitlari, keyin fallbacklar.
        """
        per_provider: list[list[dict]] = []
        for name in self._provider_order():
            model = self.ai_model if (name == self.ai_provider and self.ai_model) else DEFAULT_MODELS[name]
            entries = [
                {
                    "name": name,
                    "api_key": key,
                    "base_url": BASE_URLS.get(name),
                    "model": model,
                }
                for key in self._provider_keys(name)
            ]
            if entries:
                per_provider.append(entries)

        if not per_provider:
            return []

        if self.ai_pool_mode == "priority":
            return [e for group in per_provider for e in group]

        # mixed: provayderlar bo'yicha round-robin (interleave)
        pool: list[dict] = []
        i = 0
        while True:
            added = False
            for group in per_provider:
                if i < len(group):
                    pool.append(group[i])
                    added = True
            if not added:
                break
            i += 1
        return pool

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    def validate(self) -> list[str]:
        """Sozlamalarni tekshiradi, xatolar ro'yxatini qaytaradi."""
        errors: list[str] = []
        if not self.bot_token:
            errors.append("BOT_TOKEN belgilanmagan (@BotFather dan oling).")
        if not self.api_id:
            errors.append("API_ID belgilanmagan (my.telegram.org dan oling).")
        if not self.api_hash:
            errors.append("API_HASH belgilanmagan (my.telegram.org dan oling).")
        if not self.database_url:
            errors.append("DATABASE_URL belgilanmagan (Supabase ulanish satri).")
        if self.ai_provider not in DEFAULT_MODELS:
            errors.append(
                f"AI_PROVIDER noto'g'ri: '{self.ai_provider}'. "
                f"Variantlar: {', '.join(DEFAULT_MODELS)}."
            )
        if not self.ai_key_pool():
            errors.append(
                "Birorta ham AI kaliti topilmadi (AI_API_KEY yoki "
                "GROQ_API_KEY/GEMINI_API_KEY/OPENAI_API_KEY)."
            )
        if not self.admin_ids:
            errors.append("ADMIN_IDS belgilanmagan (kamida bitta admin ID kerak).")
        return errors


config = Config()
