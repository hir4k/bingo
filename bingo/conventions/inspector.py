from __future__ import annotations

import ast
from pathlib import Path

from bingo.conventions.errors import ConventionViolation
from bingo.db.naming import pluralize
from bingo.exceptions import BingoJSONViewError
from bingo.templates import TemplateEngine

RESOURCE_ACTIONS = {"index", "show", "new", "create", "edit", "update", "destroy"}


class ConventionInspector:
    REQUIRED = (
        "app/controllers/application_controller.py",
        "app/models/__init__.py",
        "app/validators/__init__.py",
        "app/views/layouts/application.html",
        "config/application.py",
        "config/database.py",
        "config/routes.py",
        "db/migrations",
        "public",
        "tests",
        "BINGO.md",
    )

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()

    def inspect(self) -> list[ConventionViolation]:
        violations = self._missing_paths()
        violations.extend(self._controller_violations())
        violations.extend(self._misplaced_files())
        violations.extend(self._json_view_violations())
        violations.extend(self._forbidden_architecture())
        return violations

    def _missing_paths(self) -> list[ConventionViolation]:
        violations = []
        for relative in self.REQUIRED:
            path = self.root / relative
            if path.exists():
                continue
            violations.append(
                ConventionViolation(
                    path=path,
                    problem="A required Bingo project path is missing.",
                    expected=relative,
                    fix=f"Create {relative} or regenerate the project with `bingo new`.",
                )
            )
        return violations

    def _controller_violations(self) -> list[ConventionViolation]:
        directory = self.root / "app" / "controllers"
        if not directory.is_dir():
            return []

        violations = []
        resource_controllers = self._resource_controllers()
        for path in directory.glob("*.py"):
            if path.name == "__init__.py":
                continue
            if not path.name.endswith("_controller.py"):
                violations.append(
                    ConventionViolation(
                        path=path,
                        problem="Controller filenames must end in `_controller.py`.",
                        expected="A plural resource name such as posts_controller.py.",
                        fix=f"Rename {path.name} to {path.stem}_controller.py.",
                    )
                )
                continue
            violations.extend(
                self._inspect_controller(
                    path,
                    resource_controllers=resource_controllers,
                )
            )
        return violations

    def _inspect_controller(
        self,
        path: Path,
        *,
        resource_controllers: set[str],
    ) -> list[ConventionViolation]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as error:
            return [
                ConventionViolation(
                    path=path,
                    problem=f"The controller is not valid Python: {error.msg}.",
                    expected="A Python module containing one controller class.",
                    fix="Fix the syntax error, then run `bingo inspect` again.",
                )
            ]

        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        expected_resource = path.name.removesuffix("_controller.py")
        expected_class = (
            "".join(part.capitalize() for part in expected_resource.split("_"))
            + "Controller"
        )
        if len(classes) != 1 or classes[0].name != expected_class:
            found = ", ".join(node.name for node in classes) or "no class"
            return [
                ConventionViolation(
                    path=path,
                    problem=f"Found {found}; the filename and controller class disagree.",
                    expected=f"Exactly one class named {expected_class}.",
                    fix=f"Rename the class to {expected_class}.",
                )
            ]

        controller_class = classes[0]
        violations = self._controller_class_violations(path, controller_class)
        is_resource = controller_class.name in resource_controllers
        singular = not expected_resource.endswith("s")
        if is_resource and singular:
            plural = pluralize(expected_resource)
            violations.append(
                ConventionViolation(
                    path=path,
                    problem="Resource controller filenames must use a plural resource name.",
                    expected=f"{plural}_controller.py",
                    fix=f"Rename {path.name} to {plural}_controller.py and rename its class.",
                )
            )
        if is_resource:
            violations.extend(
                self._resource_violations(path, expected_resource, controller_class)
            )
        return violations

    def _controller_class_violations(
        self,
        path: Path,
        controller: ast.ClassDef,
    ) -> list[ConventionViolation]:
        violations = []
        for item in controller.body:
            is_before_action = getattr(item, "name", None) == "before_action"
            if is_before_action and isinstance(item, ast.FunctionDef):
                violations.append(
                    ConventionViolation(
                        path=path,
                        problem="before_action must be asynchronous.",
                        expected="async def before_action(self): ...",
                        fix="Change before_action from def to async def.",
                    )
                )

            if not isinstance(item, ast.Assign):
                continue
            names = {
                target.id for target in item.targets if isinstance(target, ast.Name)
            }
            if names & {"middleware", "middlewares"}:
                violations.append(
                    ConventionViolation(
                        path=path,
                        problem="Controller middleware lists are not a Bingo convention.",
                        expected="One async before_action method on an application base controller.",
                        fix="Move the checks into before_action and call them explicitly in order.",
                    )
                )
            if "public_actions" in names:
                violations.extend(
                    self._public_action_violations(path, controller, item)
                )
        return violations

    def _public_action_violations(
        self,
        path: Path,
        controller: ast.ClassDef,
        assignment: ast.Assign,
    ) -> list[ConventionViolation]:
        if not isinstance(assignment.value, ast.Tuple | ast.List):
            return [
                ConventionViolation(
                    path=path,
                    problem="public_actions must be a tuple of action names.",
                    expected='public_actions = ("index", "show")',
                    fix="Replace the value with a tuple containing declared action names.",
                )
            ]

        values = []
        for item in assignment.value.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                return [
                    ConventionViolation(
                        path=path,
                        problem="public_actions contains a non-string value.",
                        expected="A tuple containing action names as strings.",
                        fix="Replace every value with the name of a controller action.",
                    )
                ]
            values.append(item.value)

        declared = {
            item.name
            for item in controller.body
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        allowed = RESOURCE_ACTIONS | declared
        unknown = sorted(set(values) - allowed)
        if not unknown:
            return []
        names = ", ".join(unknown)
        return [
            ConventionViolation(
                path=path,
                problem=f"public_actions contains unknown actions: {names}.",
                expected="Only canonical resource actions or declared controller actions.",
                fix=f"Remove or implement: {names}.",
            )
        ]

    def _resource_violations(
        self,
        path: Path,
        resource: str,
        controller: ast.ClassDef,
    ) -> list[ConventionViolation]:
        violations = []
        declared = {
            item.name
            for item in controller.body
            if isinstance(item, ast.AsyncFunctionDef)
        }
        missing_actions = sorted(RESOURCE_ACTIONS - declared)
        if missing_actions:
            names = ", ".join(missing_actions)
            violations.append(
                ConventionViolation(
                    path=path,
                    problem=f"The resource controller is missing actions: {names}.",
                    expected="All seven canonical async resource actions.",
                    fix=f"Add async controller methods for: {names}.",
                )
            )

        view_root = self.root / "app" / "views" / resource
        expected_views = (
            "index.html",
            "index.bjson",
            "show.html",
            "show.bjson",
            "new.html",
            "edit.html",
        )
        for name in expected_views:
            view = view_root / name
            if view.is_file():
                continue
            violations.append(
                ConventionViolation(
                    path=view,
                    problem="A conventional resource view is missing.",
                    expected=f"app/views/{resource}/{name}",
                    fix=f"Create {view} or regenerate the resource.",
                )
            )
        return violations

    def _resource_controllers(self) -> set[str]:
        routes_path = self.root / "config" / "routes.py"
        if not routes_path.is_file():
            return set()
        try:
            tree = ast.parse(routes_path.read_text(encoding="utf-8"))
        except SyntaxError:
            return set()

        controllers = set()
        for node in ast.walk(tree):
            is_resources_call = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "resources"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Name)
            )
            if is_resources_call:
                controllers.add(node.args[1].id)
        return controllers

    def _misplaced_files(self) -> list[ConventionViolation]:
        violations = []
        app = self.root / "app"
        if not app.is_dir():
            return violations
        correct = self.root / "app" / "controllers"
        for path in app.rglob("*_controller.py"):
            if path.parent == correct:
                continue
            violations.append(
                ConventionViolation(
                    path=path,
                    problem="A controller is outside app/controllers/.",
                    expected="All controller modules in app/controllers/.",
                    fix=f"Move {path.name} to app/controllers/{path.name}.",
                )
            )
        return violations

    def _json_view_violations(self) -> list[ConventionViolation]:
        views = self.root / "app" / "views"
        if not views.is_dir():
            return []
        engine = TemplateEngine(views)
        violations = []
        for path in views.rglob("*.bjson"):
            try:
                engine.validate_json_view(path)
            except BingoJSONViewError as error:
                violations.append(
                    ConventionViolation(
                        path=path,
                        problem=str(error),
                        expected="One restricted Python expression that returns JSON-compatible data.",
                        fix="Remove calls or statements and leave only data-shaping expressions.",
                    )
                )
        return violations

    def _forbidden_architecture(self) -> list[ConventionViolation]:
        forbidden = {
            "services": "Keep resource workflow orchestration in controllers.",
            "presenters": "Use colocated .bjson resource views.",
            "serializers": "Use colocated .bjson resource views.",
        }
        violations = []
        for directory, fix in forbidden.items():
            path = self.root / "app" / directory
            files = list(path.rglob("*.py")) if path.is_dir() else []
            files = [file for file in files if file.name != "__init__.py"]
            if not files:
                continue
            violations.append(
                ConventionViolation(
                    path=path,
                    problem=f"app/{directory}/ introduces a non-canonical application layer.",
                    expected="Controllers, models, validators, and format-specific views.",
                    fix=fix,
                )
            )
        return violations
