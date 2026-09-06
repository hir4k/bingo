from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bingo.db.naming import pluralize, singularize, snake_case
from bingo.exceptions import BingoConventionError
from bingo.generators.project import class_name

FIELD_TYPES = {
    "integer": ("Integer()", "Integer"),
    "string": ("String()", "String"),
    "text": ("Text()", "Text"),
    "boolean": ("Boolean(default=False)", "Boolean"),
    "date": ("Date()", "Date"),
    "datetime": ("DateTime()", "DateTime"),
    "float": ("Float()", "Float"),
    "decimal": ("Decimal()", "Decimal"),
}


@dataclass(frozen=True)
class ResourceField:
    name: str
    kind: str


@dataclass(frozen=True)
class ResourceNames:
    model: str
    singular: str
    plural: str
    controller: str


def parse_fields(values: list[str]) -> list[ResourceField]:
    fields = []
    for value in values:
        if ":" not in value:
            raise BingoConventionError(
                f"Invalid field {value!r}. Expected NAME:TYPE, for example title:string."
            )
        name, kind = value.split(":", 1)
        if not name.isidentifier() or name.startswith("_"):
            raise BingoConventionError(f"Invalid field name {name!r}.")
        if kind not in FIELD_TYPES:
            supported = ", ".join(FIELD_TYPES)
            raise BingoConventionError(
                f"Unknown field type {kind!r}. Expected one of: {supported}."
            )
        fields.append(ResourceField(name, kind))
    return fields


def resource_names(name: str) -> ResourceNames:
    normalized = snake_case(name)
    singular = singularize(normalized)
    plural = pluralize(singular)
    return ResourceNames(
        model=class_name(singular),
        singular=singular,
        plural=plural,
        controller=f"{class_name(plural)}Controller",
    )


