from rich.console import Console
from rich.table import Table

from bingo.cli.helpers import load_application, project_root


def routes() -> None:
    application = load_application(project_root())
    table = Table("METHOD", "PATH", "CONTROLLER")
    for route in application.router.definitions:
        table.add_row(route.method, route.path, route.target)
    Console().print(table)
