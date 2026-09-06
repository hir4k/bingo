from __future__ import annotations

import re
from pathlib import Path

from bingo.exceptions import BingoConventionError


def class_name(value: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_\-\s]+", value) if part)


class ProjectGenerator:
    DIRECTORIES = (
        "app/controllers",
        "app/models",
        "app/validators",
        "app/views/layouts",
        "config",
        "db/migrations",
        "public",
        "tests",
    )

    def generate(self, name: str, destination: str | Path = ".") -> Path:
        destination = Path(destination).resolve()
        uses_existing_directory = name == "."
        if uses_existing_directory:
            root = destination
            name = root.name
        else:
            root = destination / name

        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            if uses_existing_directory:
                raise BingoConventionError(
                    f"Cannot derive a Bingo project name from {root.name!r}. "
                    "Directory names must start with a lowercase letter and contain "
                    "only lowercase letters, numbers, and underscores."
                )
            raise BingoConventionError(
                "Project names must start with a lowercase letter and contain only "
                "lowercase letters, numbers, and underscores."
            )

        if uses_existing_directory and not root.is_dir():
            raise BingoConventionError(
                f"Cannot initialize {root}: the directory does not exist."
            )
        if not uses_existing_directory and root.exists():
            raise BingoConventionError(
                f"Cannot create {root}: that path already exists. Choose a new name "
                "or run `bingo new .` from inside an existing directory."
            )

        app_class = f"{class_name(name)}Application"
        files = self._files(name, app_class)
        conflicts = [
            relative_path for relative_path in files if (root / relative_path).exists()
        ]
        blocked_directories = [
            directory
            for directory in self.DIRECTORIES
            if (root / directory).exists() and not (root / directory).is_dir()
        ]
        conflicts.extend(blocked_directories)
        if conflicts:
            paths = ", ".join(sorted(conflicts))
            raise BingoConventionError(
                f"Cannot initialize {root} without overwriting existing paths: "
                f"{paths}. Move those paths and run `bingo new .` again."
            )

        for directory in self.DIRECTORIES:
            (root / directory).mkdir(parents=True, exist_ok=True)

        for relative_path, content in files.items():
            (root / relative_path).write_text(content, encoding="utf-8")
        return root

    def _files(self, name: str, app_class: str) -> dict[str, str]:
        return {
            "app/__init__.py": "",
            "app/controllers/__init__.py": "",
            "app/controllers/application_controller.py": (
                "from bingo import Controller\n\n\n"
                "class ApplicationController(Controller):\n"
                "    pass\n"
            ),
            "app/models/__init__.py": "",
            "app/validators/__init__.py": "",
            "config/__init__.py": "",
            "config/database.py": (
                "import os\n\n\n"
                "DATABASE_URL = os.getenv(\n"
                '    "DATABASE_URL",\n'
                '    "sqlite+aiosqlite:///db/development.sqlite3",\n'
                ")\n"
            ),
            "config/routes.py": "from bingo import Router\n\n\nroutes = Router()\n",
            "config/application.py": (
                "from pathlib import Path\n\n"
                "from bingo import Application\n\n"
                "from config.database import DATABASE_URL\n"
                "from config.routes import routes\n\n\n"
                f"class {app_class}(Application):\n"
                "    debug = True\n\n\n"
                "ROOT = Path(__file__).resolve().parent.parent\n"
                f"app = {app_class}(\n"
                "    routes,\n"
                "    root_path=ROOT,\n"
                "    database_url=DATABASE_URL,\n"
                ")\n"
            ),
            "app/views/layouts/application.html": LAYOUT,
            ".env.example": "DATABASE_URL=sqlite+aiosqlite:///db/development.sqlite3\n",
            ".gitignore": "__pycache__/\n*.py[cod]\n.venv/\n.env\ndb/*.sqlite3\n",
            "pyproject.toml": PROJECT_TOML.format(name=name),
            "README.md": PROJECT_README.format(name=name),
            "BINGO.md": BINGO_RULES,
        }


LAYOUT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Bingo</title>
</head>
<body>
{% block content %}{% endblock %}
</body>
</html>
"""

PROJECT_TOML = """[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["bingo-framework>=0.1"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
"""

PROJECT_README = """# {name}

A Bingo application.

```bash
bingo migrate
bingo server
```

Resource HTML uses unsuffixed URLs. Add `.json` to request the colocated `.bjson`
representation of the same controller action.
"""

BINGO_RULES = """# Bingo Project Rules

This application uses Bingo. Do not invent alternative architecture.

## Controllers

Controllers are classes in `app/controllers/`. Resource actions are only `index`,
`show`, `new`, `create`, `edit`, `update`, and `destroy`. Do not use function
controllers or route decorators.

## Models and validation

Models inherit from Bingo `Model` and live in `app/models/`. Request validators
inherit from Bingo `Validator` and live in `app/validators/`. Do not put request
validation in models or create application Pydantic schemas. Call `validate()`
once in the controller; it returns cleaned data or lets Bingo render a 422 error
for the current interface.

## Routes and views

All routes live in `config/routes.py`. Views live under `app/views/`.

HTML URLs have no format suffix and use Jinja `.html` views. JSON URLs end in
`.json` and use restricted-expression `.bjson` views. An extensionless
`self.render("posts/show")` follows the request format. Views only represent
prepared values; they never query or modify the database.

Pass validators to HTML form views as `validator`. Iterate fields only through
`form(validator)`; field controls, submitted values, and errors come from the
validator rules. On HTML validation failure, Bingo re-runs `new` or `edit` and
exposes the invalid validator as `self.validation`.

## Controller lifecycle

Bingo calls the async `before_action` method before every controller action.
Return `None` to continue or a response to stop dispatch. Use application-owned
base controllers for shared action policy. Do not create string middleware lists.

## Database and architecture

Use Bingo models and migrations, not SQLAlchemy directly. Prefer framework
conventions over custom abstractions. Controllers coordinate workflows and models
hold reusable entity behavior. Do not introduce services, presenters, serializers,
or separate API controllers. After changes, run `bingo inspect`.
"""
