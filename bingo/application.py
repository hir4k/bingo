from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route, WebSocketRoute

from bingo.channels import ChannelServer, close_channel_brokers
from bingo.db.database import database
from bingo.exceptions import BingoError, BingoNotFoundError, BingoValidationError
from bingo.routing import Router
from bingo.settings import settings
from bingo.templates import TemplateEngine


@asynccontextmanager
async def application_lifespan(_application):
    yield

    from bingo.tasks import close_task_queues

    await close_task_queues()
    await close_channel_brokers()


class MethodOverrideMiddleware:
    """Let ordinary HTML forms reach canonical PATCH and DELETE routes."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        headers = dict(scope.get("headers", []))
        content_type = headers.get(b"content-type", b"").decode("latin-1")
        is_form_post = (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and content_type.startswith("application/x-www-form-urlencoded")
        )
        if not is_form_post:
            await self.app(scope, receive, send)
            return

        body = b""
        more_body = True
        while more_body:
            message = await receive()
            body += message.get("body", b"")
            more_body = message.get("more_body", False)

        form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        override = form.get("_method", [""])[-1].upper()
        if override in {"PATCH", "PUT", "DELETE"}:
            scope = {**scope, "method": override}

        delivered = False

        async def replay_body():
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_body, send)


class Application:
    def __init__(
        self,
        routes: Router | None = None,
        *,
        root_path: str | Path | None = None,
    ) -> None:
        self.root_path = Path(root_path or Path.cwd()).resolve()
        self.settings = settings.load(self.root_path)
        self.router = routes or Router()
        self.templates = TemplateEngine(self.root_path / "app" / "views")

        if self.settings.DATABASE_URL:
            database.configure(self.settings.DATABASE_URL)

        middleware = [
            Middleware(SessionMiddleware, secret_key=self.settings.SECRET_KEY)
        ]
        channel_routes = self._channel_routes()
        starlette = Starlette(
            debug=self.settings.DEBUG,
            routes=[*channel_routes, *self.router.starlette_routes(self)],
            middleware=middleware,
            lifespan=application_lifespan,
            exception_handlers={
                BingoNotFoundError: self._not_found,
                BingoValidationError: self._validation_error,
                BingoError: self._bingo_error,
            },
        )
        self.asgi = MethodOverrideMiddleware(starlette)

    def _channel_routes(self):
        path = self.settings.CHANNEL_PATH
        is_valid_path = isinstance(path, str) and path.startswith("/")
        is_valid_path = is_valid_path and not path.startswith("//")
        is_valid_path = is_valid_path and not path.endswith("/") and path != "/"
        if not is_valid_path:
            raise BingoError(
                "CHANNEL_PATH must start with '/' and must not end with '/'."
            )

        javascript = Path(__file__).with_name("channels.js").read_text(encoding="utf-8")

        async def client(_request):
            return Response(javascript, media_type="application/javascript")

        channel_server = ChannelServer(self.root_path)
        return [
            Route(f"{path}.js", client, methods=["GET"]),
            WebSocketRoute(path, channel_server.handle),
        ]

    async def __call__(self, scope, receive, send) -> None:
        await self.asgi(scope, receive, send)

    async def _not_found(self, request, error: BingoNotFoundError):
        return PlainTextResponse(str(error), status_code=404)

    async def _validation_error(self, request, error: BingoValidationError):
        return PlainTextResponse(str(error), status_code=422)

    async def _bingo_error(self, request, error: BingoError):
        return PlainTextResponse(str(error), status_code=500)
