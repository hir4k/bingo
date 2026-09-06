from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4
from weakref import WeakKeyDictionary

from saq import Queue
from saq.job import Job
from saq.worker import Worker

from bingo.exceptions import BingoConventionError, BingoTaskError
from bingo.settings import settings

QUEUE_NAME = re.compile(r"[a-z][a-z0-9_]*")
SUPPORTED_SCHEMES = {"postgres", "postgresql", "redis", "rediss"}


@dataclass(frozen=True)
class QueuedTask:
    id: str
    name: str
    queue: str
    inline: bool = False
    result: Any = None


class Task:
    queue = "default"
    retries: int | None = None
    timeout: int | None = None
    retry_delay = 0.0
    retry_backoff: bool | float = True

    async def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    @classmethod
    async def enqueue(cls, *args: Any, **kwargs: Any) -> QueuedTask | None:
        cls._validate_definition()
        payload = cls._payload(args, kwargs)
        _ensure_json(payload, f"Arguments for {cls.__name__}")

        if settings.TASKS_INLINE:
            result = await cls().run(**payload)
            _ensure_json(result, f"Result from {cls.__name__}")
            return QueuedTask(
                id=uuid4().hex,
                name=cls.__name__,
                queue=cls.queue,
                inline=True,
                result=result,
            )

        queue = await _queue_for(cls.queue)
        queued = await queue.enqueue(cls._saq_job(payload))
        if queued is None:
            return None
        return QueuedTask(
            id=queued.key,
            name=cls.__name__,
            queue=cls.queue,
        )

    @classmethod
    def _payload(cls, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
        signature = inspect.signature(cls.run)
        try:
            bound = signature.bind(None, *args, **kwargs)
        except TypeError as error:
            raise BingoTaskError(f"Cannot enqueue {cls.__name__}: {error}") from error
        bound.apply_defaults()
        return {
            name: value for name, value in bound.arguments.items() if name != "self"
        }

    @classmethod
    def _saq_job(cls, payload: dict[str, Any]) -> Job:
        retries = cls.retries
        if retries is None:
            retries = settings.TASK_DEFAULT_RETRIES
        _validate_non_negative_integer(retries, "TASK_DEFAULT_RETRIES")

        timeout = cls.timeout
        if timeout is None:
            timeout = settings.TASK_DEFAULT_TIMEOUT
        _validate_non_negative_integer(timeout, "TASK_DEFAULT_TIMEOUT")

        return Job(
            function=cls.__name__,
            kwargs=payload,
            retries=retries,
            timeout=timeout,
            retry_delay=cls.retry_delay,
            retry_backoff=cls.retry_backoff,
        )

    @classmethod
    def _validate_definition(cls) -> None:
        if not inspect.iscoroutinefunction(cls.run):
            raise BingoConventionError(
                f"{cls.__name__}.run must be declared with async def."
            )
        parameters = list(inspect.signature(cls.run).parameters.values())
        has_variable_arguments = any(
            parameter.kind
            in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
            for parameter in parameters
        )
        if has_variable_arguments:
            raise BingoConventionError(
                f"{cls.__name__}.run must declare explicit task arguments."
            )
        task_parameters = [
            parameter for parameter in parameters if parameter.name != "self"
        ]
        has_positional_only = any(
            parameter.kind == inspect.Parameter.POSITIONAL_ONLY
            for parameter in task_parameters
        )
        if has_positional_only:
            raise BingoConventionError(
                f"{cls.__name__}.run cannot use positional-only arguments."
            )
        untyped = [
            parameter.name
            for parameter in task_parameters
            if parameter.annotation is inspect.Parameter.empty
        ]
        if untyped:
            names = ", ".join(untyped)
            raise BingoConventionError(
                f"{cls.__name__}.run arguments need type annotations: {names}."
            )
        _validate_queue_name(cls.queue)
        _validate_task_options(cls)


_queues: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple[str, str], Queue]] = (
    WeakKeyDictionary()
)
_queue_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    WeakKeyDictionary()
)


async def _queue_for(name: str) -> Queue:
    _validate_queue_name(name)
    url = _task_queue_url()
    loop = asyncio.get_running_loop()
    queues = _queues.setdefault(loop, {})
    key = (url, name)
    if key in queues:
        return queues[key]

    lock = _queue_locks.setdefault(loop, asyncio.Lock())
    async with lock:
        if key in queues:
            return queues[key]

        queue = _new_queue(url, name)
        await queue.connect()
        queues[key] = queue
        return queue


def _new_queue(url: str, name: str) -> Queue:
    return Queue.from_url(url, name=name)


def _task_queue_url() -> str:
    url = settings.TASK_QUEUE_URL
    if not isinstance(url, str) or not url:
        raise BingoTaskError(
            "TASK_QUEUE_URL must be a Redis or PostgreSQL URL before tasks can be "
            "enqueued."
        )

    scheme = urlparse(url).scheme.lower()
    if scheme not in SUPPORTED_SCHEMES:
        raise BingoTaskError(
            "TASK_QUEUE_URL supports Redis and PostgreSQL. Use a redis://, "
            "rediss://, postgres://, or postgresql:// URL."
        )
    return url


