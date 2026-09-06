import typer
from rich.console import Console

from bingo.cli.helpers import project_root
from bingo.conventions import ConventionInspector


def inspect_project() -> None:
    violations = ConventionInspector(project_root()).inspect()
    console = Console()
    if not violations:
        console.print("[green]All Bingo conventions pass.[/]")
        return
    for violation in violations:
        console.print(str(violation))
        console.print()
    raise typer.Exit(code=1)
