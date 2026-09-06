# Bingo

**The opinionated Python web framework for the AI era.**

Bingo 0.2 provides one conventional path from a new project to a complete async
CRUD application:

```bash
uv tool install .
bingo new blog
cd blog
python manage.py generate resource Post title:string body:text published:boolean
python manage.py migrate
python manage.py server
```

To initialize the current directory instead of creating a child directory:

```bash
mkdir blog
cd blog
bingo new .
```

Bingo derives the application name from the current directory. Unrelated files
are preserved. If a generated path already exists, Bingo reports every conflict
before writing anything.

New applications include a welcome controller and view at `/`, plus a small
stylesheet in `public/`, so `python manage.py server` immediately opens a working page.
Granian is Bingo's ASGI server and serves `/public` directly without sending
static-file requests through Python.

Applications use class controllers, routes in `config/routes.py`, async models,
standalone validators, Jinja templates, and Bingo migrations. Generated projects
include `BINGO.md` with concise architectural rules for coding agents.

## Settings

Settings are ordinary uppercase Python values split by environment:

```text
config/settings/base.py
config/settings/development.py
config/settings/test.py
config/settings/production.py
```

Bingo loads `base.py` and overlays the environment selected by `BINGO_ENV`. It
defaults to `development`. Application code accesses both framework and custom
settings through one object:

```python
from bingo import settings

page_size = settings.POSTS_PER_PAGE
```

Environment files never import the base file. Bingo performs the merge, so each
file contains only plain settings and environment-specific overrides.

## Application commands

Inside a project, `manage.py` is the only command entry point. Application-owned
commands live directly in `app/commands/`:

```python
from bingo import BaseCommand


class Command(BaseCommand):
    help = "Publish pending posts."

    async def handle(self, limit: int = 10, dry_run: bool = False): ...
```

Run it using its filename:

```bash
python manage.py publish_posts --limit 50 --dry-run
```

Required parameters become positional arguments. Parameters with defaults become
options, and boolean parameters become flags. `python manage.py --help` lists
built-in and application commands.

## Background tasks

Tasks use one application-facing API while SAQ handles durable queue mechanics
underneath. Generate a task with:

```bash
python manage.py generate task SendWelcomeEmail
```

This creates `app/tasks/send_welcome_email_task.py`:

```python
from app.tasks.application_task import ApplicationTask


class SendWelcomeEmailTask(ApplicationTask):
    queue = "mailers"
    retries = 3
    timeout = 60

    async def run(self, user_id: int):
        user = await User.find_or_fail(user_id)
        await send_email(user.email)
```

Controllers and commands enqueue it through the class:

```python
await SendWelcomeEmailTask.enqueue(user.id)
```

Run a worker for the default or a named queue:

```bash
python manage.py worker
python manage.py worker --queue mailers
```

`TASK_QUEUE_URL` selects the backend. Bingo defaults to Redis:

```python
TASK_QUEUE_URL = "redis://localhost:6379/0"
```

PostgreSQL is also supported without changing task code. Install
`bingo-framework[postgres]` and use a `postgres://` or `postgresql://` URL.

Task arguments and return values must be JSON-compatible. Pass model IDs instead
of model instances, and make tasks safe to execute more than once because durable
queues provide at-least-once delivery. `config/settings/test.py` sets
`TASKS_INLINE = True`, so tests execute tasks immediately without a queue server.

## Realtime channels

Channels provide ephemeral WebSocket updates through one multiplexed endpoint at
`/channels`. Generate a channel and its event views together:

```bash
python manage.py generate channel Chat message presence
```

The generated `app/channels/chat_channel.py` owns subscription and incoming
message behavior:

```python
from app.channels.application_channel import ApplicationChannel


class ChatChannel(ApplicationChannel):
    async def subscribed(self):
        await self.stream(self.params["room"])

    async def received(self, data: dict):
        message = ChatMessageValidator(data).validate()
        await type(self).broadcast(
            self.params["room"],
            "message",
            **message,
        )
```

Broadcasts render `app/views/channels/chat/message.bjson`, so channels never
serialize models implicitly. Validator failures are transmitted as the
`validation_error` event using the same error shape as JSON APIs.

Bingo serves its browser client at `/channels.js`; it maintains one WebSocket,
multiplexes subscriptions, and reconnects automatically:

```html
<script src="/channels.js"></script>
<script>
const chat = Bingo.channels.subscribe("ChatChannel", { room: "lobby" }, {
    connected() { console.log("connected") },
    received(event, data) { console.log(event, data) },
    disconnected() { console.log("reconnecting") },
})

chat.send({ name: "Ada", body: "Hello" })
</script>
```

`ApplicationConnection` is the single connection-level hook for attaching
application state or rejecting a socket. Bingo supplies no user model or default
authentication policy.

Channels and tasks may share infrastructure without sharing semantics:

```python
CHANNEL_URL = TASK_QUEUE_URL
```

