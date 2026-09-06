# blog

A Bingo application.

```bash
bingo migrate
bingo server
```

Resource HTML uses unsuffixed URLs. Add `.json` to request the colocated `.bjson`
representation of the same controller action.

The create and update validators drive both interfaces. Invalid JSON receives a
422 JSON error object. Invalid HTML re-renders the form with submitted values and
errors; the form controls are produced by `form(validator)` in the template.

`config/routes.py` declares `routes.resources("/posts")`; Bingo imports the
conventional `PostsController` lazily.
