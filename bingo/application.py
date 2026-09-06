from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import PlainTextResponse

from bingo.db.database import database
from bingo.exceptions import BingoError, BingoNotFoundError, BingoValidationError
from bingo.routing import Router
from bingo.templates import TemplateEngine


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
    debug = False
    secret_key = "development-only-change-me"

    def __init__(
        self,
        routes: Router | None = None,
        *,
        root_path: str | Path | None = None,
        database_url: str | None = None,
    ) -> None:
        self.root_path = Path(root_path or Path.cwd()).resolve()
        self.router = routes or Router()
        self.templates = TemplateEngine(self.root_path / "app" / "views")

        if database_url:
            database.configure(database_url)

        middleware = [Middleware(SessionMiddleware, secret_key=self.secret_key)]
        starlette = Starlette(
            debug=self.debug,
            routes=self.router.starlette_routes(self),
            middleware=middleware,
            exception_handlers={
                BingoNotFoundError: self._not_found,
                BingoValidationError: self._validation_error,
                BingoError: self._bingo_error,
            },
        )
        self.asgi = MethodOverrideMiddleware(starlette)

    async def __call__(self, scope, receive, send) -> None:
        await self.asgi(scope, receive, send)

    async def _not_found(self, request, error: BingoNotFoundError):
        return PlainTextResponse(str(error), status_code=404)

    async def _validation_error(self, request, error: BingoValidationError):
        return PlainTextResponse(str(error), status_code=422)

    async def _bingo_error(self, request, error: BingoError):
        return PlainTextResponse(str(error), status_code=500)
