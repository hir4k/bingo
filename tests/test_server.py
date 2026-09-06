from pathlib import Path
from types import SimpleNamespace

from granian.constants import Interfaces

from bingo.cli import server as server_module
from bingo.generators import ProjectGenerator


def test_server_uses_granian_and_serves_public_directly(
    tmp_path: Path,
    monkeypatch,
):
    root = ProjectGenerator().generate("journal", tmp_path)
    calls = {}

    class FakeGranian:
        def __init__(self, target, **options):
            calls["target"] = target
            calls["options"] = options

        def serve(self):
            calls["served"] = True

    monkeypatch.chdir(root)
    monkeypatch.setattr(server_module, "Granian", FakeGranian)
    monkeypatch.setattr(
        server_module,
        "load_application",
        lambda project_root: SimpleNamespace(),
    )

    server_module.server(host="0.0.0.0", port=4321, reload=False)

    assert calls["target"] == "config.application:app"
    assert calls["served"] is True
    assert calls["options"] == {
        "address": "0.0.0.0",
        "port": 4321,
        "interface": Interfaces.ASGI,
        "working_dir": root,
        "static_path_route": ["/public"],
        "static_path_mount": [root / "public"],
        "static_path_expires": 0,
        "reload": False,
        "reload_paths": [root],
    }
