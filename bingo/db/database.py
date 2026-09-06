from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from bingo.exceptions import BingoDatabaseError


class Database:
    def __init__(self) -> None:
        self.url: str | None = None
        self.engine: AsyncEngine | None = None
        self._sessions: sessionmaker[AsyncSession] | None = None

    def configure(self, url: str) -> None:
        if self.url == url and self.engine is not None:
            return
        self.url = url
        self.engine = create_async_engine(url)
        self._sessions = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @asynccontextmanager
    async def session(self):
        if self._sessions is None:
            raise BingoDatabaseError(
                "The database is not configured. Define DATABASE_URL in the active "
                "config/settings environment."
            )
        async with self._sessions() as session:
            yield session

    async def dispose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
        self.engine = None
        self._sessions = None
        self.url = None


database = Database()
