"""Bootstrap: Create all tables and seed admin user."""
import asyncio
from app.db.session import engine
from app.db.base import Base

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully!")

async def main():
    await create_tables()
    # Now run the seeder
    from app.seeder import seed_data
    await seed_data()
    print("Database bootstrapped!")

if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
