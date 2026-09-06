from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    delete,
    select,
)

from bingo.db.database import Database, database
from bingo.exceptions import BingoDatabaseError


class TableBuilder:
    def id(self, name: str = "id") -> Column:
        return Column(name, Integer, primary_key=True)

    def integer(self, name: str, **options) -> Column:
        return Column(name, Integer, **options)

    def string(self, name: str, max_length: int = 255, **options) -> Column:
        return Column(name, String(max_length), **options)

    def text(self, name: str, **options) -> Column:
        return Column(name, Text, **options)

    def boolean(self, name: str, **options) -> Column:
        return Column(name, Boolean, **options)

    def date(self, name: str, **options) -> Column:
        return Column(name, Date, **options)

    def datetime(self, name: str, **options) -> Column:
        return Column(name, DateTime(timezone=True), **options)

    def float(self, name: str, **options) -> Column:
        return Column(name, Float, **options)

    def decimal(
        self, name: str, precision: int = 10, scale: int = 2, **options
    ) -> Column:
        return Column(name, Numeric(precision, scale), **options)

    def timestamps(self) -> list[Column]:
        return [
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        ]


class Migration:
    def __init__(self) -> None:
        self.metadata = MetaData()
        self.tables: list[Table] = []

    def change(self) -> None:
        raise NotImplementedError

    def create_table(self, name: str, definition) -> None:
        columns = definition(TableBuilder())
        flattened = []
        for item in columns:
            flattened.extend(item if isinstance(item, list) else [item])
        self.tables.append(Table(name, self.metadata, *flattened))


class MigrationRunner:
    def __init__(
        self,
        migrations_path: str | Path,
        configured_database: Database | None = None,
    ) -> None:
        self.path = Path(migrations_path)
        self.database = configured_database or database
        self.state = Table(
            "bingo_migrations",
            MetaData(),
            Column("name", String(255), primary_key=True),
        )

    async def migrate(self) -> list[str]:
        engine = self._engine()
        applied: list[str] = []
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: self.state.create(
                    sync_connection, checkfirst=True
                )
            )
            rows = await connection.execute(select(self.state.c.name))
            completed = set(rows.scalars())

            for migration_file in self._files():
                if migration_file.stem in completed:
                    continue
                migration = self._load(migration_file)
                for table in migration.tables:
                    await connection.run_sync(table.create)
                await connection.execute(
                    self.state.insert().values(name=migration_file.stem)
                )
                applied.append(migration_file.stem)
        return applied

    async def rollback(self) -> str | None:
        engine = self._engine()
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: self.state.create(
                    sync_connection, checkfirst=True
                )
            )
            statement = (
                select(self.state.c.name).order_by(self.state.c.name.desc()).limit(1)
            )
            name = await connection.scalar(statement)
            if name is None:
                return None

            migration = self._load(self.path / f"{name}.py")
            for table in reversed(migration.tables):
                await connection.run_sync(table.drop)
            await connection.execute(
                delete(self.state).where(self.state.c.name == name)
            )
            return str(name)

    def _engine(self):
        if self.database.engine is None:
            raise BingoDatabaseError(
                "Configure the database before running migrations."
            )
        return self.database.engine

    def _files(self) -> list[Path]:
        return sorted(self.path.glob("*.py"))

    def _load(self, path: Path) -> Migration:
        spec = importlib.util.spec_from_file_location(
            f"bingo_migration_{path.stem}", path
        )
        if spec is None or spec.loader is None:
            raise BingoDatabaseError(f"Could not load migration {path}.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        classes = [
            item
            for item in vars(module).values()
            if isinstance(item, type)
            and issubclass(item, Migration)
            and item is not Migration
        ]
        if len(classes) != 1:
            raise BingoDatabaseError(
                f"{path} must contain exactly one Bingo Migration class."
            )
        migration = classes[0]()
        migration.change()
        return migration
