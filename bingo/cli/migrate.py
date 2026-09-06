import asyncio

from rich.console import Console

from bingo.cli.helpers import load_application, project_root
from bingo.db import MigrationRunner


def migrate() -> None:
    root = project_root()
    load_application(root)
    names = asyncio.run(MigrationRunner(root / "db" / "migrations").migrate())
    console = Console()
    if not names:
        console.print("[dim]Database is already up to date.[/]")
    for name in names:
        console.print(f"[green]migrated[/] {name}")


def rollback() -> None:
    root = project_root()
    load_application(root)
    name = asyncio.run(MigrationRunner(root / "db" / "migrations").rollback())
    Console().print(
        f"[yellow]rolled back[/] {name}" if name else "Nothing to roll back."
    )
