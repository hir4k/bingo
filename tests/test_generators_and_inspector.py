from pathlib import Path

import pytest
from typer.testing import CliRunner

from bingo.cli.app import app
from bingo.conventions import ConventionInspector
from bingo.exceptions import BingoConventionError
from bingo.generators import ProjectGenerator, ResourceGenerator


def test_new_project_and_all_generators(tmp_path: Path):
    root = ProjectGenerator().generate("journal", tmp_path)
    assert (root / "BINGO.md").is_file()
    assert "class JournalApplication" in (root / "config/application.py").read_text()
    assert (root / "app/controllers/welcome_controller.py").is_file()
    assert (root / "app/views/welcome/index.html").is_file()
    assert (root / "public/application.css").is_file()
    assert (
        'routes.get("/", "WelcomeController.index")'
        in (root / "config/routes.py").read_text()
    )

    generator = ResourceGenerator(root)
    generated = generator.generate(
        "Post", ["title:string", "body:text", "published:boolean"]
    )
    assert len(generated) == 13
    assert (root / "app/models/post.py").is_file()
    assert (root / "app/controllers/posts_controller.py").is_file()
    assert (root / "app/validators/post_create_validator.py").is_file()
    assert (root / "app/views/posts/edit.html").is_file()
    assert (root / "app/views/posts/index.bjson").is_file()
    assert (root / "app/views/posts/show.bjson").is_file()
    assert list((root / "db/migrations").glob("*_create_posts.py"))
    assert 'routes.resources("/posts")' in (root / "config/routes.py").read_text()
    assert "app.controllers" not in (root / "config/routes.py").read_text()
    assert ConventionInspector(root).inspect() == []

    generator.generate_model("Comment", ["body:text"])
    generator.generate_controller("Comment")
    generator.generate_validator("CommentCreateValidator", [])
    assert (root / "app/models/comment.py").exists()
    assert (root / "app/controllers/comments_controller.py").exists()
    assert (root / "app/validators/comment_create_validator.py").exists()


def test_cli_new_and_resource_generation(tmp_path: Path, monkeypatch):
    runner = CliRunner()
    result = runner.invoke(app, ["new", "notes", "--destination", str(tmp_path)])
    assert result.exit_code == 0, result.output

    root = tmp_path / "notes"
    monkeypatch.chdir(root)
    result = runner.invoke(
        app,
        ["generate", "resource", "Note", "title:string", "body:text"],
    )
    assert result.exit_code == 0, result.output
    assert (root / "app/controllers/notes_controller.py").is_file()


def test_cli_new_dot_initializes_the_current_directory(tmp_path: Path, monkeypatch):
    root = tmp_path / "existing_blog"
    root.mkdir()
    (root / "notes.txt").write_text("keep me", encoding="utf-8")
    monkeypatch.chdir(root)

    result = CliRunner().invoke(app, ["new", "."])

    assert result.exit_code == 0, result.output
    assert (root / "config/application.py").is_file()
    assert 'name = "existing_blog"' in (root / "pyproject.toml").read_text()
    assert (root / "notes.txt").read_text() == "keep me"


def test_new_dot_reports_all_conflicts_before_writing(tmp_path: Path):
    root = tmp_path / "existing_blog"
    root.mkdir()
    (root / "README.md").write_text("Existing README", encoding="utf-8")

    with pytest.raises(BingoConventionError, match="README.md"):
        ProjectGenerator().generate(".", root)

    assert not (root / "app").exists()
    assert (root / "README.md").read_text() == "Existing README"


def test_inspector_explains_invalid_class_and_misplaced_controller(tmp_path: Path):
    root = ProjectGenerator().generate("broken", tmp_path)
    bad = root / "app" / "controllers" / "posts_controller.py"
    bad.write_text("class PostHandler:\n    pass\n", encoding="utf-8")
    misplaced = root / "app" / "models" / "comments_controller.py"
    misplaced.write_text("class CommentsController:\n    pass\n", encoding="utf-8")

    text = "\n".join(str(item) for item in ConventionInspector(root).inspect())
    assert "Exactly one class named PostsController" in text
    assert "outside app/controllers" in text
    assert "Suggested fix" in text


def test_inspector_rejects_invalid_controller_hooks_and_bjson(tmp_path: Path):
    root = ProjectGenerator().generate("broken", tmp_path)
    controller = root / "app" / "controllers" / "private_controller.py"
    controller.write_text(
        """from app.controllers.application_controller import ApplicationController


class PrivateController(ApplicationController):
    middlewares = ["require_auth"]
    public_actions = ("missing",)

    def before_action(self):
        return None
""",
        encoding="utf-8",
    )
    view = root / "app" / "views" / "posts" / "show.bjson"
    view.parent.mkdir(parents=True)
    view.write_text('{"title": post.title.upper()}', encoding="utf-8")

    text = "\n".join(str(item) for item in ConventionInspector(root).inspect())
    assert "before_action must be asynchronous" in text
    assert "middleware lists are not a Bingo convention" in text
    assert "unknown actions: missing" in text
    assert "forbidden expression Call" in text


def test_inspector_rejects_non_canonical_application_layers(tmp_path: Path):
    root = ProjectGenerator().generate("layered", tmp_path)
    service = root / "app" / "services" / "posts.py"
    service.parent.mkdir(parents=True)
    service.write_text("def create():\n    pass\n", encoding="utf-8")

    violations = ConventionInspector(root).inspect()
    assert any("non-canonical application layer" in item.problem for item in violations)
