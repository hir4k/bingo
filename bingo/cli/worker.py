from __future__ import annotations

import asyncio

from rich.console import Console

from bingo.cli.helpers import load_application, project_root
from bingo.settings import settings
from bingo.tasks import run_task_worker


def worker(
    queue: str = "default",
    concurrency: int | None = None,
) -> None:
    root = project_root()
    load_application(root)
    concurrency = settings.TASK_CONCURRENCY if concurrency is None else concurrency

    console = Console()
    console.print("[bold]Bingo task worker[/]")
    console.print(f"Environment: {settings.environment}")
    console.print(f"Queue: {queue}")
    console.print(f"Concurrency: {concurrency}")
    asyncio.run(run_task_worker(root, queue, concurrency))
