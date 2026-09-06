from pathlib import Path

import httpx
import pytest

from bingo import Application, Controller, Router


class PagesController(Controller):
    async def index(self):
        return self.render("index.html", greeting=self.query.get("greeting", "Hello"))

    async def create(self):
        return self.json(
            {
                "method": self.request.method,
                "title": self.request.data.get("title"),
                "cookie": self.request.cookies.get("flavor"),
            },
            status=201,
        )

    async def show(self):
        return self.json({"id": self.params["id"]})

    async def redirect_home(self):
        return self.redirect("/")


class ThingsController(Controller):
    async def index(self):
        return self.json({"action": "index"})

    async def show(self):
        return self.json({"action": "show"})

    async def new(self):
        return self.json({"action": "new"})

    async def create(self):
        return self.json({"action": "create"})

    async def edit(self):
        return self.json({"action": "edit"})

    async def update(self):
        return self.json({"action": "update"})

    async def destroy(self):
        return self.json({"action": "destroy"})


class GuardedController(Controller):
    async def before_action(self):
        if self.query.get("blocked") == "yes":
            return self.json({"blocked": self.action}, status=403)
        return None

    async def index(self):
        return self.json({"action": self.action})


@pytest.fixture
def web_app(tmp_path: Path):
    views = tmp_path / "app" / "views"
    views.mkdir(parents=True)
    (views / "index.html").write_text("<h1>{{ greeting }}</h1>", encoding="utf-8")

    routes = Router()
    routes.get("/", PagesController.index)
    routes.post("/pages", PagesController.create)
    routes.get("/pages/:id", PagesController.show)
    routes.get("/redirect", PagesController.redirect_home)
    return Application(routes, root_path=tmp_path)


@pytest.mark.asyncio
async def test_explicit_routes_render_parse_requests_and_redirect(web_app):
    transport = httpx.ASGITransport(app=web_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"flavor": "vanilla"},
    ) as client:
        response = await client.get("/?greeting=Welcome")
        assert response.status_code == 200
        assert "<h1>Welcome</h1>" in response.text

        response = await client.post("/pages", data={"title": "Readable code"})
        assert response.status_code == 201
        assert response.json() == {
            "method": "POST",
            "title": "Readable code",
            "cookie": "vanilla",
        }

        assert (await client.get("/pages/42")).json() == {"id": "42"}
        response = await client.get("/redirect", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert (await client.get("/missing")).status_code == 404


def test_resources_create_html_and_json_routes_from_seven_actions():
    routes = Router()
    routes.resources("/things", ThingsController)

    assert [
        (route.method, route.path, route.action) for route in routes.definitions
    ] == [
        ("GET", "/things", "index"),
        ("GET", "/things.json", "index"),
        ("GET", "/things/new", "new"),
        ("POST", "/things", "create"),
        ("POST", "/things.json", "create"),
        ("GET", "/things/:id.json", "show"),
        ("GET", "/things/:id", "show"),
        ("GET", "/things/:id/edit", "edit"),
        ("PATCH", "/things/:id.json", "update"),
        ("PATCH", "/things/:id", "update"),
        ("DELETE", "/things/:id.json", "destroy"),
        ("DELETE", "/things/:id", "destroy"),
    ]


@pytest.mark.asyncio
async def test_before_action_can_continue_or_stop_dispatch(tmp_path: Path):
    routes = Router()
    routes.get("/guarded", GuardedController.index)
    application = Application(routes, root_path=tmp_path)

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/guarded")).json() == {"action": "index"}
        blocked = await client.get("/guarded?blocked=yes")
        assert blocked.status_code == 403
        assert blocked.json() == {"blocked": "index"}
