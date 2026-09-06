from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConventionViolation:
    path: Path
    problem: str
    expected: str
    fix: str

    def __str__(self) -> str:
        return (
            f"BingoConventionError\n\n{self.path}\n\n"
            f"What is wrong:\n    {self.problem}\n\n"
            f"Expected:\n    {self.expected}\n\n"
            f"Suggested fix:\n    {self.fix}"
        )
