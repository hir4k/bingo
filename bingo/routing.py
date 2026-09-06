from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from starlette.routing import Route

from bingo.controller import Controller
from bingo.exceptions import BingoRouteError, BingoValidationError
from bingo.request import Request


@dataclass(frozen=True)
class RouteDefinition:
    method: str
    path: str
    controller: type[Controller]
    action: str
    format: str = "html"

    @property
    def target(self) -> str:
        return f"{self.controller.__name__}.{self.action}"


def _controller_for(action: Callable[..., Any]) -> type[Controller]:
    parts = action.__qualname__.split(".")
    if len(parts) != 2:
        raise BingoRouteError(
            "Routes must point to a controller class action, for example "
            "PostsController.index."
        )

    module = importlib.import_module(action.__module__)
    controller = getattr(module, parts[0], None)
    if not isinstance(controller, type) or not issubclass(controller, Controller):
        raise BingoRouteError(
            f"{parts[0]} must be a class that inherits from bingo.Controller."
        )
    return controller


class Router:
    RESOURCE_ACTIONS = (
        ("GET", "", "index", ("html", "json")),
        ("GET", "/new", "new", ("html",)),
        ("POST", "", "create", ("html", "json")),
        ("GET", "/:id", "show", ("json", "html")),
        ("GET", "/:id/edit", "edit", ("html",)),
        ("PATCH", "/:id", "update", ("json", "html")),
        ("DELETE", "/:id", "destroy", ("json", "html")),
    )

    def __init__(self) -> None:
        self.definitions: list[RouteDefinition] = []

    def get(self, path: str, action: Callable[..., Any]) -> None:
        self._add("GET", path, action)

    def post(self, path: str, action: Callable[..., Any]) -> None:
        self._add("POST", path, action)

    def put(self, path: str, action: Callable[..., Any]) -> None:
        self._add("PUT", path, action)

    def patch(self, path: str, action: Callable[..., Any]) -> None:
        self._add("PATCH", path, action)

    def delete(self, path: str, action: Callable[..., Any]) -> None:
        self._add("DELETE", path, action)

    def resources(self, path: str, controller: type[Controller]) -> None:
        missing = [
            action
            for _, _, action, _ in self.RESOURCE_ACTIONS
            if not hasattr(controller, action)
        ]
        if missing:
            names = ", ".join(missing)
            raise BingoRouteError(
                f"{controller.__name__} is missing resource actions: {names}. "
                "Define all seven canonical resource actions."
            )

        base = path.rstrip("/") or "/"
        for method, suffix, action, formats in self.RESOURCE_ACTIONS:
            resource_path = (
                f"{base}{suffix}" if base != "/" else f"/{suffix.lstrip('/')}"
            )
            for response_format in formats:
                path = _format_path(resource_path, response_format)
                self.definitions.append(
                    RouteDefinition(
                        method,
                        path,
                        controller,
                        action,
                        response_format,
                    )
                )

    def _add(self, method: str, path: str, action: Callable[..., Any]) -> None:
        controller = _controller_for(action)
        response_format = "json" if path.endswith(".json") else "html"
        self.definitions.append(
            RouteDefinition(method, path, controller, action.__name__, response_format)
        )

    def starlette_routes(self, application) -> list[Route]:
        return [self._starlette_route(item, application) for item in self.definitions]

    def _starlette_route(self, item: RouteDefinition, application) -> Route:
        async def endpoint(starlette_request):
            request = await Request.from_starlette(
                starlette_request,
                response_format=item.format,
            )
            controller = item.controller(
                request=request,
                templates=application.templates,
                params=dict(starlette_request.path_params),
                query=dict(starlette_request.query_params),
                action=item.action,
            )
            before_response = await controller.before_action()
            if before_response is not None:
                return before_response
            try:
                return await getattr(controller, item.action)()
            except BingoValidationError as error:
                return await self._validation_response(controller, item, error)

        starlette_path = _to_starlette_path(item.path)
        return Route(starlette_path, endpoint, methods=[item.method])

    async def _validation_response(
        self,
        controller: Controller,
        route: RouteDefinition,
        error: BingoValidationError,
    ):
        if route.format == "json":
            return controller.json({"errors": error.errors}, status=422)

        form_action = {"create": "new", "update": "edit"}.get(route.action)
        if form_action is None:
            raise error

        controller.validation = error.validator
        response = await getattr(controller, form_action)()
        response.status_code = 422
        return response


def _to_starlette_path(path: str) -> str:
    import re

    return re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"{\1}", path)


def _format_path(path: str, response_format: str) -> str:
    if response_format == "html":
        return path
    return f"{path}.json"
