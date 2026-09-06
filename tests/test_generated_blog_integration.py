import importlib
import sys
from pathlib import Path

import httpx
import pytest

from bingo.db import MigrationRunner
from bingo.generators import ProjectGenerator, ResourceGenerator


@pytest.mark.asyncio
async def test_generated_blog_performs_complete_post_crud(
    tmp_path: Path,
    monkeypatch,
    clear_generated_modules,
):
    root = ProjectGenerator().generate("blog", tmp_path)
    ResourceGenerator(root).generate(
        "Post", ["title:string", "body:text", "published:boolean"]
    )
    monkeypatch.chdir(root)
    sys.path.insert(0, str(root))

    module = importlib.import_module("config.application")
    await MigrationRunner(root / "db" / "migrations").migrate()
    application = module.app

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        welcome = await client.get("/")
        assert welcome.status_code == 200
        assert "Your application is running." in welcome.text
        assert 'href="/public/application.css"' in welcome.text

        assert (await client.get("/posts")).status_code == 200
        new = await client.get("/posts/new")
        assert new.status_code == 200
        assert "<textarea" in new.text

        invalid = await client.post(
            "/posts",
            data={"title": "Keep me", "body": "", "published": "false"},
        )
        assert invalid.status_code == 422
        assert "is required" in invalid.text
        assert 'value="Keep me"' in invalid.text
        assert '<ul class="errors">' in invalid.text

        created = await client.post(
            "/posts",
            data={"title": "Hello", "body": "A useful post", "published": "true"},
            follow_redirects=False,
        )
        assert created.status_code == 303
        assert created.headers["location"] == "/posts/1"

        shown = await client.get("/posts/1")
        assert shown.status_code == 200
        assert "Hello" in shown.text

        edited = await client.get("/posts/1/edit")
        assert edited.status_code == 200
        assert 'value="Hello"' in edited.text

        invalid_update = await client.post(
            "/posts/1",
            data={
                "_method": "PATCH",
                "title": "Keep this too",
                "body": "",
                "published": "false",
            },
        )
        assert invalid_update.status_code == 422
        assert 'value="Keep this too"' in invalid_update.text
        assert "is required" in invalid_update.text

        updated = await client.post(
            "/posts/1",
            data={
                "_method": "PATCH",
                "title": "Updated",
                "body": "Still a useful post",
                "published": "false",
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303
        assert "Updated" in (await client.get("/posts/1")).text

        deleted = await client.post(
            "/posts/1", data={"_method": "DELETE"}, follow_redirects=False
        )
        assert deleted.status_code == 303
        assert deleted.headers["location"] == "/posts"
        assert (await client.get("/posts/1")).status_code == 404

        assert (await client.get("/posts.json")).json() == {"posts": []}

        invalid_json = await client.post(
            "/posts.json",
            json={"title": "", "body": "", "published": False},
        )
        assert invalid_json.status_code == 422
        assert invalid_json.json() == {
            "errors": {
                "title": ["is required"],
                "body": ["is required"],
            }
        }

        created_json = await client.post(
            "/posts.json",
            json={
                "title": "JSON post",
                "body": "Created over JSON",
                "published": True,
            },
        )
        assert created_json.status_code == 201
        post_id = created_json.json()["post"]["id"]
        assert created_json.json()["post"]["title"] == "JSON post"

        shown_json = await client.get(f"/posts/{post_id}.json")
        assert shown_json.status_code == 200
        assert shown_json.json()["post"]["published"] is True

        invalid_json_update = await client.patch(
            f"/posts/{post_id}.json",
            json={"title": "", "body": "", "published": False},
        )
        assert invalid_json_update.status_code == 422
        assert invalid_json_update.json()["errors"]["title"] == ["is required"]

        updated_json = await client.patch(
            f"/posts/{post_id}.json",
            json={
                "title": "Updated JSON post",
                "body": "Updated over JSON",
                "published": False,
            },
        )
        assert updated_json.status_code == 200
        assert updated_json.json()["post"]["title"] == "Updated JSON post"

        deleted_json = await client.delete(f"/posts/{post_id}.json")
        assert deleted_json.status_code == 200
        assert deleted_json.json() == {"deleted": True}
        assert (await client.get(f"/posts/{post_id}.json")).status_code == 404

    sys.path.remove(str(root))
    clear_generated_modules()
