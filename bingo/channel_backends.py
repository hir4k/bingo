from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

from bingo.exceptions import BingoChannelError


class MemorySubscription:
    def __init__(
        self,
        backend: MemoryChannelBackend,
        stream: str,
        queue: asyncio.Queue,
    ) -> None:
        self.backend = backend
        self.stream = stream
        self.queue = queue

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            yield await self.queue.get()

    async def close(self) -> None:
        subscribers = self.backend.subscribers.get(self.stream, set())
        subscribers.discard(self.queue)
        if not subscribers:
            self.backend.subscribers.pop(self.stream, None)


class MemoryChannelBackend:
    def __init__(self) -> None:
        self.subscribers: dict[str, set[asyncio.Queue]] = {}

    async def subscribe(self, stream: str) -> MemorySubscription:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.setdefault(stream, set()).add(queue)
        return MemorySubscription(self, stream, queue)

    async def publish(self, stream: str, message: dict[str, Any]) -> None:
        for queue in self.subscribers.get(stream, set()):
            queue.put_nowait(message)

    async def close(self) -> None:
        self.subscribers.clear()


class RedisSubscription:
    def __init__(self, pubsub, stream: str) -> None:
        self.pubsub = pubsub
        self.stream = stream

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        async for message in self.pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                yield json.loads(message["data"])
            except (TypeError, ValueError) as error:
                raise BingoChannelError(
                    f"Channel stream {self.stream!r} received invalid JSON."
                ) from error

    async def close(self) -> None:
        await self.pubsub.unsubscribe(self.stream)
        await self.pubsub.aclose()


class RedisChannelBackend:
    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis

        self.client = Redis.from_url(url, decode_responses=True)

    async def subscribe(self, stream: str) -> RedisSubscription:
        pubsub = self.client.pubsub()
        await pubsub.subscribe(stream)
        return RedisSubscription(pubsub, stream)

    async def publish(self, stream: str, message: dict[str, Any]) -> None:
        await self.client.publish(stream, json.dumps(message, allow_nan=False))

    async def close(self) -> None:
        await self.client.aclose()


class PostgresSubscription:
    def __init__(self, connection, channel: str, stream: str) -> None:
        self.connection = connection
        self.channel = channel
        self.stream = stream

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        async for notification in self.connection.notifies():
            try:
                yield json.loads(notification.payload)
            except (TypeError, ValueError) as error:
                raise BingoChannelError(
                    f"Channel stream {self.stream!r} received invalid JSON."
                ) from error

    async def close(self) -> None:
        await self.connection.close()


class PostgresChannelBackend:
    def __init__(self, url: str) -> None:
        self.url = url
        self.publisher = None
        self.publisher_lock = asyncio.Lock()

    async def subscribe(self, stream: str) -> PostgresSubscription:
        from psycopg import AsyncConnection, sql

        connection = await AsyncConnection.connect(self.url, autocommit=True)
        channel = _postgres_channel(stream)
        statement = sql.SQL("LISTEN {}").format(sql.Identifier(channel))
        await connection.execute(statement)
        return PostgresSubscription(connection, channel, stream)

    async def publish(self, stream: str, message: dict[str, Any]) -> None:
        from psycopg import AsyncConnection

        payload = json.dumps(message, allow_nan=False)
        if len(payload.encode("utf-8")) >= 8_000:
            raise BingoChannelError(
                "PostgreSQL channel broadcasts must be smaller than 8,000 bytes."
            )

        async with self.publisher_lock:
            if self.publisher is None or self.publisher.closed:
                self.publisher = await AsyncConnection.connect(
                    self.url,
                    autocommit=True,
                )
            channel = _postgres_channel(stream)
            await self.publisher.execute(
                "SELECT pg_notify(%s, %s)",
                (channel, payload),
            )

    async def close(self) -> None:
        if self.publisher is not None and not self.publisher.closed:
            await self.publisher.close()


def channel_backend(url: str):
    scheme = url.split(":", 1)[0].lower()
    if scheme == "memory":
        return MemoryChannelBackend()
    if scheme in {"redis", "rediss"}:
        return RedisChannelBackend(url)
    if scheme in {"postgres", "postgresql"}:
        return PostgresChannelBackend(url)
    raise BingoChannelError("CHANNEL_URL supports memory, PostgreSQL, and Redis URLs.")


def _postgres_channel(stream: str) -> str:
    digest = hashlib.sha256(stream.encode("utf-8")).hexdigest()[:48]
    return f"bingo_{digest}"
