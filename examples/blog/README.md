# blog

A Bingo application.

```bash
python manage.py migrate
python manage.py server
```

Generate and run background tasks with:

```bash
python manage.py generate task PublishPost
python manage.py worker
```

Tasks use the PostgreSQL URL in `TASK_QUEUE_URL` by default. Redis URLs are also
supported without changing application task code.

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
