import asyncio
import os
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

# Load environment variables from main .env
load_dotenv("/home/sasha42/Mimic42-main/.env")

connection_string = os.getenv("DATABASE_CONNECTION_STRING")
if not connection_string:
    print("Error: DATABASE_CONNECTION_STRING is not set in .env")
    sys.exit(1)

# Convert connection string to asyncpg compatible
if connection_string.startswith("postgresql://"):
    connection_string = connection_string.replace("postgresql://", "postgresql+asyncpg://", 1)
elif connection_string.startswith("postgres://"):
    connection_string = connection_string.replace("postgres://", "postgresql+asyncpg://", 1)

async def inspect():
    try:
        engine = create_async_engine(connection_string)
        async with engine.connect() as conn:
            print("Connected to Supabase Database via asyncpg successfully!")
            
            # Check profiles table
            print("\n=== PROFILES TABLE ===")
            res = await conn.execute(text("SELECT * FROM public.profiles LIMIT 10"))
            cols = res.keys()
            rows = res.fetchall()
            print(f"Columns: {list(cols)}")
            for r in rows:
                print(dict(zip(cols, r)))
                
            # Check agents table
            print("\n=== AGENTS TABLE ===")
            res = await conn.execute(text("SELECT * FROM public.agents LIMIT 10"))
            cols = res.keys()
            rows = res.fetchall()
            print(f"Columns: {list(cols)}")
            for r in rows:
                print(dict(zip(cols, r)))

        await engine.dispose()
    except Exception as e:
        print(f"Error querying database: {e}")

if __name__ == "__main__":
    asyncio.run(inspect())

