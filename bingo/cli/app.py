import typer
from rich.console import Console

from bingo.cli.new import new
from bingo.exceptions import BingoError

app = typer.Typer(
    name="bingo",
    help="The opinionated Python web framework for the AI era.",
    no_args_is_help=True,
)


@app.callback()
def bootstrap() -> None:
    """Keep project creation under the explicit `bingo new` command."""


app.command("new")(new)


def main() -> int | None:
    try:
        app()
    except BingoError as error:
        Console(stderr=True).print(f"[bold red]{type(error).__name__}[/]\n\n{error}")
        return 1
    return None


if __name__ == "__main__":
    raise SystemExit(main())