def _validate_queue_name(name: Any) -> None:
    is_valid = isinstance(name, str) and QUEUE_NAME.fullmatch(name)
    if is_valid:
        return
    raise BingoConventionError(
        f"Invalid task queue {name!r}. Use a lowercase name such as default or mailers."
    )


def _validate_task_options(task_class: type[Task]) -> None:
    for name in ("retries", "timeout"):
        value = getattr(task_class, name)
        if value is None:
            continue
        is_non_negative_integer = isinstance(value, int) and not isinstance(value, bool)
        if is_non_negative_integer and value >= 0:
            continue
        raise BingoConventionError(
            f"{task_class.__name__}.{name} must be a non-negative integer."
        )

    retry_delay = task_class.retry_delay
    is_number = isinstance(retry_delay, int | float) and not isinstance(
        retry_delay, bool
    )
    if not is_number or retry_delay < 0:
        raise BingoConventionError(
            f"{task_class.__name__}.retry_delay must be a non-negative number."
        )

    retry_backoff = task_class.retry_backoff
    is_backoff = isinstance(retry_backoff, bool) or (
        isinstance(retry_backoff, int | float) and retry_backoff > 0
    )
    if not is_backoff:
        raise BingoConventionError(
            f"{task_class.__name__}.retry_backoff must be true, false, or a "
            "positive maximum delay."
        )


def _validate_non_negative_integer(value: Any, setting_name: str) -> None:
    is_integer = isinstance(value, int) and not isinstance(value, bool)
    if is_integer and value >= 0:
        return
    raise BingoTaskError(f"{setting_name} must be a non-negative integer.")


def _ensure_json(value: Any, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise BingoTaskError(
            f"{label} must be JSON-compatible: {type(error).__name__}: {error}"
        ) from error


def discover_tasks(root: str | Path) -> list[type[Task]]:
    root = Path(root).resolve()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    directory = root / "app" / "tasks"
    if not directory.is_dir():
        raise BingoConventionError(f"Task directory {directory} does not exist.")

    discovered = []
    for path in sorted(directory.glob("*_task.py")):
        if path.name == "application_task.py":
            continue
        discovered.append(_load_task(path))
    return discovered


def _load_task(path: Path) -> type[Task]:
    expected_class = _task_class_name(path.stem)
    module_name = f"app.tasks.{path.stem}"
    try:
        module = importlib.import_module(module_name)
    except Exception as error:
        raise BingoConventionError(
            f"Could not import task {path.stem!r}: {type(error).__name__}: {error}"
        ) from error

    task_class = getattr(module, expected_class, None)
    is_task = isinstance(task_class, type) and issubclass(task_class, Task)
    if not is_task:
        raise BingoConventionError(
            f"{path} must define class {expected_class}(ApplicationTask)."
        )
    if "run" not in task_class.__dict__:
        raise BingoConventionError(f"{path} must define async def run(self, ...).")
    task_class._validate_definition()
    return task_class


def _task_class_name(stem: str) -> str:
    return "".join(part.capitalize() for part in stem.split("_") if part)


async def run_task_worker(
    root: str | Path,
    queue_name: str = "default",
    concurrency: int | None = None,
) -> None:
    _validate_queue_name(queue_name)
    concurrency = settings.TASK_CONCURRENCY if concurrency is None else concurrency
    is_positive_integer = isinstance(concurrency, int) and not isinstance(
        concurrency, bool
    )
    if not is_positive_integer or concurrency < 1:
        raise BingoTaskError("Task worker concurrency must be at least 1.")

    registered = [task for task in discover_tasks(root) if task.queue == queue_name]
    if not registered:
        raise BingoTaskError(f"No application tasks use the {queue_name!r} queue.")

    queue = _new_queue(_task_queue_url(), queue_name)
    functions = [(task.__name__, _task_function(task)) for task in registered]
    worker = Worker(queue=queue, functions=functions, concurrency=concurrency)
    await queue.connect()
    try:
        await worker.start()
    finally:
        await queue.disconnect()
        from bingo.channels import close_channel_brokers

        await close_channel_brokers()


def _task_function(task_class: type[Task]):
    async def execute(_context: dict[str, Any], **payload: Any) -> Any:
        result = await task_class().run(**payload)
        _ensure_json(result, f"Result from {task_class.__name__}")
        return result

    return execute


async def close_task_queues() -> None:
    loop = asyncio.get_running_loop()
    queues = _queues.pop(loop, {})
    _queue_locks.pop(loop, None)
    if not queues:
        return
    await asyncio.gather(
        *(queue.disconnect() for queue in queues.values()),
        return_exceptions=True,
    )
