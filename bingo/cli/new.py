from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from bingo.generators import ProjectGenerator


def new(
    name: Annotated[
        str,
        typer.Argument(
            help="New directory name, or . to initialize the current directory."
        ),
    ],
    destination: Annotated[Path, typer.Option("--destination", "-d")] = Path("."),
):
    root = ProjectGenerator().generate(name, destination)
    Console().print(f"[green]Created Bingo application:[/] {root}")
