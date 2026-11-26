"""
SmartPresence — Neon PostgreSQL Connection & Schema Verification Script
Executes real connection, SSL handshake, table creation, and transaction tests.
"""
import asyncio
import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

async def test_connection():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("\n[ERROR] DATABASE_URL is not set in your .env file.")
        print("Please set your Neon PostgreSQL connection string in .env like:")
        print("DATABASE_URL=postgresql+asyncpg://<user>:<password>@<ep-pool-host>.neon.tech/<dbname>?sslmode=require\n")
        return False

    if db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Clean query parameters for asyncpg compatibility
    # asyncpg expects 'ssl' rather than 'sslmode' or 'channel_binding'
    base_url = db_url.split("?")[0]
    
    print(f"\n[*] Initiating Neon PostgreSQL Connection Test...")
    print(f"[*] Target Host: {base_url.split('@')[-1].split('/')[0] if '@' in base_url else 'Unknown'}")
    
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    connect_args = {"ssl": "require"}

    start_time = time.time()
    try:
        engine = create_async_engine(
            base_url,
            connect_args=connect_args,
            pool_pre_ping=True
        )
        async with engine.connect() as conn:
            # Test 1: Simple query & version check
            res = await conn.execute(text("SELECT version();"))
            db_version = res.scalar()
            latency = (time.time() - start_time) * 1000

            print(f"[SUCCESS] Connected to Neon PostgreSQL!")
            print(f"[*] Latency: {latency:.2f} ms")
            print(f"[*] Server Version: {db_version}\n")

            # Test 2: Transaction test
            print("[*] Testing Atomic Transaction & Schema Creation...")
            await conn.execute(text("CREATE TABLE IF NOT EXISTS _neon_healthcheck (id serial PRIMARY KEY, test_val varchar(50));"))
            await conn.execute(text("INSERT INTO _neon_healthcheck (test_val) VALUES ('smartpresence_ok');"))
            test_row = await conn.execute(text("SELECT test_val FROM _neon_healthcheck LIMIT 1;"))
            val = test_row.scalar()
            await conn.execute(text("DROP TABLE _neon_healthcheck;"))
            
            print(f"[SUCCESS] Transaction executed & cleaned up successfully (Sample: '{val}').")
            print("[SUCCESS] Neon PostgreSQL is fully operational for SmartPresence!\n")
            return True
    except Exception as e:
        print(f"\n[FAIL] Connection failed: {str(e)}")
        print("\nTroubleshooting tips for Neon:")
        print("1. Ensure 'sslmode=require' is present in your connection string.")
        print("2. Ensure the driver is 'postgresql+asyncpg://' instead of 'postgresql://'.")
        print("3. Check if password special characters are URL-encoded if applicable.\n")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_connection())
    sys.exit(0 if success else 1)
