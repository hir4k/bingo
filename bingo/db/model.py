from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, inspect
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from bingo.db.database import database
from bingo.db.naming import pluralize, snake_case
from bingo.db.query import Query
from bingo.exceptions import BingoNotFoundError


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Model(Base):
    __abstract__ = True
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return pluralize(snake_case(cls.__name__))

    @classmethod
    async def find(cls, identifier: Any):
        async with database.session() as session:
            return await session.get(cls, identifier)

    @classmethod
    async def find_or_fail(cls, identifier: Any):
        record = await cls.find(identifier)
        if record is None:
            raise BingoNotFoundError(
                f"{cls.__name__} with id {identifier!r} was not found."
            )
        return record

    @classmethod
    async def all(cls):
        return await Query(cls).all()

    @classmethod
    def where(cls, **values):
        return Query(cls, values)

    @classmethod
    def order_by(cls, *fields: str):
        return Query(cls).order_by(*fields)

    @classmethod
    def limit(cls, count: int):
        return Query(cls).limit(count)

    @classmethod
    def offset(cls, count: int):
        return Query(cls).offset(count)

    @classmethod
    async def first(cls):
        return await Query(cls).first()

    @classmethod
    async def count(cls):
        return await Query(cls).count()

    @classmethod
    async def create(cls, **values):
        record = cls(**values)
        await record.save()
        return record

    def fill(self, **values) -> None:
        valid_fields = {column.key for column in inspect(type(self)).columns}
        for name, value in values.items():
            if name not in valid_fields:
                raise AttributeError(f"{type(self).__name__} has no field {name!r}.")
            setattr(self, name, value)

    async def save(self) -> None:
        async with database.session() as session:
            session.add(self)
            await session.commit()
            await session.refresh(self)

    async def delete(self) -> None:
        async with database.session() as session:
            record = await session.merge(self)
            await session.delete(record)
            await session.commit()

    def to_dict(self) -> dict[str, Any]:
        return {
            column.key: getattr(self, column.key)
            for column in inspect(type(self)).columns
        }
