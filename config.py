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

    @property
    def ai_base_url(self) -> str | None:
        return BASE_URLS.get(self.ai_provider)

    @property
    def model_name(self) -> str:
        return self.ai_model or DEFAULT_MODELS.get(self.ai_provider, "gpt-4o-mini")

    def _provider_key(self, name: str) -> str:
        """Provayder uchun API kalitini topadi (per-provider yoki asosiy)."""
        specific = {
            "groq": self.groq_api_key,
            "gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
        }.get(name, "")
        if specific:
            return specific
        # Agar bu asosiy provayder bo'lsa, umumiy AI_API_KEY ishlaydi
        if name == self.ai_provider:
            return self.ai_api_key
        return ""

    def ai_providers(self) -> list[dict]:
        """
        Tartiblangan provayderlar ro'yxati: avval asosiy, keyin fallbacklar.
        Faqat API kaliti mavjud bo'lganlari qaytariladi.
        """
        order: list[str] = [self.ai_provider]
        for part in self.ai_fallbacks_raw.replace(";", ",").split(","):
            p = part.strip().lower()
            if p and p in DEFAULT_MODELS and p not in order:
                order.append(p)

        result: list[dict] = []
        for name in order:
            key = self._provider_key(name)
            if not key:
                continue
            model = self.ai_model if (name == self.ai_provider and self.ai_model) else DEFAULT_MODELS[name]
            result.append(
                {
                    "name": name,
                    "api_key": key,
                    "base_url": BASE_URLS.get(name),
                    "model": model,
                }
            )
        return result

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
        if not self.ai_providers():
            errors.append(
                "Birorta ham AI kaliti topilmadi (AI_API_KEY yoki "
                "GROQ_API_KEY/GEMINI_API_KEY/OPENAI_API_KEY)."
            )
        if not self.admin_ids:
            errors.append("ADMIN_IDS belgilanmagan (kamida bitta admin ID kerak).")
        return errors


config = Config()
