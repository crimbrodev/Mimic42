import asyncio
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from mimic42.config import Settings
from mimic42.integrations.database_session import create_engine, create_session_factory
from mimic42.integrations.database_models import AgentOnboardingSessionModel

async def test_upsert():
    settings = Settings()
    engine = create_engine(settings.database_connection_string)
    session_maker = create_session_factory(engine)
    
    owner_id = "f03ec7c0-bfce-460d-9ff2-65895c3f2a10"
    
    async with session_maker() as session:
        try:
            stmt = insert(AgentOnboardingSessionModel).values(
                owner_id=owner_id,
                agent_name="42 брат",
            ).on_conflict_do_update(
                index_elements=["owner_id"],
                set_={
                    "agent_name": "42 брат",
                }
            )
            await session.execute(stmt)
            await session.commit()
            print("SQLAlchemy upsert succeeded!")
        except Exception as exc:
            import traceback
            print("SQLAlchemy upsert failed:")
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_upsert())
