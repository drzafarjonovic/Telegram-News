"""
asyncpg ulanish puli (Supabase / PostgreSQL).

`db.pool` global pulni saqlaydi; `init_db()` ulanishni ochadi va
schema.sql ni bajaradi.
"""
import logging
import os
import ssl

import asyncpg

from config import config

logger = logging.getLogger(__name__)

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def _safe_schema(name: str) -> str:
    """SQL injectiondan saqlanish uchun schema nomini tozalaydi."""
    cleaned = "".join(c for c in name if c.isalnum() or c == "_")
    return cleaned or "tgnews"


class Database:
    """Asinxron ulanish pulini boshqaradi."""

    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None
        self.schema: str = _safe_schema(config.db_schema)

    async def connect(self, dsn: str) -> None:
        if self.pool is not None:
            return
        # Supabase TLS talab qiladi; sertifikatni qat'iy tekshirmaymiz
        # (pooler bilan ishlashni soddalashtirish uchun).
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        # Har bir ulanish o'z schema'sida ishlasin (boshqa loyihaga tegmaslik uchun)
        self.pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=1,
            max_size=10,
            ssl=ssl_ctx,
            command_timeout=60,
            # Supabase pooler (PgBouncer) bilan ishlash uchun prepared statement
            # keshini o'chiramiz — aks holda "prepared statement" xatolari chiqishi mumkin.
            statement_cache_size=0,
            server_settings={"search_path": f"{self.schema}, public"},
        )
        logger.info("PostgreSQL puliga ulanildi (schema: %s).", self.schema)

    async def init_schema(self) -> None:
        if self.pool is None:
            raise RuntimeError("Avval connect() chaqiring.")
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        async with self.pool.acquire() as conn:
            # Avval schema'ni yaratamiz, keyin jadvallarni (search_path shu schema'ga ishora qiladi)
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            await conn.execute(schema_sql)
        logger.info("Ma'lumotlar bazasi sxemasi tayyor (schema: %s).", self.schema)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
            logger.info("PostgreSQL puli yopildi.")

    def acquire(self):
        if self.pool is None:
            raise RuntimeError("Ma'lumotlar bazasi ulanmagan.")
        return self.pool.acquire()


# Global yagona obyekt
db = Database()


async def init_db(dsn: str) -> None:
    await db.connect(dsn)
    await db.init_schema()
