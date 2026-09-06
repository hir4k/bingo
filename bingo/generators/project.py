from __future__ import annotations

import re
from pathlib import Path

from bingo.exceptions import BingoConventionError


def class_name(value: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_\-\s]+", value) if part)


class ProjectGenerator:
    DIRECTORIES = (
        "app/channels",
        "app/commands",
        "app/controllers",
        "app/models",
        "app/tasks",
        "app/validators",
        "app/views/layouts",
        "app/views/welcome",
        "config",
        "config/settings",
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
            "app/channels/__init__.py": "",
            "app/channels/application_channel.py": APPLICATION_CHANNEL,
            "app/channels/application_connection.py": APPLICATION_CONNECTION,
            "app/commands/__init__.py": "",
            "app/controllers/__init__.py": "",
            "app/controllers/application_controller.py": (
                "from bingo import Controller\n\n\n"
                "class ApplicationController(Controller):\n"
                "    pass\n"
            ),
            "app/controllers/welcome_controller.py": WELCOME_CONTROLLER,
            "app/models/__init__.py": "",
            "app/tasks/__init__.py": "",
            "app/tasks/application_task.py": APPLICATION_TASK,
            "app/validators/__init__.py": "",
            "config/__init__.py": "",
            "config/settings/__init__.py": "",
            "config/settings/base.py": SETTINGS_BASE.format(name=name),
            "config/settings/development.py": SETTINGS_DEVELOPMENT.format(name=name),
            "config/settings/test.py": SETTINGS_TEST,
            "config/settings/production.py": SETTINGS_PRODUCTION,
            "config/routes.py": (
                "from bingo import Router\n\n\n"
                "routes = Router()\n\n"
                'routes.get("/", "WelcomeController.index")\n'
            ),
            "config/application.py": (
                "from pathlib import Path\n\n"
                "from bingo import Application\n\n"
                "from config.routes import routes\n\n\n"
                f"class {app_class}(Application):\n"
                "    pass\n\n\n"
                "ROOT = Path(__file__).resolve().parent.parent\n"
                f"app = {app_class}(\n"
                "    routes,\n"
                "    root_path=ROOT,\n"
                ")\n"
            ),
            "app/views/layouts/application.html": LAYOUT,
            "app/views/welcome/index.html": WELCOME_VIEW,
            "public/application.css": APPLICATION_CSS,
            "manage.py": MANAGE,
            ".env.example": (
                "BINGO_ENV=development\n"
                "DATABASE_URL=sqlite+aiosqlite:///db/development.sqlite3\n"
                f"TASK_QUEUE_URL=postgres://postgres@localhost/{name}_tasks\n"
            ),
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
    <link rel="stylesheet" href="/public/application.css">
</head>
<body>
{% block content %}{% endblock %}
</body>
</html>
"""

WELCOME_CONTROLLER = """from app.controllers.application_controller import ApplicationController


class WelcomeController(ApplicationController):
    async def index(self):
        return self.render("welcome/index.html")
"""

WELCOME_VIEW = """{% extends "layouts/application.html" %}
{% block content %}
<main class="welcome">
    <p class="eyebrow">Bingo</p>
    <h1>Your application is running.</h1>
    <p class="intro">
        You have one conventional path from an idea to HTML and JSON.
    </p>
    <section>
        <p>Build your first resource:</p>
        <code>python manage.py generate resource Post title:string body:text</code>
        <code>python manage.py migrate</code>
        <p>Then open <a href="/posts">/posts</a>.</p>
    </section>
</main>
{% endblock %}
"""

APPLICATION_CSS = """:root {
    color-scheme: light;
    font-family: Inter, ui-sans-serif, system-ui, sans-serif;
    color: #17202a;
    background: #f6f4ef;
}

body {
    margin: 0;
}

.welcome {
    width: min(42rem, calc(100% - 3rem));
    margin: 16vh auto 4rem;
}

.eyebrow {
    margin: 0 0 1rem;
    color: #d94f35;
    font-weight: 800;
    letter-spacing: 0.14em;
    text-transform: uppercase;
}

h1 {
    margin: 0;
    font-size: clamp(2.6rem, 8vw, 5.6rem);
    line-height: 0.95;
    letter-spacing: -0.055em;
}

.intro {
    max-width: 34rem;
    margin: 1.5rem 0 3rem;
    color: #53606c;
    font-size: 1.2rem;
    line-height: 1.6;
}

section {
    padding: 1.5rem;
    border: 1px solid #d9d4c8;
    border-radius: 0.75rem;
    background: #fff;
    box-shadow: 0 1rem 3rem rgb(23 32 42 / 8%);
}

section p {
    margin: 0 0 1rem;
}

section p:last-child {
    margin: 1rem 0 0;
}

code {
    display: block;
    overflow-x: auto;
    padding: 0.75rem 1rem;
    color: #f8f7f2;
    background: #17202a;
}

code + code {
    padding-top: 0;
}

a {
    color: #b83722;
}
"""

MANAGE = """from bingo import manage

if __name__ == "__main__":
    raise SystemExit(manage())
"""

APPLICATION_TASK = """from bingo import Task


class ApplicationTask(Task):
    pass
"""

APPLICATION_CONNECTION = """from bingo import Connection


class ApplicationConnection(Connection):
    pass
"""

APPLICATION_CHANNEL = """from bingo import Channel


class ApplicationChannel(Channel):
    pass
"""

SETTINGS_BASE = """APP_NAME = "{name}"
DEBUG = False
SECRET_KEY = "development-only-change-me"
DATABASE_URL = None

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
SERVER_WORKERS = 1
SERVER_RELOAD = False

PUBLIC_URL = "/public"
PUBLIC_DIRECTORY = "public"
PUBLIC_CACHE_SECONDS = 86400

TASK_QUEUE_URL = "postgres://postgres@localhost/{name}_tasks"
TASK_CONCURRENCY = 10
TASK_DEFAULT_RETRIES = 3
TASK_DEFAULT_TIMEOUT = 60
TASKS_INLINE = False

CHANNEL_URL = TASK_QUEUE_URL
CHANNEL_PATH = "/channels"
CHANNEL_ALLOWED_ORIGINS = []
CHANNEL_BUFFER_SIZE = 100
CHANNEL_MAX_MESSAGE_BYTES = 65536
"""

SETTINGS_DEVELOPMENT = """import os

DEBUG = True
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///db/development.sqlite3",
)
TASK_QUEUE_URL = os.getenv(
    "TASK_QUEUE_URL",
    "postgres://postgres@localhost/{name}_tasks",
)
CHANNEL_URL = os.getenv("CHANNEL_URL", TASK_QUEUE_URL)
SERVER_RELOAD = True
PUBLIC_CACHE_SECONDS = 0
"""

SETTINGS_TEST = """DEBUG = True
DATABASE_URL = "sqlite+aiosqlite:///:memory:"
PUBLIC_CACHE_SECONDS = 0
TASKS_INLINE = True
CHANNEL_URL = "memory://"
"""

SETTINGS_PRODUCTION = """import os

