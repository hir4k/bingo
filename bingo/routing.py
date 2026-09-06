from __future__ import annotations

import importlib
from collections.abc import Callable
from contextlib import contextmanager
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
    controller: type[Controller] | str
    action: str
    format: str = "html"
    resource: bool = False
    groups: tuple[str, ...] = ()

    @property
    def target(self) -> str:
        if isinstance(self.controller, str):
            controller_name = self.controller
        else:
            controller_name = self.controller.__name__
        parts = (*self.groups, controller_name, self.action)
        return ".".join(parts)


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
        self._groups: list[str] = []

    @contextmanager
    def group(self, path: str):
        name = path.removeprefix("/")
        has_one_leading_slash = path.startswith("/") and not path.startswith("//")
        is_one_segment = "/" not in name
        is_valid_name = (
            name.isidentifier() and not name.startswith("_") and name.lower() == name
        )
        if not has_one_leading_slash or not is_one_segment or not is_valid_name:
            raise BingoRouteError(
                f"Invalid route group {path!r}. Group paths must be one lowercase "
                "segment beginning with '/', such as '/admin' or '/staff_tools'."
            )

        self._groups.append(name)
        try:
            yield self
        finally:
            self._groups.pop()

    def get(self, path: str, action: Callable[..., Any] | str) -> None:
        self._add("GET", path, action)

    def post(self, path: str, action: Callable[..., Any] | str) -> None:
        self._add("POST", path, action)

    def put(self, path: str, action: Callable[..., Any] | str) -> None:
        self._add("PUT", path, action)

    def patch(self, path: str, action: Callable[..., Any] | str) -> None:
        self._add("PATCH", path, action)

    def delete(self, path: str, action: Callable[..., Any] | str) -> None:
        self._add("DELETE", path, action)

    def resources(
        self,
        path: str,
        controller: type[Controller] | str | None = None,
    ) -> None:
        controller = controller or _controller_name_for_path(path)
        if isinstance(controller, type):
            _require_resource_actions(controller)

        base = path.rstrip("/") or "/"
        for method, suffix, action, formats in self.RESOURCE_ACTIONS:
            resource_path = (
                f"{base}{suffix}" if base != "/" else f"/{suffix.lstrip('/')}"
            )
            for response_format in formats:
                formatted_path = _format_path(resource_path, response_format)
                self.definitions.append(
                    RouteDefinition(
                        method,
                        self._scoped_path(formatted_path),
                        controller,
                        action,
                        response_format,
                        True,
                        tuple(self._groups),
                    )
                )

    def _add(
        self,
        method: str,
        path: str,
        action: Callable[..., Any] | str,
    ) -> None:
        if isinstance(action, str):
            controller, action_name = _parse_target(action)
        else:
            controller = _controller_for(action)
            action_name = action.__name__
        response_format = "json" if path.endswith(".json") else "html"
        self.definitions.append(
            RouteDefinition(
                method,
                self._scoped_path(path),
                controller,
                action_name,
                response_format,
                groups=tuple(self._groups),
            )
        )

    def _scoped_path(self, path: str) -> str:
        path = path if path.startswith("/") else f"/{path}"
        if not self._groups:
            return path

        prefix = "/" + "/".join(self._groups)
        if path == "/":
            return prefix
        return f"{prefix}{path}"

    def starlette_routes(self, application) -> list[Route]:
        controllers: dict[tuple[tuple[str, ...], str], type[Controller]] = {}
        routes = []
        for item in sorted(self.definitions, key=_route_priority):
            controller = _resolve_controller(
                item.controller,
                item.groups,
                controllers,
            )
            if item.resource:
                _require_resource_actions(controller)
            if not hasattr(controller, item.action):
                raise BingoRouteError(
                    f"{controller.__name__} has no action {item.action!r}. "
                    f"Define it before routing to {item.target}."
                )
            routes.append(self._starlette_route(item, controller, application))
        return routes

    def _starlette_route(
        self,
        item: RouteDefinition,
        controller_class: type[Controller],
        application,
    ) -> Route:
        async def endpoint(starlette_request):
            request = await Request.from_starlette(
                starlette_request,
                response_format=item.format,
            )
            controller = controller_class(
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


def _parse_target(target: str) -> tuple[str, str]:
    parts = target.split(".")
    if len(parts) != 2 or not all(part.isidentifier() for part in parts):
        raise BingoRouteError(
            f"Invalid route target {target!r}. Expected 'PostsController.index'."
        )
    return parts[0], parts[1]


def _controller_name_for_path(path: str) -> str:
    resource = path.rstrip("/").rsplit("/", 1)[-1].replace("-", "_")
    if not resource.isidentifier() or resource.startswith("_"):
        raise BingoRouteError(
            f"Cannot infer a controller from resource path {path!r}. Use a plural "
            "resource name such as '/posts'."
        )
    class_name = "".join(part.capitalize() for part in resource.split("_"))
    return f"{class_name}Controller"


def _resolve_controller(
    controller: type[Controller] | str,
    groups: tuple[str, ...],
    cache: dict[tuple[tuple[str, ...], str], type[Controller]],
) -> type[Controller]:
    if isinstance(controller, type):
        return controller
    cache_key = (groups, controller)
    if cache_key in cache:
        return cache[cache_key]
    if not controller.endswith("Controller"):
        raise BingoRouteError(
            f"Route controller {controller!r} must end in 'Controller'."
        )

    module_stem = _snake_case(controller)
    module_name = ".".join(("app", "controllers", *groups, module_stem))
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise BingoRouteError(
            f"Could not import {controller} from {module_name}. "
            f"Define it in {module_name.replace('.', '/')}.py. "
            f"The import failed with: {error}"
        ) from error

    resolved = getattr(module, controller, None)
    if not isinstance(resolved, type) or not issubclass(resolved, Controller):
        raise BingoRouteError(
            f"{module_name} must define {controller} as a Bingo Controller class."
        )
    cache[cache_key] = resolved
    return resolved


def _require_resource_actions(controller: type[Controller]) -> None:
    missing = [
        action
        for _, _, action, _ in Router.RESOURCE_ACTIONS
        if not hasattr(controller, action)
    ]
    if not missing:
        return
    names = ", ".join(missing)
    raise BingoRouteError(
        f"{controller.__name__} is missing resource actions: {names}. "
        "Define all seven canonical resource actions."
    )


def _snake_case(name: str) -> str:
    import re

    first_pass = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first_pass).lower()


def _route_priority(route: RouteDefinition) -> tuple[int, int]:
    segments = [segment for segment in route.path.split("/") if segment]
    dynamic_segments = sum(segment.startswith(":") for segment in segments)
    return dynamic_segments, -len(segments)


def _format_path(path: str, response_format: str) -> str:
    if response_format == "html":
        return path
    return f"{path}.json"
