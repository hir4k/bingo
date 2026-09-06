import sys
from pathlib import Path

from typer.testing import CliRunner

from bingo.generators import ProjectGenerator
from bingo.management import build_management_app
from bingo.settings import settings


def test_settings_merge_base_and_selected_environment(
    tmp_path: Path,
    monkeypatch,
):
    root = ProjectGenerator().generate("journal", tmp_path)
    base = root / "config" / "settings" / "base.py"
    base.write_text(base.read_text() + '\nCUSTOM_TITLE = "Base"\n', encoding="utf-8")
    test = root / "config" / "settings" / "test.py"
    test.write_text(
        test.read_text() + '\nCUSTOM_TITLE = "Test"\nTEST_ONLY = 42\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BINGO_ENV", "test")

    settings.load(root)

    assert settings.environment == "test"
    assert settings.APP_NAME == "journal"
    assert settings.CUSTOM_TITLE == "Test"
    assert settings.TEST_ONLY == 42
    assert settings.SERVER_HOST == "127.0.0.1"
    assert settings.CHANNEL_URL == "memory://"


def test_manage_discovers_and_runs_async_application_commands(
    tmp_path: Path,
    monkeypatch,
    clear_generated_modules,
):
    root = ProjectGenerator().generate("journal", tmp_path)
    command = root / "app" / "commands" / "greet.py"
    command.write_text(
        """from bingo import BaseCommand, settings


class Command(BaseCommand):
    help = "Greet someone from this application."

    async def handle(self, name: str, loud: bool = False):
        greeting = f"Hello, {name} from {settings.APP_NAME}"
        self.console.print(greeting.upper() if loud else greeting)
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(root)
    sys.path.insert(0, str(root))

    application = build_management_app(root)
    result = CliRunner().invoke(application, ["greet", "Ada", "--loud"])

    assert result.exit_code == 0, result.output
    assert "HELLO, ADA FROM JOURNAL" in result.output
    sys.path.remove(str(root))
    clear_generated_modules()
