from __future__ import annotations

from collections.abc import Iterator
from html import escape
from typing import Any

from markupsafe import Markup

from bingo.validation import Validator, rules


class ErrorList:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages

    def __bool__(self) -> bool:
        return bool(self.messages)

    def __iter__(self) -> Iterator[str]:
        return iter(self.messages)

    def __html__(self) -> Markup:
        if not self.messages:
            return Markup("")

        items = "".join(f"<li>{escape(message)}</li>" for message in self.messages)
        return Markup(f'<ul class="errors">{items}</ul>')

    def __str__(self) -> str:
        return str(self.__html__())


class Field:
    def __init__(self, name: str, rule: rules.Rule, validator: Validator) -> None:
        self.name = name
        self.rule = rule
        self.label = name.replace("_", " ").title()
        self.value = validator.data.get(name, "")
        self.errors = ErrorList(validator.errors.get(name, []))

    @property
    def required(self) -> bool:
        return self.rule.required

    @property
    def type(self) -> str:
        if isinstance(self.rule, rules.Text):
            return "textarea"
        if isinstance(self.rule, rules.Email):
            return "email"
        if isinstance(self.rule, rules.Boolean):
            return "checkbox"
        if isinstance(self.rule, rules.Integer | rules.Float | rules.Decimal):
            return "number"
        if isinstance(self.rule, rules.DateTime):
            return "datetime-local"
        if isinstance(self.rule, rules.Date):
            return "date"
        return "text"

    def input(self, **attributes: Any) -> Markup:
        input_type = attributes.pop("type", self.type)
        if input_type == "textarea":
            return self.textarea(**attributes)
        if input_type == "checkbox":
            return self._checkbox(attributes)

        attributes = {
            "id": self.name,
            "name": self.name,
            "type": input_type,
            "value": self.value,
            "required": self.required,
            **attributes,
        }
        return Markup(f"<input {_attributes(attributes)}>")

    def textarea(self, **attributes: Any) -> Markup:
        attributes = {
            "id": self.name,
            "name": self.name,
            "required": self.required,
            **attributes,
        }
        value = escape(str(self.value))
        return Markup(f"<textarea {_attributes(attributes)}>{value}</textarea>")

    def _checkbox(self, attributes: dict[str, Any]) -> Markup:
        normalized = self.value.lower() if isinstance(self.value, str) else self.value
        checked = normalized in rules.Boolean.TRUE_VALUES
        checkbox_attributes = {
            "id": self.name,
            "name": self.name,
            "type": "checkbox",
            "value": "true",
            "checked": checked,
            **attributes,
        }
        hidden = f'<input type="hidden" name="{escape(self.name)}" value="false">'
        checkbox = f"<input {_attributes(checkbox_attributes)}>"
        return Markup(hidden + checkbox)

    def __html__(self) -> Markup:
        return self.input()

    def __str__(self) -> str:
        return str(self.__html__())


class Form:
    def __init__(self, validator: Validator) -> None:
        self.validator = validator

    def __iter__(self) -> Iterator[Field]:
        for name, rule in self.validator.declared_rules().items():
            yield Field(name, rule, self.validator)

    def __getitem__(self, name: str) -> Field:
        rule = self.validator.declared_rules()[name]
        return Field(name, rule, self.validator)

    def value(self, name: str) -> Any:
        return self[name].value

    def error(self, name: str) -> ErrorList:
        return self[name].errors

    def input(self, name: str, **attributes: Any) -> Markup:
        return self[name].input(**attributes)

    def textarea(self, name: str, **attributes: Any) -> Markup:
        return self[name].textarea(**attributes)


def _attributes(attributes: dict[str, Any]) -> str:
    rendered = []
    for name, value in attributes.items():
        html_name = "class" if name == "class_" else name.replace("_", "-")
        if isinstance(value, bool):
            if value:
                rendered.append(html_name)
            continue
        rendered.append(f'{html_name}="{escape(str(value), quote=True)}"')
    return " ".join(rendered)
