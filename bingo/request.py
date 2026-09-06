from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from starlette.requests import Request as StarletteRequest


class Request:
    """The single request interface exposed to controller actions."""

    def __init__(
        self,
        request: StarletteRequest,
        *,
        response_format: str = "html",
        data: Mapping[str, Any] | None = None,
        json_data: Any = None,
    ) -> None:
        self._request = request
        self.format = response_format
        self.data = dict(data or {})
        self.json = json_data

    @classmethod
    async def from_starlette(
        cls,
        request: StarletteRequest,
        *,
        response_format: str = "html",
    ) -> Request:
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            try:
                json_data = await request.json()
            except ValueError:
                json_data = None
            data = json_data if isinstance(json_data, Mapping) else {}
            return cls(
                request,
                response_format=response_format,
                data=data,
                json_data=json_data,
            )

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            form = await request.form()
            return cls(request, response_format=response_format, data=form)

        return cls(request, response_format=response_format, data={})

    @property
    def method(self) -> str:
        return self._request.method

    @property
    def path(self) -> str:
        return self._request.url.path

    @property
    def headers(self):
        return self._request.headers

    @property
    def cookies(self) -> dict[str, str]:
        return self._request.cookies

    @property
    def session(self) -> dict[str, Any]:
        return self._request.session
