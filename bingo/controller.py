from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse, RedirectResponse

from bingo.request import Request
from bingo.templates import TemplateEngine


class Controller:
    """Base class for every Bingo controller."""

    public_actions: tuple[str, ...] = ()

    def __init__(
        self,
        request: Request,
        templates: TemplateEngine,
        params: dict[str, str],
        query: dict[str, str],
        action: str,
    ) -> None:
        self.request = request
        self.params = params
        self.query = query
        self.session = request.session
        self.action = action
        self.validation = None
        self._templates = templates

    async def before_action(self):
        return None

    def render(self, template: str, *, status: int = 200, **context: Any):
        return self._templates.render(
            template,
            request_format=self.request.format,
            status=status,
            context=context,
        )

    def redirect(self, location: str, *, status: int = 303):
        return RedirectResponse(location, status_code=status)

    def json(self, data: Any, *, status: int = 200):
        return JSONResponse(data, status_code=status)
