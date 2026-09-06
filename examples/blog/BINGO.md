# Bingo Project Rules

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
