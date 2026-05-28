import asyncio
from sqlalchemy import text
from mimic42.config import Settings
from mimic42.integrations.database_session import create_engine, create_session_factory

async def test_raw_sql():
    settings = Settings()
    engine = create_engine(settings.database_connection_string)
    session_maker = create_session_factory(engine)
    
    async with session_maker() as session:
        try:
            # We simulate the exact insert that PostgREST does:
            # It generates a new ID, but owner_id already exists.
            query = text("""
                INSERT INTO public.agent_onboarding_sessions (id, owner_id, agent_name, updated_at)
                VALUES (gen_random_uuid(), 'f03ec7c0-bfce-460d-9ff2-65895c3f2a10', '42 брат', now())
                ON CONFLICT (owner_id) 
                DO UPDATE SET agent_name = EXCLUDED.agent_name, updated_at = EXCLUDED.updated_at
                RETURNING *;
            """)
            res = await session.execute(query)
            row = res.first()
            await session.commit()
            print("Raw SQL upsert succeeded!")
            print("Returned row:", row)
        except Exception as exc:
            import traceback
            print("Raw SQL upsert failed:")
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_raw_sql())
