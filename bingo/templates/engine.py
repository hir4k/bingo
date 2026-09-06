import ast
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape
from markupsafe import Markup
from starlette.responses import HTMLResponse, JSONResponse

from bingo.exceptions import BingoJSONViewError, BingoNotFoundError
from bingo.forms import Form


class TemplateEngine:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.environment = Environment(
            loader=FileSystemLoader(root),
            autoescape=select_autoescape(("html", "xml")),
            enable_async=False,
        )
        self.environment.globals["safe"] = Markup
        self.environment.globals["form"] = Form

    def render(
        self,
        template_name: str,
        *,
        request_format: str = "html",
        status: int = 200,
        context: dict[str, Any] | None = None,
    ):
        view_name, selected_format = self._resolve_format(
            template_name,
            request_format,
        )
        if selected_format == "html":
            return self._render_html(view_name, status, context or {})
        return self._render_json(view_name, status, context or {})

    def _resolve_format(self, view_name: str, request_format: str) -> tuple[str, str]:
        explicit_format = None
        if view_name.endswith(".html"):
            view_name = view_name.removesuffix(".html")
            explicit_format = "html"
        elif view_name.endswith(".json"):
            view_name = view_name.removesuffix(".json")
            explicit_format = "json"
        elif Path(view_name).suffix:
            suffix = Path(view_name).suffix
            raise BingoNotFoundError(
                f"Unsupported view format {suffix!r} in {view_name!r}. "
                "Bingo render targets support only .html and .json."
            )

        selected_format = explicit_format or request_format
        if explicit_format and explicit_format != request_format:
            raise BingoNotFoundError(
                f"The request expects {request_format}, but the controller explicitly "
                f"rendered {explicit_format}. Remove the extension to follow the "
                "request format or request the matching URL."
            )
        return view_name, selected_format

    def _render_html(
        self,
        view_name: str,
        status: int,
        context: dict[str, Any],
    ) -> HTMLResponse:
        template_name = f"{view_name}.html"
        try:
            template = self.environment.get_template(template_name)
        except TemplateNotFound as error:
            raise BingoNotFoundError(
                f"HTML view {template_name!r} was not found. Expected "
                f"{self.root / template_name}."
            ) from error
        return HTMLResponse(template.render(**context), status_code=status)

    def _render_json(
        self,
        view_name: str,
        status: int,
        context: dict[str, Any],
    ) -> JSONResponse:
        relative_path = Path(f"{view_name}.bjson")
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            raise BingoNotFoundError(
                f"JSON view {relative_path} was not found. Expected {path}."
            )

        expression = self.validate_json_view(path)
        namespace = {"__builtins__": {}, **context}
        try:
            value = eval(compile(expression, path, "eval"), namespace, {})
        except Exception as error:
            raise BingoJSONViewError(
                f"Could not render {path}: {type(error).__name__}: {error}"
            ) from error
        return JSONResponse(self._json_value(value, path), status_code=status)

    def validate_json_view(self, path: Path) -> ast.Expression:
        source = path.read_text(encoding="utf-8")
        return self._parse_json_view(path, source)

    def _parse_json_view(self, path: Path, source: str) -> ast.Expression:
        try:
            expression = ast.parse(source, filename=str(path), mode="eval")
        except SyntaxError as error:
            raise BingoJSONViewError(
                f"{path} must contain one valid Bingo JSON expression. "
                f"Line {error.lineno}: {error.msg}."
            ) from error

        forbidden = (
            ast.Await,
            ast.Call,
            ast.DictComp,
            ast.GeneratorExp,
            ast.Lambda,
            ast.NamedExpr,
            ast.Set,
            ast.SetComp,
            ast.Yield,
            ast.YieldFrom,
        )
        for node in ast.walk(expression):
            if isinstance(node, forbidden):
                name = type(node).__name__
                raise BingoJSONViewError(
                    f"{path} uses forbidden expression {name}. Bingo JSON views "
                    "may shape data but cannot call functions or perform application work."
                )
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                raise BingoJSONViewError(
                    f"{path} cannot access private attribute {node.attr!r}."
                )
            if isinstance(node, ast.Name) and node.id.startswith("_"):
                raise BingoJSONViewError(
                    f"{path} cannot access private name {node.id!r}."
                )
        return expression

    def _json_value(self, value: Any, path: Path):
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, Decimal | UUID | Path):
            return str(value)
        if isinstance(value, list | tuple):
            return [self._json_value(item, path) for item in value]
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise BingoJSONViewError(
                    f"{path} returned a dictionary with a non-string key."
                )
            return {key: self._json_value(item, path) for key, item in value.items()}
        raise BingoJSONViewError(
            f"{path} returned {type(value).__name__}, which is not JSON-compatible. "
            "Select model fields explicitly in the view."
        )
