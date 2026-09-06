from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
from functools import wraps
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from bingo.channels import close_channel_brokers
from bingo.cli.generate import generate_app
from bingo.cli.helpers import load_application, project_root
from bingo.cli.inspect import inspect_project
from bingo.cli.migrate import migrate, rollback
from bingo.cli.routes import routes
from bingo.cli.server import server
from bingo.cli.worker import worker
from bingo.exceptions import BingoConventionError, BingoError
from bingo.settings import settings
from bingo.tasks import close_task_queues

BUILT_IN_COMMANDS = {
    "generate",
    "inspect",
    "migrate",
    "rollback",
    "routes",
    "server",
    "worker",
}


class BaseCommand:
    help = ""

    def __init__(self) -> None:
        self.console = Console()

    async def handle(self) -> None:
        raise NotImplementedError


def build_management_app(root: str | Path | None = None) -> typer.Typer:
    root = Path(root).resolve() if root else project_root()
    settings.load(root)

    app = typer.Typer(
        name="manage.py",
        help=f"Manage the {settings.APP_NAME} Bingo application.",
        no_args_is_help=True,
    )
    app.command("server")(server)
    app.command("migrate")(migrate)
    app.command("rollback")(rollback)
    app.command("routes")(routes)
    app.command("inspect")(inspect_project)
    app.command("worker")(worker)
    app.add_typer(generate_app, name="generate")

    for path in _command_paths(root):
        command = _load_command(root, path)
        callback = _command_callback(root, command)
        app.command(path.stem, help=command.help or None)(callback)
    return app


def manage() -> int | None:
    try:
        build_management_app()()
    except BingoError as error:
        Console(stderr=True).print(f"[bold red]{type(error).__name__}[/]\n\n{error}")
        return 1
    return None


def _command_paths(root: Path) -> list[Path]:
    directory = root / "app" / "commands"
    if not directory.is_dir():
        return []

    paths = []
    for path in sorted(directory.glob("*.py")):
        if path.name == "__init__.py":
            continue
        if not path.stem.isidentifier() or path.stem.startswith("_"):
            raise BingoConventionError(
                f"Invalid command filename {path.name!r}. Use a Python identifier "
                "such as publish_posts.py."
            )
        if path.stem in BUILT_IN_COMMANDS:
            raise BingoConventionError(
                f"Command {path.stem!r} conflicts with a built-in Bingo command. "
                "Choose another filename."
            )
        paths.append(path)
    return paths


def _load_command(root: Path, path: Path) -> BaseCommand:
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    module_name = f"app.commands.{path.stem}"
    try:
        module = importlib.import_module(module_name)
    except Exception as error:
        raise BingoConventionError(
            f"Could not import command {path.stem!r}: {type(error).__name__}: {error}"
        ) from error

    command_class = getattr(module, "Command", None)
    is_command = isinstance(command_class, type) and issubclass(
        command_class, BaseCommand
    )
    if not is_command:
        raise BingoConventionError(f"{path} must define class Command(BaseCommand).")
    declares_handle = "handle" in command_class.__dict__
    if not declares_handle or not inspect.iscoroutinefunction(command_class.handle):
        raise BingoConventionError(f"{path} must define async def handle(self, ...).")
    return command_class()


def _command_callback(root: Path, command: BaseCommand):
    @wraps(command.handle)
    def callback(*args: Any, **kwargs: Any):
        load_application(root)
        return asyncio.run(_run_command(command, args, kwargs))

    callback.__signature__ = inspect.signature(command.handle, eval_str=True)
    return callback


async def _run_command(
    command: BaseCommand,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
):
    try:
        return await command.handle(*args, **kwargs)
    finally:
        await close_task_queues()
        await close_channel_brokers()