class ResourceGenerator:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()

    def generate(self, name: str, field_specs: list[str]) -> list[Path]:
        names = resource_names(name)
        fields = parse_fields(field_specs)
        generated = []
        generated.extend(self.generate_model(name, field_specs))
        generated.extend(self.generate_controller(name, fields))
        generated.extend(self.generate_validators(name, fields))
        generated.extend(self.generate_views(names, fields))
        generated.append(self.generate_migration(names, fields))
        generated.extend(self.generate_tests(names))
        generated.append(self.update_routes(names))
        return generated

    def generate_model(self, name: str, field_specs: list[str]) -> list[Path]:
        names = resource_names(name)
        fields = parse_fields(field_specs)
        definitions = [
            f"    {field.name} = fields.{FIELD_TYPES[field.kind][0]}"
            for field in fields
        ]
        definitions.extend(
            [
                "    created_at = fields.DateTime(auto_now_add=True)",
                "    updated_at = fields.DateTime(auto_now=True)",
            ]
        )
        content = (
            "from bingo.db import Model, fields\n\n\n"
            f"class {names.model}(Model):\n" + "\n".join(definitions) + "\n"
        )
        path = self.root / "app" / "models" / f"{names.singular}.py"
        self._write_new(path, content)
        return [path]

    def generate_controller(
        self, name: str, fields: list[ResourceField] | None = None
    ) -> list[Path]:
        names = resource_names(name)
        path = self.root / "app" / "controllers" / f"{names.plural}_controller.py"
        template = CONTROLLER if fields is not None else EMPTY_CONTROLLER
        self._write_new(path, template.format(**vars(names)))
        return [path]

    def generate_validator(self, name: str, fields: list[ResourceField]) -> list[Path]:
        normalized = snake_case(name)
        validator_class = class_name(normalized)
        definitions = [
            f"    {field.name} = rules.{FIELD_TYPES[field.kind][1]}(required=True)"
            for field in fields
        ]
        content = (
            "from bingo.validation import Validator, rules\n\n\n"
            f"class {validator_class}(Validator):\n"
            + ("\n".join(definitions) if definitions else "    pass")
            + "\n"
        )
        path = self.root / "app" / "validators" / f"{normalized}.py"
        self._write_new(path, content)
        return [path]

    def generate_validators(self, name: str, fields: list[ResourceField]) -> list[Path]:
        names = resource_names(name)
        paths = []
        for action in ("create", "update"):
            validator_name = f"{names.singular}_{action}_validator"
            paths.extend(self.generate_validator(validator_name, fields))
        return paths

    def generate_views(
        self, names: ResourceNames, fields: list[ResourceField]
    ) -> list[Path]:
        directory = self.root / "app" / "views" / names.plural
        values = "\n".join(
            f"<dt>{field.name.replace('_', ' ').title()}</dt>\n<dd>{{{{ {names.singular}.{field.name} }}}}</dd>"
            for field in fields
        )
        display_field = fields[0].name if fields else "id"
        files = {
            "index.html": INDEX_VIEW.format(display_field=display_field, **vars(names)),
            "show.html": SHOW_VIEW.format(values=values, **vars(names)),
            "new.html": NEW_VIEW.format(**vars(names)),
            "edit.html": EDIT_VIEW.format(**vars(names)),
            "index.bjson": self._index_json_view(names, fields),
            "show.bjson": self._show_json_view(names, fields),
        }
        paths = []
        for filename, content in files.items():
            path = directory / filename
            self._write_new(path, content)
            paths.append(path)
        return paths

    def _index_json_view(
        self,
        names: ResourceNames,
        fields: list[ResourceField],
    ) -> str:
        attributes = [
            "id",
            *(field.name for field in fields),
            "created_at",
            "updated_at",
        ]
        values = "\n".join(
            f'            "{name}": {names.singular}.{name},' for name in attributes
        )
        return (
            "{\n"
            f'    "{names.plural}": [\n'
            "        {\n"
            f"{values}\n"
            "        }\n"
            f"        for {names.singular} in {names.plural}\n"
            "    ],\n"
            "}\n"
        )

    def _show_json_view(
        self,
        names: ResourceNames,
        fields: list[ResourceField],
    ) -> str:
        attributes = [
            "id",
            *(field.name for field in fields),
            "created_at",
            "updated_at",
        ]
        values = "\n".join(
            f'        "{name}": {names.singular}.{name},' for name in attributes
        )
        return f'{{\n    "{names.singular}": {{\n{values}\n    }},\n}}\n'

    def generate_migration(
        self, names: ResourceNames, fields: list[ResourceField]
    ) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        columns = [
            f'                t.{field.kind}("{field.name}"),' for field in fields
        ]
        content = MIGRATION.format(
            migration_class=f"Create{class_name(names.plural)}",
            table=names.plural,
            columns="\n".join(columns),
        )
        path = self.root / "db" / "migrations" / f"{timestamp}_create_{names.plural}.py"
        self._write_new(path, content)
        return path

    def generate_tests(self, names: ResourceNames) -> list[Path]:
        path = self.root / "tests" / f"test_{names.plural}.py"
        self._write_new(path, GENERATED_TEST.format(**vars(names)))
        return [path]

    def update_routes(self, names: ResourceNames) -> Path:
        path = self.root / "config" / "routes.py"
        content = path.read_text(encoding="utf-8")
        route_line = f'routes.resources("/{names.plural}")\n'
        if route_line in content:
            raise BingoConventionError(
                f"Routes for {names.model} already exist in config/routes.py."
            )
        updated = content.rstrip() + "\n\n" + route_line
        path.write_text(updated, encoding="utf-8")
        return path

    def _write_new(self, path: Path, content: str) -> None:
        if path.exists():
            raise BingoConventionError(
                f"Cannot generate {path}: the file already exists. Remove it or "
                "choose another resource name."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


CONTROLLER = """from app.controllers.application_controller import ApplicationController
from app.models.{singular} import {model}
from app.validators.{singular}_create_validator import {model}CreateValidator
from app.validators.{singular}_update_validator import {model}UpdateValidator


class {controller}(ApplicationController):
    async def index(self):
        {plural} = await {model}.all()
        return self.render("{plural}/index", {plural}={plural})

    async def show(self):
        {singular} = await {model}.find_or_fail(self.params["id"])
        return self.render("{plural}/show", {singular}={singular})

    async def new(self):
        validator = self.validation or {model}CreateValidator()
        return self.render(
            "{plural}/new.html",
            validator=validator,
        )

    async def create(self):
        data = {model}CreateValidator(self.request.data).validate()
        {singular} = await {model}.create(**data)
        if self.request.format == "json":
            return self.render(
                "{plural}/show",
                {singular}={singular},
                status=201,
            )

        return self.redirect(f"/{plural}/{{{singular}.id}}")

    async def edit(self):
        {singular} = await {model}.find_or_fail(self.params["id"])
        validator = self.validation or {model}UpdateValidator({singular}.to_dict())
        return self.render(
            "{plural}/edit.html",
            {singular}={singular},
            validator=validator,
        )

    async def update(self):
        {singular} = await {model}.find_or_fail(self.params["id"])
        data = {model}UpdateValidator(self.request.data).validate()
        {singular}.fill(**data)
        await {singular}.save()
        if self.request.format == "json":
            return self.render(
                "{plural}/show",
                {singular}={singular},
            )

        return self.redirect(f"/{plural}/{{{singular}.id}}")

    async def destroy(self):
        {singular} = await {model}.find_or_fail(self.params["id"])
        await {singular}.delete()
        if self.request.format == "json":
            return self.json({{"deleted": True}})

        return self.redirect("/{plural}")
"""

EMPTY_CONTROLLER = """from app.controllers.application_controller import ApplicationController


class {controller}(ApplicationController):
    pass
"""

MIGRATION = """from bingo.db import Migration


class {migration_class}(Migration):
    def change(self):
        self.create_table(
            "{table}",
            lambda t: [
                t.id(),
{columns}
                t.timestamps(),
            ],
        )
"""

INDEX_VIEW = """{{% extends "layouts/application.html" %}}
{{% block content %}}
<h1>{model}s</h1>
<p><a href="/{plural}/new">New {model}</a></p>
<ul>
{{% for {singular} in {plural} %}}
    <li><a href="/{plural}/{{{{ {singular}.id }}}}">{{{{ {singular}.{display_field} }}}}</a></li>
{{% else %}}
    <li>No {plural} yet.</li>
{{% endfor %}}
</ul>
{{% endblock %}}
"""

SHOW_VIEW = """{{% extends "layouts/application.html" %}}
{{% block content %}}
<h1>{model}</h1>
<dl>
{values}
</dl>
<p><a href="/{plural}/{{{{ {singular}.id }}}}/edit">Edit</a></p>
<form method="post" action="/{plural}/{{{{ {singular}.id }}}}">
    <input type="hidden" name="_method" value="DELETE">
    <button type="submit">Delete</button>
</form>
<p><a href="/{plural}">Back</a></p>
{{% endblock %}}
"""

NEW_VIEW = """{{% extends "layouts/application.html" %}}
{{% block content %}}
<h1>New {model}</h1>
<form method="post" action="/{plural}">
{{% for field in form(validator) %}}
<p>
    <label for="{{{{ field.name }}}}">{{{{ field.label }}}}</label>
    {{{{ field }}}}
    {{{{ field.errors }}}}
</p>
{{% endfor %}}
    <button type="submit">Create {model}</button>
</form>
{{% endblock %}}
"""

EDIT_VIEW = """{{% extends "layouts/application.html" %}}
{{% block content %}}
<h1>Edit {model}</h1>
<form method="post" action="/{plural}/{{{{ {singular}.id }}}}">
    <input type="hidden" name="_method" value="PATCH">
{{% for field in form(validator) %}}
<p>
    <label for="{{{{ field.name }}}}">{{{{ field.label }}}}</label>
    {{{{ field }}}}
    {{{{ field.errors }}}}
</p>
{{% endfor %}}
    <button type="submit">Update {model}</button>
</form>
{{% endblock %}}
"""

GENERATED_TEST = """def test_{plural}_resource_was_generated():
    from pathlib import Path

    from app.controllers.{plural}_controller import {controller}
    from app.models.{singular} import {model}

    assert {model}.__tablename__ == "{plural}"
    assert {controller}.__name__ == "{controller}"
    assert Path("app/views/{plural}/index.bjson").is_file()
    assert Path("app/views/{plural}/show.bjson").is_file()
"""
