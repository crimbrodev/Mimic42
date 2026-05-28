import asyncio
from sqlalchemy import select
from mimic42.config import Settings
from mimic42.integrations.database_session import create_engine, create_session_factory
from mimic42.integrations.database_models import AgentOnboardingSessionModel, AgentModel, ProfileModel

async def check():
    settings = Settings()
    print("Database string:", settings.database_connection_string)
    engine = create_engine(settings.database_connection_string)
    session_maker = create_session_factory(engine)
    
    async with session_maker() as session:
        # Check profiles
        res = await session.execute(select(ProfileModel))
        profiles = res.scalars().all()
        print(f"\n--- PROFILES ({len(profiles)}) ---")
        for p in profiles:
            print(f"ID: {p.id}, Email: {p.email}")
            
        # Check onboarding sessions
        res = await session.execute(select(AgentOnboardingSessionModel))
        sessions = res.scalars().all()
        print(f"\n--- ONBOARDING SESSIONS ({len(sessions)}) ---")
        for s in sessions:
            print(f"ID: {s.id}, Owner: {s.owner_id}, Name: {s.agent_name}, Status: {s.authorization_status}, CompletedAgentID: {s.completed_agent_id}")
            
        # Check agents
        res = await session.execute(select(AgentModel))
        agents = res.scalars().all()
        print(f"\n--- AGENTS ({len(agents)}) ---")
        for a in agents:
            print(f"ID: {a.id}, Owner: {a.owner_id}, Name: {a.name}, Status: {a.status}")

if __name__ == "__main__":
    asyncio.run(check())
