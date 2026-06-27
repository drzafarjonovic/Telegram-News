"""
Telethon StringSession yaratish skripti (bir martalik).

Buni LOKAL kompyuteringizda ishga tushiring:
    python login.py

Telefon raqami, Telegram kodi (va kerak bo'lsa 2FA paroli) so'raladi.
Natijada chiqqan uzun satrni STRING_SESSION sifatida .env yoki
Railway Variables'ga qo'ying. Bu satrni HECH KIMGA bermang!
"""
import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import config


async def main() -> None:
    if not config.api_id or not config.api_hash:
        print("❌ Avval .env faylga API_ID va API_HASH ni yozing "
              "(my.telegram.org dan oling).")
        return

    print("📱 Telegram akkauntingizga kirish...\n")
    async with TelegramClient(
        StringSession(), config.api_id, config.api_hash
    ) as client:
        session_str = client.session.save()
        me = await client.get_me()
        print("\n" + "=" * 60)
        print(f"✅ Kirildi: {me.first_name} (@{me.username})")
        print("=" * 60)
        print("\nQuyidagi STRING_SESSION'ni .env / Railway Variables'ga qo'ying:\n")
        print(session_str)
        print("\n⚠️  Bu satrni hech kimga bermang — u akkauntingizga to'liq kirish beradi!")


if __name__ == "__main__":
    asyncio.run(main())
