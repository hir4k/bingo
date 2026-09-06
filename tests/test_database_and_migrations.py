from pathlib import Path

import pytest
from sqlalchemy import inspect

from bingo.db import MigrationRunner, Model, database, fields
from bingo.exceptions import BingoNotFoundError


class Book(Model):
    title = fields.String()
    pages = fields.Integer()


@pytest.mark.asyncio
async def test_model_crud_and_query_builder(tmp_path: Path):
    database.configure(f"sqlite+aiosqlite:///{tmp_path / 'models.sqlite3'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Model.metadata.create_all)

    short = await Book.create(title="Short", pages=10)
    long = await Book.create(title="Long", pages=100)

    assert (await Book.find(short.id)).title == "Short"
    assert await Book.count() == 2
    found = await Book.where(pages=100).first()
    assert found.id == long.id
    assert [book.title for book in await Book.order_by("-pages").limit(1).all()] == [
        "Long"
    ]

    long.fill(title="Longer")
    await long.save()
    assert (await Book.find(long.id)).title == "Longer"
    await short.delete()
    assert await Book.count() == 1
    with pytest.raises(BingoNotFoundError):
        await Book.find_or_fail(short.id)

    await database.dispose()


@pytest.mark.asyncio
async def test_migration_runner_migrates_once_and_rolls_back(tmp_path: Path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    migration = migrations / "20260906000000_create_notes.py"
    migration.write_text(
        """from bingo.db import Migration


class CreateNotes(Migration):
    def change(self):
        self.create_table(
            "notes",
            lambda t: [t.id(), t.string("title")],
        )
""",
        encoding="utf-8",
    )
    database.configure(f"sqlite+aiosqlite:///{tmp_path / 'migrations.sqlite3'}")
    runner = MigrationRunner(migrations)

    assert await runner.migrate() == [migration.stem]
    assert await runner.migrate() == []
    async with database.engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    assert "notes" in tables

    assert await runner.rollback() == migration.stem
    assert await runner.rollback() is None
    await database.dispose()
