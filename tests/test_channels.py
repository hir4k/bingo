from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from bingo import Application, Router
from bingo.conventions import ConventionInspector
from bingo.generators import ChannelGenerator, ProjectGenerator


def add_chat_channel(root: Path) -> None:
    channel = root / "app" / "channels" / "chat_channel.py"
    channel.write_text(
        """from app.channels.application_channel import ApplicationChannel
from app.validators.chat_message_validator import ChatMessageValidator


class ChatChannel(ApplicationChannel):
    async def subscribed(self):
        await self.stream(self.params["room"])

    async def received(self, data: dict):
        message = ChatMessageValidator(data).validate()
        await type(self).broadcast(self.params["room"], "message", **message)
""",
        encoding="utf-8",
    )
    validator = root / "app" / "validators" / "chat_message_validator.py"
    validator.write_text(
        """from bingo.validation import Validator, rules


class ChatMessageValidator(Validator):
    body = rules.String(required=True, max_length=100)
""",
        encoding="utf-8",
    )
    view = root / "app" / "views" / "channels" / "chat" / "message.bjson"
    view.parent.mkdir(parents=True)
    view.write_text('{"body": body}\n', encoding="utf-8")


def subscribe(websocket, identifier: str = "chat") -> None:
    websocket.send_json(
        {
            "command": "subscribe",
            "identifier": identifier,
            "channel": "ChatChannel",
            "params": {"room": "lobby"},
        }
    )
    assert websocket.receive_json() == {
        "type": "subscribed",
        "identifier": identifier,
    }


def test_channels_multiplex_and_broadcast_to_every_subscriber(
    tmp_path: Path,
    monkeypatch,
    clear_generated_modules,
):
    root = ProjectGenerator().generate("journal", tmp_path)
    add_chat_channel(root)
    monkeypatch.setenv("BINGO_ENV", "test")
    app = Application(Router(), root_path=root)

    with TestClient(app) as client:
        javascript = client.get("/channels.js")
        assert javascript.status_code == 200
        assert "class ChannelConsumer" in javascript.text

        with client.websocket_connect("/channels") as first:
            subscribe(first, "first")
            with client.websocket_connect("/channels") as second:
                subscribe(second, "second")

                first.send_json(
                    {
                        "command": "message",
                        "identifier": "first",
                        "data": {"body": "Hello"},
                    }
                )

                assert first.receive_json() == {
                    "type": "message",
                    "identifier": "first",
                    "event": "message",
                    "data": {"body": "Hello"},
                }
                assert second.receive_json() == {
                    "type": "message",
                    "identifier": "second",
                    "event": "message",
                    "data": {"body": "Hello"},
                }

    clear_generated_modules()


def test_channel_validation_errors_use_the_standard_error_shape(
    tmp_path: Path,
    monkeypatch,
    clear_generated_modules,
):
    root = ProjectGenerator().generate("journal", tmp_path)
    add_chat_channel(root)
    monkeypatch.setenv("BINGO_ENV", "test")
    app = Application(Router(), root_path=root)

    with (
        TestClient(app) as client,
        client.websocket_connect("/channels") as websocket,
    ):
        subscribe(websocket)
        websocket.send_json(
            {
                "command": "message",
                "identifier": "chat",
                "data": {"body": ""},
            }
        )
        assert websocket.receive_json() == {
            "type": "message",
            "identifier": "chat",
            "event": "validation_error",
            "data": {"errors": {"body": ["is required"]}},
        }

    clear_generated_modules()


def test_channel_generator_creates_channel_and_event_views(tmp_path: Path):
    root = ProjectGenerator().generate("journal", tmp_path)

    paths = ChannelGenerator(root).generate("Chat", ["message", "presence"])

    assert [path.name for path in paths] == [
        "chat_channel.py",
        "message.bjson",
        "presence.bjson",
    ]
    assert "class ChatChannel(ApplicationChannel)" in paths[0].read_text()
    assert ConventionInspector(root).inspect() == []
