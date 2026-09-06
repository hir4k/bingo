import uvicorn
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
    uvicorn.run(
        "config.application:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(root)],
    )
