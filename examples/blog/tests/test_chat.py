from starlette.testclient import TestClient


def test_chat_broadcasts_and_validates_messages(monkeypatch):
    monkeypatch.setenv("BINGO_ENV", "test")

    from config.application import app

    with TestClient(app) as client:
        page = client.get("/chat")
        assert page.status_code == 200
        assert "Lobby chat" in page.text
        assert client.get("/channels.js").status_code == 200

        with client.websocket_connect("/channels") as websocket:
            websocket.send_json(
                {
                    "command": "subscribe",
                    "identifier": "demo",
                    "channel": "ChatChannel",
                    "params": {"room": "lobby"},
                }
            )
            assert websocket.receive_json()["type"] == "subscribed"

            websocket.send_json(
                {
                    "command": "message",
                    "identifier": "demo",
                    "data": {"name": "Ada", "body": "Hello from Bingo"},
                }
            )
            assert websocket.receive_json() == {
                "type": "message",
                "identifier": "demo",
                "event": "message",
                "data": {"name": "Ada", "body": "Hello from Bingo"},
            }
