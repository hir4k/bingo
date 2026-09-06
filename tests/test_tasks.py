from __future__ import annotations

from pathlib import Path

import pytest

import bingo.tasks as task_runtime
from bingo import BingoTaskError, Task
from bingo.generators import ProjectGenerator, TaskGenerator
from bingo.settings import settings
from bingo.tasks import discover_tasks, run_task_worker


def write_task(root: Path, content: str) -> Path:
    path = root / "app" / "tasks" / "send_welcome_email_task.py"
    path.write_text(content, encoding="utf-8")
    return path


async def test_tasks_run_inline_in_the_test_environment(
    tmp_path: Path,
    clear_generated_modules,
):
    root = ProjectGenerator().generate("journal", tmp_path)
    write_task(
        root,
        """from app.tasks.application_task import ApplicationTask


class SendWelcomeEmailTask(ApplicationTask):
    async def run(self, user_id: int, greeting: str = "Hello"):
        return {"message": f"{greeting} {user_id}"}
""",
    )
    settings.load(root, "test")

    task_class = discover_tasks(root)[0]
    queued = await task_class.enqueue(7)

    assert queued is not None
    assert queued.name == "SendWelcomeEmailTask"
    assert queued.queue == "default"
    assert queued.inline is True
    assert queued.result == {"message": "Hello 7"}
    clear_generated_modules()


async def test_enqueue_hides_saq_and_applies_task_defaults(
    tmp_path: Path,
    monkeypatch,
):
    root = ProjectGenerator().generate("journal", tmp_path)
    settings.load(root, "development")
    captured = {}

    class FakeQueue:
        async def enqueue(self, queued):
            captured["queued"] = queued
            return queued

    async def fake_queue_for(name: str):
        captured["queue"] = name
        return FakeQueue()

    monkeypatch.setattr(task_runtime, "_queue_for", fake_queue_for)

    class DeliverDigestTask(Task):
        queue = "mailers"
        retries = 5
        timeout = 90

        async def run(self, account_id: int):
            return {"account_id": account_id}

    queued = await DeliverDigestTask.enqueue(12)
    internal = captured["queued"]

    assert queued is not None
    assert queued.name == "DeliverDigestTask"
    assert queued.queue == "mailers"
    assert queued.inline is False
    assert captured["queue"] == "mailers"
    assert internal.function == "DeliverDigestTask"
    assert internal.kwargs == {"account_id": 12}
    assert internal.retries == 5
    assert internal.timeout == 90


async def test_task_arguments_must_be_json_compatible(tmp_path: Path):
    root = ProjectGenerator().generate("journal", tmp_path)
    settings.load(root, "test")

    class InvalidPayloadTask(Task):
        async def run(self, value: object):
            return None

    with pytest.raises(BingoTaskError, match="must be JSON-compatible"):
        await InvalidPayloadTask.enqueue(object())


async def test_worker_discovers_only_tasks_for_its_queue(
    tmp_path: Path,
    monkeypatch,
    clear_generated_modules,
):
    root = ProjectGenerator().generate("journal", tmp_path)
    write_task(
        root,
        """from app.tasks.application_task import ApplicationTask


class SendWelcomeEmailTask(ApplicationTask):
    queue = "mailers"

    async def run(self, user_id: int):
        return {"sent": user_id}
""",
    )
    settings.load(root, "development")
    captured = {}

    class FakeQueue:
        async def connect(self):
            captured["connected"] = True

        async def disconnect(self):
            captured["disconnected"] = True

    class FakeWorker:
        def __init__(self, *, queue, functions, concurrency):
            captured["queue"] = queue
            captured["functions"] = functions
            captured["concurrency"] = concurrency

        async def start(self):
            name, function = captured["functions"][0]
            captured["name"] = name
            captured["result"] = await function({}, user_id=4)

    fake_queue = FakeQueue()
    monkeypatch.setattr(task_runtime, "_new_queue", lambda _url, _name: fake_queue)
    monkeypatch.setattr(task_runtime, "Worker", FakeWorker)

    await run_task_worker(root, "mailers", concurrency=2)

    assert captured == {
        "queue": fake_queue,
        "functions": captured["functions"],
        "concurrency": 2,
        "connected": True,
        "name": "SendWelcomeEmailTask",
        "result": {"sent": 4},
        "disconnected": True,
    }
    clear_generated_modules()


def test_task_generator_uses_the_filename_as_the_class_convention(tmp_path: Path):
    root = ProjectGenerator().generate("journal", tmp_path)

    path = TaskGenerator(root).generate("SendWelcomeEmail")

    assert path.name == "send_welcome_email_task.py"
    assert "class SendWelcomeEmailTask(ApplicationTask)" in path.read_text()
