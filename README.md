# Bingo

**The opinionated Python web framework for the AI era.**

Bingo 0.1 provides one conventional path from a new project to a complete async
CRUD application:

```bash
uv tool install .
bingo new blog
cd blog
bingo generate resource Post title:string body:text published:boolean
bingo migrate
bingo server
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
stylesheet in `public/`, so `bingo server` immediately opens a working page.
Granian is Bingo's ASGI server and serves `/public` directly without sending
static-file requests through Python.

Applications use class controllers, routes in `config/routes.py`, async models,
standalone validators, Jinja templates, and Bingo migrations. Generated projects
include `BINGO.md` with concise architectural rules for coding agents.

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
bingo server
bingo generate resource NAME [fields...]
bingo generate model NAME [fields...]
bingo generate controller NAME
bingo generate validator NAME [fields...]
bingo migrate
bingo rollback
bingo routes
bingo inspect
```

Generated projects use SQLite by default and accept `DATABASE_URL` for another
SQLAlchemy async database URL. `bingo inspect` reports convention violations with
the problem, expected structure, and a suggested fix.

`bingo server` maps the project's `public/` directory to `/public` through
Granian. Application routes do not need a static-files route or controller.

See [`examples/blog`](examples/blog) for a complete generated Post resource.

## Framework development

```bash
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```

Python 3.12 or newer is required.