SECRET_KEY = os.environ["SECRET_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]
SERVER_HOST = "0.0.0.0"
SERVER_WORKERS = int(os.getenv("SERVER_WORKERS", "4"))
TASK_QUEUE_URL = os.environ["TASK_QUEUE_URL"]
CHANNEL_URL = os.getenv("CHANNEL_URL", TASK_QUEUE_URL)
"""

PROJECT_TOML = """[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["bingo-framework>=0.2"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
"""

PROJECT_README = """# {name}

A Bingo application.

```bash
python manage.py migrate
python manage.py server
```

Open `http://127.0.0.1:8000` to see the generated welcome page. Granian serves
files in `public/` at `/public` automatically.

Set `BINGO_ENV` to load `config/settings/base.py` followed by the matching
environment file. The default environment is `development`.

Resource HTML uses unsuffixed URLs. Add `.json` to request the colocated `.bjson`
representation of the same controller action.

Background tasks live in `app/tasks/`. Generate one with
`python manage.py generate task SendWelcomeEmail`, enqueue it through its class,
and process it with `python manage.py worker`.

Realtime channels live in `app/channels/` and use the automatic `/channels`
WebSocket endpoint. Generate one with `python manage.py generate channel Chat
message`, then load `/channels.js` in the browser.
"""

BINGO_RULES = """# Bingo Project Rules

This application uses Bingo. Do not invent alternative architecture.

## Settings and commands

Shared settings live in `config/settings/base.py`; environment overrides live in
`config/settings/development.py`, `test.py`, and `production.py`. Bingo loads
uppercase names from base and then the environment selected by `BINGO_ENV`, which
defaults to `development`. Access values through `from bingo import settings`.
Do not add another configuration system.

Inside this project, run framework commands through `python manage.py`. Custom
commands live directly in `app/commands/`. A file such as `publish_posts.py`
defines exactly one `Command(BaseCommand)` with one async `handle()` method. Its
filename is the command name. Required parameters are positional; parameters with
defaults are options; booleans are flags.

## Background tasks

Tasks live directly in `app/tasks/`. Each file defines one matching task class:
`send_welcome_email_task.py` defines `SendWelcomeEmailTask(ApplicationTask)` with
one async `run()` method. Task arguments are typed and JSON-compatible. Pass model
IDs, not model instances. Enqueue work only through
`await SendWelcomeEmailTask.enqueue(...)`.

Run the default queue with `python manage.py worker`. A task can declare
`queue = "mailers"`; process it with `python manage.py worker --queue mailers`.
PostgreSQL is the default backend, and Redis is also accepted through
`TASK_QUEUE_URL`. Do not import SAQ in application code. Test settings execute
tasks inline through `TASKS_INLINE = True`.

## Realtime channels

Channels live directly in `app/channels/`. `chat_channel.py` defines exactly one
`ChatChannel(ApplicationChannel)` with async `subscribed()` and `received()`
methods. Register streams with `await self.stream(key)`. Do not add channel routes;
Bingo provides the single `/channels` WebSocket endpoint and `/channels.js`
browser client.

Broadcast with `await ChatChannel.broadcast(key, "message", **context)`. Bingo
renders `app/views/channels/chat/message.bjson` and sends the result as the
`message` event. Do not send models or hand-built serialized payloads. Incoming
messages use ordinary Bingo validators; validation failures become a
`validation_error` channel event.

Shared connection setup belongs only in `ApplicationConnection.connect()`, which
may attach application-defined state or call `self.reject()`. The framework does
not provide a user model. `CHANNEL_URL` accepts PostgreSQL or Redis; tests use
`memory://`. Broadcasts are ephemeral, so persistent data belongs in models.

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

Declare resources as `routes.resources("/posts")`; Bingo infers
`app/controllers/posts_controller.py` and `PostsController`. Custom routes use an
explicit HTTP verb and a string target such as
`routes.get("/posts/published", "PostsController.published")`. Do not import
controllers into the route file.

Use `with routes.group("/admin"):` when the URL and controller directory share a
group. The leading slash is required. Inside the block, `/posts` resolves to
`app/controllers/admin/posts_controller.py`, and resource views live in
`app/views/admin/posts/`. Nested group blocks map to nested URL, controller,
and view directories. Keep the class name `PostsController`; the directory owns
the group.

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
or separate API controllers.

Run the application with `python manage.py server`. Granian serves the `public/`
directory at `/public`; do not add a static-files route or ASGI static middleware.
After changes, run `python manage.py inspect`.
"""
