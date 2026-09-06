from __future__ import annotations

from sqlalchemy import func, select

from bingo.db.database import database
from bingo.exceptions import BingoDatabaseError


class Query[ModelType]:
    def __init__(self, model: type[ModelType], filters: dict | None = None) -> None:
        self.model = model
        self.filters = filters or {}
        self.ordering: list[str] = []
        self.maximum: int | None = None
        self.skip = 0

    def where(self, **values) -> Query[ModelType]:
        self.filters.update(values)
        return self

    def order_by(self, *fields: str) -> Query[ModelType]:
        self.ordering.extend(fields)
        return self

    def limit(self, count: int) -> Query[ModelType]:
        self.maximum = count
        return self

    def offset(self, count: int) -> Query[ModelType]:
        self.skip = count
        return self

    async def all(self) -> list[ModelType]:
        statement = self._statement()
        async with database.session() as session:
            result = await session.scalars(statement)
            return list(result.all())

    async def first(self) -> ModelType | None:
        statement = self._statement().limit(1)
        async with database.session() as session:
            return await session.scalar(statement)

    async def count(self) -> int:
        statement = select(func.count()).select_from(self.model)
        for name, value in self.filters.items():
            statement = statement.where(self._column(name) == value)
        async with database.session() as session:
            value = await session.scalar(statement)
            return int(value or 0)

    def __await__(self):
        return self.all().__await__()

    def _statement(self):
        statement = select(self.model)
        for name, value in self.filters.items():
            statement = statement.where(self._column(name) == value)

        for field in self.ordering:
            descending = field.startswith("-")
            name = field[1:] if descending else field
            column = self._column(name)
            statement = statement.order_by(
                column.desc() if descending else column.asc()
            )

        if self.maximum is not None:
            statement = statement.limit(self.maximum)
        if self.skip:
            statement = statement.offset(self.skip)
        return statement

    def _column(self, name: str):
        column = getattr(self.model, name, None)
        if column is None:
            raise BingoDatabaseError(
                f"{self.model.__name__} has no field named {name!r}. "
                "Use a declared model field in where() or order_by()."
            )
        return column
