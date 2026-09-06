from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from weakref import WeakKeyDictionary

from starlette.websockets import WebSocket, WebSocketDisconnect

from bingo.channel_backends import channel_backend
from bingo.db.naming import snake_case
from bingo.exceptions import (
    BingoChannelError,
    BingoChannelRejected,
    BingoError,
    BingoValidationError,
)
from bingo.settings import settings
from bingo.templates import TemplateEngine

logger = logging.getLogger(__name__)
CHANNEL_NAME = re.compile(r"[A-Z][A-Za-z0-9]*Channel")
EVENT_NAME = re.compile(r"[a-z][a-z0-9_]*")


class Connection:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.headers = websocket.headers
        self.cookies = websocket.cookies
        self.query = dict(websocket.query_params)
        self.session = websocket.session

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    def reject(self, reason: str = "Connection rejected.") -> None:
        raise BingoChannelRejected(reason)


class Channel:
    def __init__(
        self,
        connection: Connection,
        identifier: str,
        params: dict[str, Any],
        broker: ChannelBroker,
        send,
    ) -> None:
        self.connection = connection
        self.identifier = identifier
        self.params = params
        self.session = connection.session
        self._broker = broker
        self._send = send
        self._streams: list[tuple[str, asyncio.Queue, asyncio.Task]] = []

    async def subscribed(self) -> None:
        pass

    async def received(self, data: dict[str, Any]) -> None:
        pass

    async def unsubscribed(self) -> None:
        pass

    async def stream(self, key: str | int) -> None:
        stream = type(self)._stream_name(key)
        if any(active == stream for active, _, _ in self._streams):
            return
        queue = await self._broker.subscribe(stream)
        forwarding = asyncio.create_task(self._forward(queue))
        self._streams.append((stream, queue, forwarding))

    @classmethod
    async def broadcast(
        cls,
        key: str | int,
        event: str,
        **context: Any,
    ) -> None:
        if not EVENT_NAME.fullmatch(event):
            raise BingoChannelError(
                f"Invalid channel event {event!r}. Use a lowercase name such as message."
            )

        templates = TemplateEngine(settings.root / "app" / "views")
        view = f"channels/{cls._view_name()}/{event}"
        data = templates.render_json_value(view, context=context)
        broker = await channel_broker()
        await broker.publish(
            cls._stream_name(key),
            {"event": event, "data": data},
        )

    async def close(self) -> None:
        try:
            await self.unsubscribed()
        finally:
            forwarding_tasks = []
            for stream, queue, forwarding in self._streams:
                forwarding.cancel()
                forwarding_tasks.append(forwarding)
                await self._broker.unsubscribe(stream, queue)
            self._streams.clear()
            await asyncio.gather(*forwarding_tasks, return_exceptions=True)

    async def _forward(self, queue: asyncio.Queue) -> None:
        while True:
            message = await queue.get()
            await self._send(
                {
                    "type": "message",
                    "identifier": self.identifier,
                    **message,
                }
            )

    async def _transmit(self, event: str, data: Any) -> None:
        await self._send(
            {
                "type": "message",
                "identifier": self.identifier,
                "event": event,
                "data": data,
            }
        )

    @classmethod
    def _stream_name(cls, key: str | int) -> str:
        if isinstance(key, bool) or not isinstance(key, str | int):
            raise BingoChannelError("Channel stream keys must be strings or integers.")
        return f"bingo:channels:{cls._view_name()}:{key}"

    @classmethod
    def _view_name(cls) -> str:
        return snake_case(cls.__name__.removesuffix("Channel"))


class ChannelBroker:
    def __init__(self, url: str, buffer_size: int) -> None:
        self.backend = channel_backend(url)
        self.buffer_size = buffer_size
        self.subscribers: dict[str, set[asyncio.Queue]] = {}
        self.listeners: dict[str, tuple[Any, asyncio.Task]] = {}
        self.lock = asyncio.Lock()

    async def subscribe(self, stream: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.buffer_size)
        async with self.lock:
            self.subscribers.setdefault(stream, set()).add(queue)
            if stream not in self.listeners:
                listener = await self.backend.subscribe(stream)
                task = asyncio.create_task(self._listen(stream, listener))
                self.listeners[stream] = (listener, task)
        return queue

    async def unsubscribe(self, stream: str, queue: asyncio.Queue) -> None:
        async with self.lock:
            subscribers = self.subscribers.get(stream, set())
            subscribers.discard(queue)
            if subscribers:
                return

            self.subscribers.pop(stream, None)
            listener, task = self.listeners.pop(stream, (None, None))
            if task is not None:
                task.cancel()
            if listener is not None:
                await listener.close()

    async def publish(self, stream: str, message: dict[str, Any]) -> None:
        await self.backend.publish(stream, message)

    async def close(self) -> None:
        async with self.lock:
            listeners = list(self.listeners.values())
            self.listeners.clear()
            self.subscribers.clear()

        for listener, task in listeners:
            task.cancel()
            await listener.close()
        await self.backend.close()

    async def _listen(self, stream: str, listener) -> None:
        try:
            async for message in listener.messages():
                for queue in self.subscribers.get(stream, set()):
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(message)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Channel stream %s stopped unexpectedly", stream)


