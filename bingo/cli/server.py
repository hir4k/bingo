from pathlib import Path

from granian import Granian
from granian.constants import Interfaces
from rich.console import Console

from bingo.cli.helpers import load_application, project_root
from bingo.settings import settings


def server(
    host: str | None = None,
    port: int | None = None,
    workers: int | None = None,
    reload: bool | None = None,
) -> None:
    root = project_root()
    application = load_application(root)
    host = settings.SERVER_HOST if host is None else host
    port = settings.SERVER_PORT if port is None else port
    workers = settings.SERVER_WORKERS if workers is None else workers
    reload = settings.SERVER_RELOAD if reload is None else reload

    public_directory = Path(settings.PUBLIC_DIRECTORY)
    if not public_directory.is_absolute():
        public_directory = root / public_directory

    console = Console()
    console.print("[bold]Bingo 0.2[/]")
    console.print(f"Application: {type(application).__name__}")
    console.print(f"Environment: {settings.environment}")
    console.print(f"http://{host}:{port}")
    Granian(
        "config.application:app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,
        workers=workers,
        working_dir=root,
        static_path_route=[settings.PUBLIC_URL],
        static_path_mount=[public_directory],
        static_path_expires=settings.PUBLIC_CACHE_SECONDS,
        reload=reload,
        reload_paths=[root],
    ).serve()
