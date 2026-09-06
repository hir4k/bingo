import typer
from rich.console import Console

from bingo.cli.generate import generate_app
from bingo.cli.inspect import inspect_project
from bingo.cli.migrate import migrate, rollback
from bingo.cli.new import new
from bingo.cli.routes import routes
from bingo.cli.server import server
from bingo.exceptions import BingoError

app = typer.Typer(
    name="bingo",
    help="The opinionated Python web framework for the AI era.",
    no_args_is_help=True,
)
app.command("new")(new)
app.command("server")(server)
app.command("migrate")(migrate)
app.command("rollback")(rollback)
app.command("routes")(routes)
app.command("inspect")(inspect_project)
app.add_typer(generate_app, name="generate")


def main() -> int | None:
    try:
        app()
    except BingoError as error:
        Console(stderr=True).print(f"[bold red]{type(error).__name__}[/]\n\n{error}")
        return 1
    return None


if __name__ == "__main__":
    raise SystemExit(main())
