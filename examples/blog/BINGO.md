# Bingo Project Rules

This application uses Bingo. Do not invent alternative architecture.

## Settings and commands

Shared settings live in `config/settings/base.py`; environment overrides live in
`config/settings/development.py`, `test.py`, and `production.py`. Bingo loads the
environment selected by `BINGO_ENV`, which defaults to `development`. Access
values through `from bingo import settings`. Do not add another configuration
system.

Run framework commands through `python manage.py`. Custom commands live in
`app/commands/`; each file defines one `Command(BaseCommand)` with one async
`handle()` method.

## Background tasks

Tasks live directly in `app/tasks/`. Each task file contains one matching class,
such as `send_welcome_email_task.py` and `SendWelcomeEmailTask`. It inherits from
`ApplicationTask`, declares one async `run()` method, and receives only typed,
JSON-compatible arguments. Enqueue it with `await SendWelcomeEmailTask.enqueue(...)`.
Pass model IDs, never model instances. Run tasks with `python manage.py worker` or
select a named queue with `python manage.py worker --queue mailers`. Configure the
backend only through `TASK_QUEUE_URL`; Redis is the default and PostgreSQL is also
supported through the `bingo-framework[postgres]` extra. Keep
`TASKS_INLINE = True` in test settings only.

## Realtime channels

Channels live directly in `app/channels/`. Each concrete channel file contains
one matching `ApplicationChannel` subclass with async `subscribed()` and
`received()` methods. Use `await self.stream(key)` to subscribe and
`await ChannelClass.broadcast(key, "event", **context)` to publish. Event data is
rendered only through `app/views/channels/<channel>/<event>.bjson`.

Do not declare channel routes or expose arbitrary methods. Bingo owns `/channels`
and serves the reconnecting browser wrapper at `/channels.js`. Incoming data uses
ordinary validators. `ApplicationConnection` owns shared connection setup but
defines no default user or authentication model. Broadcasts are ephemeral;
persistent messages and notifications belong in models.

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
or separate API controllers. Granian serves `public/` at `/public`; do not add
static middleware. After changes, run `python manage.py inspect`.
