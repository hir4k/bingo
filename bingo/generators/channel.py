from __future__ import annotations

from pathlib import Path

from bingo.db.naming import snake_case
from bingo.exceptions import BingoConventionError
from bingo.generators.project import class_name


class ChannelGenerator:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()

    def generate(self, name: str, events: list[str] | None = None) -> list[Path]:
        normalized = snake_case(name).removesuffix("_channel")
        if (
            not normalized
            or not normalized.isidentifier()
            or normalized.startswith("_")
        ):
            raise BingoConventionError(
                f"Invalid channel name {name!r}. Use a name such as Chat."
            )

        events = events or []
        for event in events:
            self._validate_event(event)
        if len(events) != len(set(events)):
            raise BingoConventionError("Channel event names must be unique.")

        channel_class = f"{class_name(normalized)}Channel"
        channel_path = self.root / "app" / "channels" / f"{normalized}_channel.py"
        view_paths = [
            (self.root / "app" / "views" / "channels" / normalized / f"{event}.bjson")
            for event in events
        ]
        paths = [channel_path, *view_paths]
        conflicts = [path for path in paths if path.exists()]
        if conflicts:
            names = ", ".join(str(path) for path in conflicts)
            raise BingoConventionError(
                f"Cannot generate the channel without overwriting: {names}."
            )

        self._write(channel_path, CHANNEL.format(channel_class=channel_class))
        for view in view_paths:
            self._write(view, "{}\n")
        return paths

    def _validate_event(self, event: str) -> None:
        is_valid_event = (
            event.isidentifier()
            and not event.startswith("_")
            and event.lower() == event
        )
        if not is_valid_event:
            raise BingoConventionError(
                f"Invalid channel event {event!r}. Use a lowercase name such as message."
            )

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


CHANNEL = """from app.channels.application_channel import ApplicationChannel


class {channel_class}(ApplicationChannel):
    async def subscribed(self):
        await self.stream("all")

    async def received(self, data: dict):
        pass
"""
