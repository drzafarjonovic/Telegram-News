"""
asyncpg ulanish puli (Supabase / PostgreSQL).

`db.pool` global pulni saqlaydi; `init_db()` ulanishni ochadi va
schema.sql ni bajaradi.
"""
import logging
import os
import ssl

import asyncpg

logger = logging.getLogger(__name__)

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


class Database:
    """Asinxron ulanish pulini boshqaradi."""

    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None

    async def connect(self, dsn: str) -> None:
        if self.pool is not None:
            return
        # Supabase TLS talab qiladi; sertifikatni qat'iy tekshirmaymiz
        # (pooler bilan ishlashni soddalashtirish uchun).
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        self.pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=1,
            max_size=10,
            ssl=ssl_ctx,
            command_timeout=60,
        )
        logger.info("PostgreSQL puliga ulanildi.")

    async def init_schema(self) -> None:
        if self.pool is None:
            raise RuntimeError("Avval connect() chaqiring.")
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        async with self.pool.acquire() as conn:
            await conn.execute(schema_sql)
        logger.info("Ma'lumotlar bazasi sxemasi tayyor.")

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
