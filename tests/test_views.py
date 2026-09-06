from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from bingo import Application, Controller, Router


class ViewController(Controller):
    async def index(self):
        items = [SimpleNamespace(name="Notebook", price=Decimal("12.50"))]
        return self.render(
            "items/index",
            items=items,
            published_on=date(2026, 9, 6),
        )

    async def html_only(self):
        return self.render("items/index.html", items=[], published_on=None)

    async def missing(self):
        return self.render("items/missing")


def make_views(root: Path) -> None:
    views = root / "app" / "views" / "items"
    views.mkdir(parents=True)
    (views / "index.html").write_text(
        "{% for item in items %}{{ item.name }}{% endfor %}", encoding="utf-8"
    )
    (views / "index.bjson").write_text(
        """{
    "items": [
        {"name": item.name, "price": item.price}
        for item in items
    ],
    "published_on": published_on,
}
""",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_render_selects_html_or_bjson_from_the_route_format(tmp_path: Path):
    make_views(tmp_path)
    routes = Router()
    routes.get("/items", ViewController.index)
    routes.get("/items.json", ViewController.index)
    routes.get("/html-only.json", ViewController.html_only)
    routes.get("/missing.json", ViewController.missing)
    application = Application(routes, root_path=tmp_path)

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        html = await client.get("/items")
        assert html.status_code == 200
        assert "Notebook" in html.text

        json = await client.get("/items.json")
        assert json.status_code == 200
        assert json.json() == {
            "items": [{"name": "Notebook", "price": "12.50"}],
            "published_on": "2026-09-06",
        }

        mismatch = await client.get("/html-only.json")
        assert mismatch.status_code == 404
        assert "explicitly rendered html" in mismatch.text

        missing = await client.get("/missing.json")
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_bjson_rejects_function_calls(tmp_path: Path):
    make_views(tmp_path)
    view = tmp_path / "app" / "views" / "items" / "index.bjson"
    view.write_text(
        '{"names": [item.name.upper() for item in items]}', encoding="utf-8"
    )
    routes = Router()
    routes.get("/items.json", ViewController.index)
    application = Application(routes, root_path=tmp_path)

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/items.json")

    assert response.status_code == 500
    assert "forbidden expression Call" in response.text
