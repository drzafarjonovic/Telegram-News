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

    # AI
    ai_provider: str = os.getenv("AI_PROVIDER", "groq").strip().lower()
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_model: str = os.getenv("AI_MODEL", "").strip()

    # Tahlil
    analysis_language: str = os.getenv("ANALYSIS_LANGUAGE", "uz").strip().lower()

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
        if not self.ai_api_key:
            errors.append("AI_API_KEY belgilanmagan.")
        if not self.admin_ids:
            errors.append("ADMIN_IDS belgilanmagan (kamida bitta admin ID kerak).")
        return errors


config = Config()
