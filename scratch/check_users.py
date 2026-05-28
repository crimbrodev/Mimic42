import asyncio
from sqlalchemy import text
from mimic42.config import Settings
from mimic42.integrations.database_session import create_engine, create_session_factory

async def check():
    settings = Settings()
    engine = create_engine(settings.database_connection_string)
    session_maker = create_session_factory(engine)
    
    async with session_maker() as session:
        # Check auth.users
        res = await session.execute(text("SELECT id, email, created_at FROM auth.users;"))
        users = res.all()
        print(f"\n--- AUTH USERS ({len(users)}) ---")
        for u in users:
            print(u)

if __name__ == "__main__":
    asyncio.run(check())
