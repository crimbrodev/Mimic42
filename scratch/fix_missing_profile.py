import asyncio
from sqlalchemy import text
from mimic42.config import Settings
from mimic42.integrations.database_session import create_engine, create_session_factory

async def fix():
    settings = Settings()
    engine = create_engine(settings.database_connection_string)
    session_maker = create_session_factory(engine)
    
    user_id = "a4e3a22c-4fea-4639-9f1d-aa2b8e17d1aa"
    email = "crambor228@gmail.com"
    display_name = "crimbor228"
    
    async with session_maker() as session:
        try:
            # Insert the missing profile row
            query = text("""
                INSERT INTO public.profiles (id, email, display_name, created_at, updated_at)
                VALUES (:id, :email, :display_name, now(), now())
                ON CONFLICT (id) DO NOTHING;
            """)
            await session.execute(query, {
                "id": user_id,
                "email": email,
                "display_name": display_name
            })
            await session.commit()
            print("Successfully inserted missing profile for crambor228@gmail.com!")
        except Exception as exc:
            import traceback
            print("Failed to insert profile:")
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(fix())
