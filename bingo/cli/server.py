from granian import Granian
from granian.constants import Interfaces
from rich.console import Console

from bingo.cli.helpers import load_application, project_root


def server(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = True,
) -> None:
    root = project_root()
    application = load_application(root)
    console = Console()
    console.print("[bold]Bingo 0.1[/]")
    console.print(f"Application: {type(application).__name__}")
    console.print("Environment: development")
    console.print(f"http://{host}:{port}")
    Granian(
        "config.application:app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,
        working_dir=root,
        static_path_route=["/public"],
        static_path_mount=[root / "public"],
        static_path_expires=0,
        reload=reload,
        reload_paths=[root],
    ).serve()
