from __future__ import annotations

import os
import re
import runpy
from pathlib import Path
from typing import Any

from bingo.exceptions import BingoConventionError

DEFAULTS = {
    "APP_NAME": "Bingo",
    "DEBUG": False,
    "SECRET_KEY": "development-only-change-me",
    "DATABASE_URL": None,
    "SERVER_HOST": "127.0.0.1",
    "SERVER_PORT": 8000,
    "SERVER_WORKERS": 1,
    "SERVER_RELOAD": False,
    "PUBLIC_URL": "/public",
    "PUBLIC_DIRECTORY": "public",
    "PUBLIC_CACHE_SECONDS": 86400,
    "TASK_QUEUE_URL": "postgres://postgres@localhost/bingo_tasks",
    "TASK_CONCURRENCY": 10,
    "TASK_DEFAULT_RETRIES": 3,
    "TASK_DEFAULT_TIMEOUT": 60,
    "TASKS_INLINE": False,
    "CHANNEL_URL": "postgres://postgres@localhost/bingo_tasks",
    "CHANNEL_PATH": "/channels",
    "CHANNEL_ALLOWED_ORIGINS": [],
    "CHANNEL_BUFFER_SIZE": 100,
    "CHANNEL_MAX_MESSAGE_BYTES": 65536,
}


class Settings:
    def __init__(self) -> None:
        self._values = dict(DEFAULTS)
        self._root = Path.cwd().resolve()
        self._environment = "development"
        self._loaded = False

    @property
    def root(self) -> Path:
        return self._root

    @property
    def environment(self) -> str:
        return self._environment

    def load(
        self,
        root: str | Path,
        environment: str | None = None,
    ) -> Settings:
        root = Path(root).resolve()
        environment = environment or os.getenv("BINGO_ENV", "development")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", environment):
            raise BingoConventionError(
                f"Invalid Bingo environment {environment!r}. Use a lowercase name "
                "such as development, test, or production."
            )
        if self._loaded and root == self._root and environment == self._environment:
            return self

        values = dict(DEFAULTS)
        settings_directory = root / "config" / "settings"
        if settings_directory.is_dir():
            values.update(self._read(settings_directory / "base.py"))
            values.update(self._read(settings_directory / f"{environment}.py"))

        self._values = values
        self._root = root
        self._environment = environment
        self._loaded = True
        return self

    def __getattr__(self, name: str) -> Any:
        if name in self._values:
            return self._values[name]
        raise BingoConventionError(
            f"Setting {name!r} is not defined for the {self.environment} environment."
        )

    def _read(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise BingoConventionError(
                f"Settings file {path} does not exist. Create it or select another "
                "environment with BINGO_ENV."
            )

        try:
            namespace = runpy.run_path(str(path))
        except Exception as error:
            raise BingoConventionError(
                f"Could not load settings from {path}: {type(error).__name__}: {error}"
            ) from error
        return {
            name: value
            for name, value in namespace.items()
            if name.isupper() and not name.startswith("_")
        }


settings = Settings()