Redis uses Pub/Sub. PostgreSQL `LISTEN/NOTIFY` remains available through the
`bingo-framework[postgres]` extra. Tests use `memory://`.
Broadcasts are online-only, so persist anything clients must retrieve after
reconnecting. Configure additional browser origins with
`CHANNEL_ALLOWED_ORIGINS`; same-origin connections are accepted automatically.

## The application shape

Routes have one home and one syntax:

```python
from bingo import Router

routes = Router()
routes.resources("/posts")
routes.get("/posts/published", "PostsController.published")
```

Resource controllers are inferred from the resource path:

```text
/posts → app/controllers/posts_controller.py → PostsController
```

Custom routes use a `"Controller.action"` target and an explicit HTTP verb.
Controllers are imported lazily when the application boots, after `config/routes.py`
has finished loading, so route files do not import application controllers.

Groups prefix both the URL and controller directory:

```python
with routes.group("/admin"):
    routes.resources("/posts")
    routes.get("/posts/published", "PostsController.published")
```

```text
/admin/posts
→ app/controllers/admin/posts_controller.py
→ PostsController
→ app/views/admin/posts/
```

The directory is the group, so controller classes remain short. Group blocks can
nest, and every group name uses the same slash-prefixed path syntax:

```python
with routes.group("/admin"):
    with routes.group("/reports"):
        routes.resources("/sales")
```

This resolves `SalesController` from
`app/controllers/admin/reports/sales_controller.py` and serves it under
`/admin/reports/sales`.

Resource controllers provide the seven actions `index`, `show`, `new`, `create`,
`edit`, `update`, and `destroy`. They receive `self.request`, `self.params`,
`self.query`, and `self.session`, and return `self.render(...)`,
`self.redirect(...)`, or `self.json(...)`.

HTML and JSON are representations of the same resource actions:

```text
GET /posts        → app/views/posts/index.html
GET /posts.json   → app/views/posts/index.bjson
GET /posts/1      → app/views/posts/show.html
GET /posts/1.json → app/views/posts/show.bjson
```

An extensionless render target follows the URL format:

```python
return self.render("posts/show", post=post)
```

Adding `.html` or `.json` to the render target locks it to that format. A format
mismatch returns 404. HTML views use Jinja. A `.bjson` view contains one restricted
Python expression that explicitly selects JSON fields; it cannot call functions,
await work, query models, or execute statements.

Every controller has one async `before_action` lifecycle hook. It returns `None`
to continue or a response to stop dispatch. Application-owned base controllers
can use this hook for shared policy without middleware registries or decorators.

Models and validators stay separate:

```python
from bingo.db import Model, fields
from bingo.validation import Validator, rules


class Post(Model):
    title = fields.String(max_length=200)
    published = fields.Boolean(default=False)


class PostCreateValidator(Validator):
    title = rules.String(required=True, max_length=200)
    published = rules.Boolean(required=True)
```

Validation has one execution path. `validate()` returns cleaned values or raises a
structured validation error:

```python
async def create(self):
    data = PostCreateValidator(self.request.data).validate()
    post = await Post.create(**data)

    if self.request.format == "json":
        return self.render("posts/show", post=post, status=201)
    return self.redirect(f"/posts/{post.id}")
```

Bingo handles the error at the controller boundary. A JSON request receives
`{"errors": {"title": ["is required"]}}` with status 422. An HTML `create` or
`update` request re-runs the conventional `new` or `edit` action with
`self.validation` set to the invalid validator, also with status 422.

HTML forms are generated from those same validator rules:

```python
async def new(self):
    validator = self.validation or PostCreateValidator()
    return self.render("posts/new.html", validator=validator)
```

```jinja
{% for field in form(validator) %}
    <label for="{{ field.name }}">{{ field.label }}</label>
    {{ field }}
    {{ field.errors }}
{% endfor %}
```

The field rule determines the standard HTML control. Use `rules.Text` for a
textarea; string, email, boolean, numeric, date, and datetime rules select their
matching inputs. Submitted values and field errors remain on the validator, so a
failed HTML form is rendered without rebuilding its state.

All database operations are async:

```python
post = await Post.create(title="Hello")
post = await Post.find_or_fail(1)
posts = await Post.where(published=True).order_by("-created_at").limit(10).all()
post.fill(title="Updated")
await post.save()
await post.delete()
```

## Commands

```text
bingo new NAME  # use . to initialize the current directory
python manage.py server
python manage.py generate resource NAME [fields...]
python manage.py generate model NAME [fields...]
python manage.py generate controller NAME
python manage.py generate validator NAME [fields...]
python manage.py generate task NAME
python manage.py generate channel NAME [events...]
python manage.py migrate
python manage.py rollback
python manage.py routes
python manage.py inspect
python manage.py worker [--queue QUEUE] [--concurrency INTEGER]
```

Development settings use SQLite by default and accept `DATABASE_URL` for another
SQLAlchemy async database URL. `python manage.py inspect` reports convention
violations with the problem, expected structure, and a suggested fix.

`python manage.py server` maps the project's `public/` directory to `/public` through
Granian. Application routes do not need a static-files route or controller.

See [`examples/blog`](examples/blog) for a complete generated Post resource.

## Framework development

```bash
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```

Python 3.12 or newer is required.
