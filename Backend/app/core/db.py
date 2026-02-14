from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    future=True,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=300,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    session: AsyncSession | None = None
    try:
        session = AsyncSessionLocal()
        try:
            await session.execute(text('SELECT 1'))
        except Exception:
            await session.close()
            session = AsyncSessionLocal()
            await session.execute(text('SELECT 1'))
        yield session
    finally:
        if session is not None:
            await session.close()
