import asyncio
from sqlalchemy import select
from telethon import TelegramClient
from telethon.sessions import StringSession
from mimic42.config import Settings
from mimic42.core.crypto import FernetSecretCipher
from mimic42.integrations.database_session import create_engine, create_session_factory
from mimic42.integrations.database_models import TelegramSessionModel
from mimic42.integrations.telegram_tools import TelegramToolbox

async def test_live():
    settings = Settings()
    if not settings.database_connection_string:
        print("No database connection string found!")
        return

    print("Connecting to Supabase...")
    engine = create_engine(settings.database_connection_string)
    session_maker = create_session_factory(engine)
    
    async with session_maker() as db_session:
        res = await db_session.execute(select(TelegramSessionModel))
        row = res.first()
        if not row:
            print("No Telegram sessions found in the database!")
            return
        ts = row[0]
        
    print("Decrypting credentials using FernetSecretCipher...")
    cipher = FernetSecretCipher(settings.secret_key)
    api_id = ts.api_id
    api_hash = cipher.decrypt(ts.api_hash_ciphertext)
    session_str = cipher.decrypt(ts.session_ciphertext)
    
    print(f"Telegram API ID: {api_id}")
    print(f"Phone Number: {ts.phone_number}")
    print(f"Status: {ts.authorization_status}")

    print("Connecting to live Telegram...")
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("User is not authorized in Telegram!")
        return
        
    me = await client.get_me()
    print(f"Successfully connected to Telegram as {me.first_name} (@{me.username})")
    
    toolbox = TelegramToolbox(client)
    
    print("\n--- Testing: search_location ---")
    query = "Красная Площадь, Москва"
    print(f"Searching for: '{query}'")
    loc_res = await toolbox.search_location(query)
    print("search_location result:", loc_res)
    
    print("\n--- Testing: get_chat_folders ---")
    folders = await toolbox.get_chat_folders()
    print("get_chat_folders returned:")
    for f in folders:
        print(f"Folder: ID={f['id']}, Title={f['title']}, Emoticon={f.get('emoticon', 'None')}, Type={f.get('type', 'custom')}")

    await client.disconnect()
    print("Disconnected from Telegram successfully.")

if __name__ == "__main__":
    asyncio.run(test_live())