_brokers: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    dict[tuple[Path, str], ChannelBroker],
] = WeakKeyDictionary()
_broker_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    WeakKeyDictionary()
)


async def channel_broker() -> ChannelBroker:
    url = _channel_url()
    loop = asyncio.get_running_loop()
    brokers = _brokers.setdefault(loop, {})
    key = (settings.root, url)
    if key in brokers:
        return brokers[key]

    lock = _broker_locks.setdefault(loop, asyncio.Lock())
    async with lock:
        if key in brokers:
            return brokers[key]
        buffer_size = settings.CHANNEL_BUFFER_SIZE
        is_valid_buffer = isinstance(buffer_size, int) and not isinstance(
            buffer_size, bool
        )
        if not is_valid_buffer or buffer_size < 1:
            raise BingoChannelError("CHANNEL_BUFFER_SIZE must be at least 1.")
        broker = ChannelBroker(url, buffer_size)
        brokers[key] = broker
        return broker


async def close_channel_brokers() -> None:
    loop = asyncio.get_running_loop()
    brokers = _brokers.pop(loop, {})
    _broker_locks.pop(loop, None)
    await asyncio.gather(
        *(broker.close() for broker in brokers.values()),
        return_exceptions=True,
    )


class ChannelServer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.channels: dict[str, type[Channel]] = {}

    async def handle(self, websocket: WebSocket) -> None:
        if not _origin_allowed(websocket):
            await websocket.close(code=4403, reason="Origin is not allowed.")
            return

        try:
            connection_class = _application_connection(self.root)
            connection = connection_class(websocket)
            await connection.connect()
        except BingoChannelRejected as error:
            await websocket.close(code=4403, reason=str(error))
            return
        except Exception:
            logger.exception("Channel connection setup failed")
            await websocket.close(code=1011, reason="Connection setup failed.")
            return

        await websocket.accept()
        broker = await channel_broker()
        subscriptions: dict[str, Channel] = {}
        send_lock = asyncio.Lock()

        async def send(message: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(message)

        try:
            while True:
                try:
                    message = await _receive_command(websocket)
                except BingoChannelError as error:
                    await send({"type": "error", "error": str(error)})
                    continue
                await self._handle_command(
                    message,
                    connection,
                    broker,
                    subscriptions,
                    send,
                )
        except WebSocketDisconnect:
            asyncio.create_task(self._disconnect(connection, subscriptions))
        except asyncio.CancelledError:
            await self._disconnect(connection, subscriptions)

    async def _disconnect(
        self,
        connection: Connection,
        subscriptions: dict[str, Channel],
    ) -> None:
        await asyncio.gather(
            *(channel.close() for channel in subscriptions.values()),
            return_exceptions=True,
        )
        try:
            await connection.disconnect()
        except Exception:
            logger.exception("Channel connection cleanup failed")

    async def _handle_command(
        self,
        message: dict[str, Any],
        connection: Connection,
        broker: ChannelBroker,
        subscriptions: dict[str, Channel],
        send,
    ) -> None:
        command = message.get("command")
        identifier = message.get("identifier")
        if not isinstance(identifier, str) or not identifier:
            await send(
                {"type": "error", "error": "A subscription identifier is required."}
            )
            return

        if command == "subscribe":
            await self._subscribe(
                message,
                identifier,
                connection,
                broker,
                subscriptions,
                send,
            )
            return
        if command == "unsubscribe":
            channel = subscriptions.pop(identifier, None)
            if channel is not None:
                await channel.close()
            await send({"type": "unsubscribed", "identifier": identifier})
            return
        if command == "message":
            await self._receive(message, identifier, subscriptions, send)
            return
        await send(
            {
                "type": "error",
                "identifier": identifier,
                "error": f"Unknown channel command {command!r}.",
            }
        )

    async def _subscribe(
        self,
        message: dict[str, Any],
        identifier: str,
        connection: Connection,
        broker: ChannelBroker,
        subscriptions: dict[str, Channel],
        send,
    ) -> None:
        if identifier in subscriptions:
            await send(
                {
                    "type": "error",
                    "identifier": identifier,
                    "error": "That subscription identifier is already active.",
                }
            )
            return

        name = message.get("channel")
        params = message.get("params", {})
        if not isinstance(name, str) or not isinstance(params, Mapping):
            await send(
                {
                    "type": "rejected",
                    "identifier": identifier,
                    "error": "A channel name and object params are required.",
                }
            )
            return

        channel = None
        try:
            channel_class = self._channel(name)
            channel = channel_class(
                connection,
                identifier,
                dict(params),
                broker,
                send,
            )
            subscriptions[identifier] = channel
            await channel.subscribed()
        except Exception as error:
            subscriptions.pop(identifier, None)
            if channel is not None:
                await channel.close()
            logger.exception("Channel subscription failed")
            reason = (
                str(error) if isinstance(error, BingoError) else "Subscription failed."
            )
            await send(
                {
                    "type": "rejected",
                    "identifier": identifier,
                    "error": reason,
                }
            )
            return

        await send({"type": "subscribed", "identifier": identifier})

    async def _receive(
        self,
        message: dict[str, Any],
        identifier: str,
        subscriptions: dict[str, Channel],
        send,
    ) -> None:
        channel = subscriptions.get(identifier)
        data = message.get("data")
        if channel is None:
            await send(
                {
                    "type": "error",
                    "identifier": identifier,
                    "error": "The subscription is not active.",
                }
            )
            return
        if not isinstance(data, Mapping):
            await send(
                {
                    "type": "error",
                    "identifier": identifier,
                    "error": "Channel messages must contain an object as data.",
                }
            )
            return

        try:
            await channel.received(dict(data))
        except BingoValidationError as error:
            await channel._transmit("validation_error", {"errors": error.errors})
        except BingoError as error:
            await channel._transmit("error", {"message": str(error)})
        except Exception:
            logger.exception("Channel message handling failed")
            await channel._transmit("error", {"message": "Channel action failed."})

    def _channel(self, name: str) -> type[Channel]:
        if name in self.channels:
            return self.channels[name]
        channel = _application_channel(self.root, name)
        self.channels[name] = channel
        return channel


async def _receive_command(websocket: WebSocket) -> dict[str, Any]:
    text = await websocket.receive_text()
    maximum = settings.CHANNEL_MAX_MESSAGE_BYTES
    is_valid_maximum = isinstance(maximum, int) and not isinstance(maximum, bool)
    if not is_valid_maximum or maximum < 1:
        raise BingoChannelError("CHANNEL_MAX_MESSAGE_BYTES must be at least 1.")
    if len(text.encode("utf-8")) > maximum:
        raise BingoChannelError(f"Channel messages cannot exceed {maximum} bytes.")
    try:
        message = json.loads(text)
    except ValueError as error:
        raise BingoChannelError("Channel messages must contain valid JSON.") from error
    if not isinstance(message, dict):
        raise BingoChannelError("Channel messages must contain a JSON object.")
    return message


def _application_connection(root: Path) -> type[Connection]:
    module = _import_application_module(root, "application_connection")
    connection = getattr(module, "ApplicationConnection", None)
    is_connection = isinstance(connection, type) and issubclass(connection, Connection)
    if not is_connection:
        raise BingoChannelError(
            "app/channels/application_connection.py must define "
            "ApplicationConnection(Connection)."
        )
    lifecycle = (connection.connect, connection.disconnect)
    if not all(inspect.iscoroutinefunction(method) for method in lifecycle):
        raise BingoChannelError(
            "ApplicationConnection connect and disconnect hooks must be asynchronous."
        )
    return connection


def _application_channel(root: Path, name: str) -> type[Channel]:
    if not CHANNEL_NAME.fullmatch(name):
        raise BingoChannelError(
            f"Invalid channel {name!r}. Expected a name such as ChatChannel."
        )
    module_name = snake_case(name)
    module = _import_application_module(root, module_name)
    channel = getattr(module, name, None)
    is_channel = isinstance(channel, type) and issubclass(channel, Channel)
    if not is_channel:
        raise BingoChannelError(
            f"app/channels/{module_name}.py must define {name}(ApplicationChannel)."
        )
    lifecycle = ("subscribed", "received")
    missing = [
        method
        for method in lifecycle
        if method not in channel.__dict__
        or not inspect.iscoroutinefunction(getattr(channel, method))
    ]
    if missing:
        names = ", ".join(missing)
        raise BingoChannelError(
            f"{name} must define asynchronous channel methods: {names}."
        )
    return channel


def _import_application_module(root: Path, name: str):
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    module_name = f"app.channels.{name}"
    try:
        return importlib.import_module(module_name)
    except Exception as error:
        raise BingoChannelError(
            f"Could not import {module_name}: {type(error).__name__}: {error}"
        ) from error


def _channel_url() -> str:
    url = settings.CHANNEL_URL
    if not isinstance(url, str) or not url:
        raise BingoChannelError("CHANNEL_URL must be configured before using channels.")
    scheme = urlparse(url).scheme.lower()
    if scheme not in {"memory", "postgres", "postgresql", "redis", "rediss"}:
        raise BingoChannelError(
            "CHANNEL_URL supports memory://, Redis, and PostgreSQL URLs."
        )
    return url


def _origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return True

    allowed = settings.CHANNEL_ALLOWED_ORIGINS
    if not isinstance(allowed, list | tuple):
        raise BingoChannelError("CHANNEL_ALLOWED_ORIGINS must be a list of origins.")
    if "*" in allowed or origin in allowed:
        return True

    parsed = urlparse(origin)
    return parsed.netloc == websocket.headers.get("host")
