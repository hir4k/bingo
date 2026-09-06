from __future__ import annotations

from pathlib import Path

from bingo.db.naming import snake_case
from bingo.exceptions import BingoConventionError
from bingo.generators.project import class_name


class TaskGenerator:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()

    def generate(self, name: str) -> Path:
        normalized = snake_case(name)
        normalized = normalized.removesuffix("_task")
        if (
            not normalized
            or not normalized.isidentifier()
            or normalized.startswith("_")
        ):
            raise BingoConventionError(
                f"Invalid task name {name!r}. Use a name such as SendWelcomeEmail."
            )

        task_name = f"{normalized}_task"
        task_class = f"{class_name(normalized)}Task"
        path = self.root / "app" / "tasks" / f"{task_name}.py"
        if path.exists():
            raise BingoConventionError(
                f"Cannot generate {path}: the task already exists."
            )

        content = TASK.format(task_class=task_class)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path


TASK = """from app.tasks.application_task import ApplicationTask


class {task_class}(ApplicationTask):
    async def run(self):
        raise NotImplementedError
"""
