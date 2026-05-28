import asyncio
from sqlalchemy import text
from mimic42.config import Settings
from mimic42.integrations.database_session import create_engine, create_session_factory

async def inspect():
    settings = Settings()
    engine = create_engine(settings.database_connection_string)
    session_maker = create_session_factory(engine)
    
    async with session_maker() as session:
        # Get table constraints
        res = await session.execute(text("""
            SELECT conname, contype, pg_get_constraintdef(oid) 
            FROM pg_constraint 
            WHERE conrelid = 'public.agent_onboarding_sessions'::regclass;
        """))
        print("\n--- CONSTRAINTS ---")
        for row in res.all():
            print(row)
            
        # Get indexes
        res = await session.execute(text("""
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE tablename = 'agent_onboarding_sessions';
        """))
        print("\n--- INDEXES ---")
        for row in res.all():
            print(row)
            
        # Get triggers
        res = await session.execute(text("""
            SELECT tgname 
            FROM pg_trigger 
            WHERE tgrelid = 'public.agent_onboarding_sessions'::regclass;
        """))
        print("\n--- TRIGGERS ---")
        for row in res.all():
            print(row)

if __name__ == "__main__":
    asyncio.run(inspect())
