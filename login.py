"""
Telethon StringSession yaratish skripti (bir martalik).

Bu skript MUSTAQIL ishlaydi — faqat `telethon` kerak (config/.env shart emas).
Shuning uchun uni telefonda Pydroid3'da ham bemalol ishga tushirish mumkin.

ISHGA TUSHIRISH:
    1) Pydroid3'da:  pip install telethon
    2) Bu faylni oching va "Run" (▶) tugmasini bosing.
    3) So'ralganda API_ID, API_HASH, telefon raqami va Telegram kodini kiriting.
    4) Chiqqan uzun STRING_SESSION satrini nusxalab, Railway "Variables" ga
       STRING_SESSION sifatida qo'ying.

⚠️  STRING_SESSION akkauntingizga to'liq kirish beradi — uni hech kimga bermang!
"""
import asyncio

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    raise SystemExit(
        "❌ Telethon o'rnatilmagan. Avval shuni bajaring:\n   pip install telethon"
    )


async def main() -> None:
    print("=" * 60)
    print("  Telegram StringSession yaratish")
    print("=" * 60)
    print("API_ID va API_HASH'ni https://my.telegram.org dan oling.\n")

    api_id_raw = input("API_ID (raqam): ").strip()
    if not api_id_raw.isdigit():
        print("❌ API_ID raqam bo'lishi kerak.")
        return
    api_id = int(api_id_raw)
    api_hash = input("API_HASH: ").strip()

    if not api_hash:
        print("❌ API_HASH bo'sh bo'lishi mumkin emas.")
        return

    print("\n📱 Telegram'ga kirish (telefon raqami +998... ko'rinishida)...\n")
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        me = await client.get_me()
        session_str = client.session.save()
        print("\n" + "=" * 60)
        print(f"✅ Kirildi: {me.first_name} (@{me.username})")
        print("=" * 60)
        print("\n👇 Quyidagi STRING_SESSION'ni Railway Variables'ga qo'ying:\n")
        print(session_str)
        print("\n⚠️  Bu satrni hech kimga bermang!")


# Skriptni to'g'ridan-to'g'ri ishga tushiramiz (Pydroid3 uchun qulay,
# nusxalashда __name__ kabi maxsus belgilar muammo tug'dirmasligi uchun)
asyncio.run(main())
