from __future__ import annotations

import importlib
import sys
from pathlib import Path

from bingo.exceptions import BingoConventionError
from bingo.settings import settings


def project_root() -> Path:
    current = Path.cwd().resolve()
    candidates = [current, *current.parents]
    command = Path(sys.argv[0]).resolve()
    if command.name == "manage.py":
        script_directory = command.parent
        candidates.extend((script_directory, *script_directory.parents))

    for path in dict.fromkeys(candidates):
        if (path / "config" / "application.py").is_file():
            return path
    raise BingoConventionError(
        "This command must run inside a Bingo project. Expected "
        "config/application.py in this directory or one of its parents."
    )


def load_application(root: Path):
    settings.load(root)
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    module = importlib.import_module("config.application")
    app = getattr(module, "app", None)
    if app is None:
        raise BingoConventionError(
            "config/application.py must expose the Bingo application as `app`."
        )
    return app
