# blog

A Bingo application.

Start the Redis service used by background tasks and realtime channels:

```bash
docker compose up -d --wait
```

Then prepare and run the application:

```bash
python manage.py migrate
python manage.py server
```

Run the test suite with:

```bash
python -m pytest
```

Tests use SQLite and Bingo's in-memory task and channel backends, so they do not
require Docker. Redis is provided for exercising the development application
across server and worker processes.

Generate and run background tasks with:

```bash
python manage.py generate task PublishPost
python manage.py worker
```

Tasks and channels use the Redis URL in `TASK_QUEUE_URL` by default. PostgreSQL is
also supported by installing `bingo-framework[postgres]` and changing the URL.

Open `http://127.0.0.1:8000/chat` in two browser tabs to try the realtime channel
demo. The page uses Bingo's `/channels.js` wrapper, `ChatChannel`, a standard
validator, and `app/views/channels/chat/message.bjson`. Messages are intentionally
ephemeral and are delivered only to connected clients.

`BINGO_ENV` selects the settings file layered over `config/settings/base.py`.
It defaults to `development`.

Resource HTML uses unsuffixed URLs. Add `.json` to request the colocated `.bjson`
representation of the same controller action.

The create and update validators drive both interfaces. Invalid JSON receives a
422 JSON error object. Invalid HTML re-renders the form with submitted values and
errors; the form controls are produced by `form(validator)` in the template.

`config/routes.py` declares `routes.resources("/posts")`; Bingo imports the
conventional `PostsController` lazily.

Application commands live in `app/commands/` and run through `python manage.py`.

Stop the development service with `docker compose down`. Its data remains in the
`blog_redis-data` volume between runs.
