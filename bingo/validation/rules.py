from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal as DecimalValue
from decimal import InvalidOperation
from typing import Any


class Rule:
    def __init__(
        self,
        *,
        required: bool = False,
        min_length: int | None = None,
        max_length: int | None = None,
        min: float | None = None,
        max: float | None = None,
    ) -> None:
        self.required = required
        self.min_length = min_length
        self.max_length = max_length
        self.minimum = min
        self.maximum = max

    def clean(self, value: Any) -> tuple[Any, str | None]:
        if value is None or value == "":
            if self.required:
                return None, "is required"
            return None, None
        return self._clean_present(value)

    def _clean_present(self, value: Any) -> tuple[Any, str | None]:
        return value, None

    def _check_length(self, value: str) -> str | None:
        if self.min_length is not None and len(value) < self.min_length:
            return f"must be at least {self.min_length} characters"
        if self.max_length is not None and len(value) > self.max_length:
            return f"must be at most {self.max_length} characters"
        return None

    def _check_range(self, value: float) -> str | None:
        if self.minimum is not None and value < self.minimum:
            return f"must be at least {self.minimum}"
        if self.maximum is not None and value > self.maximum:
            return f"must be at most {self.maximum}"
        return None


class String(Rule):
    def _clean_present(self, value: Any):
        if not isinstance(value, str):
            return None, "must be a string"
        return value, self._check_length(value)


class Text(String):
    pass


class Integer(Rule):
    def _clean_present(self, value: Any):
        try:
            cleaned = int(value)
        except (TypeError, ValueError):
            return None, "must be an integer"
        return cleaned, self._check_range(cleaned)


class Float(Rule):
    def _clean_present(self, value: Any):
        try:
            cleaned = float(value)
        except (TypeError, ValueError):
            return None, "must be a number"
        return cleaned, self._check_range(cleaned)


class Boolean(Rule):
    TRUE_VALUES = (True, "1", "true", "on", "yes")
    FALSE_VALUES = (False, "0", "false", "off", "no")

    def _clean_present(self, value: Any):
        normalized = value.lower() if isinstance(value, str) else value
        if normalized in self.TRUE_VALUES:
            return True, None
        if normalized in self.FALSE_VALUES:
            return False, None
        return None, "must be true or false"


class Email(String):
    EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

    def _clean_present(self, value: Any):
        cleaned, error = super()._clean_present(value)
        if error:
            return cleaned, error
        if not self.EMAIL_PATTERN.match(cleaned):
            return None, "must be a valid email address"
        return cleaned, None


class Date(Rule):
    def _clean_present(self, value: Any):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value, None
        try:
            return date.fromisoformat(str(value)), None
        except ValueError:
            return None, "must be a date in YYYY-MM-DD format"


class DateTime(Rule):
    def _clean_present(self, value: Any):
        if isinstance(value, datetime):
            return value, None
        try:
            return datetime.fromisoformat(str(value)), None
        except ValueError:
            return None, "must be a valid ISO 8601 date and time"


class Decimal(Rule):
    def _clean_present(self, value: Any):
        try:
            cleaned = DecimalValue(str(value))
        except (InvalidOperation, ValueError):
            return None, "must be a decimal number"
        return cleaned, self._check_range(float(cleaned))
