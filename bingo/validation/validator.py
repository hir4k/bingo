from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bingo.exceptions import BingoValidationError
from bingo.validation.rules import Rule


class Validator:
    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self.data = dict(data or {})
        self.cleaned_data: dict[str, Any] = {}
        self.errors: dict[str, list[str]] = {}
        self._validated = False

    @classmethod
    def declared_rules(cls) -> dict[str, Rule]:
        collected: dict[str, Rule] = {}
        for parent in reversed(cls.__mro__):
            collected.update(
                {
                    name: value
                    for name, value in vars(parent).items()
                    if isinstance(value, Rule)
                }
            )
        return collected

    def validate(self) -> dict[str, Any]:
        self.cleaned_data = {}
        self.errors = {}

        for name, rule in self.declared_rules().items():
            cleaned, error = rule.clean(self.data.get(name))
            if error:
                self.errors[name] = [error]
                continue
            if cleaned is not None:
                self.cleaned_data[name] = cleaned

        self._validated = True
        if self.errors:
            raise BingoValidationError(self)
        return self.cleaned_data

    def __getitem__(self, name: str) -> Any:
        if not self._validated:
            raise RuntimeError(
                "Call validator.validate() before reading cleaned values."
            )
        return self.cleaned_data[name]
