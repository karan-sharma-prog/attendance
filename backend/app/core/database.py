from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from backend.app.core.config import settings
import logging

logger = logging.getLogger("smartpresence.database")

Base = declarative_base()

engine = None
AsyncSessionLocal = None


def get_engine():
    global engine, AsyncSessionLocal
    if engine is None:
        db_url = settings.DATABASE_URL
        if not db_url:
            logger.warning("DATABASE_URL not set in .env. Falling back to local sqlite+aiosqlite for bootstrap validation.")
            db_url = "sqlite+aiosqlite:///./smartpresence_bootstrap.db"
            engine = create_async_engine(db_url, echo=False)
        else:
            if db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
                db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

            base_url = db_url.split("?")[0]
            connect_args = {}
            if "neon.tech" in db_url or "sslmode" in db_url or "ssl" in db_url:
                connect_args["ssl"] = "require"

            engine = create_async_engine(
                base_url,
                echo=False,
                connect_args=connect_args,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=300,
            )
        AsyncSessionLocal = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False
        )
    return engine

async def get_db():
    get_engine()
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
