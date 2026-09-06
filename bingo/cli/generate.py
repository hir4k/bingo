from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from bingo.cli.helpers import project_root
from bingo.generators.resource import ResourceGenerator, parse_fields

generate_app = typer.Typer(help="Generate conventional Bingo application code.")


def _show(paths: list[Path]) -> None:
    console = Console()
    for path in paths:
        console.print(f"[green]create[/] {path}")


@generate_app.command("resource")
def resource(
    name: str,
    fields: Annotated[list[str] | None, typer.Argument()] = None,
):
    generator = ResourceGenerator(project_root())
    _show(generator.generate(name, fields or []))


@generate_app.command("model")
def model(
    name: str,
    fields: Annotated[list[str] | None, typer.Argument()] = None,
):
    generator = ResourceGenerator(project_root())
    _show(generator.generate_model(name, fields or []))


@generate_app.command("controller")
def controller(name: str):
    generator = ResourceGenerator(project_root())
    _show(generator.generate_controller(name))


@generate_app.command("validator")
def validator(
    name: str,
    fields: Annotated[list[str] | None, typer.Argument()] = None,
):
    generator = ResourceGenerator(project_root())
    _show(generator.generate_validator(name, parse_fields(fields or [])))
