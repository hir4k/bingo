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
        "manage.py",
        "app/channels/__init__.py",
        "app/channels/application_channel.py",
        "app/channels/application_connection.py",
        "app/commands/__init__.py",
        "app/controllers/application_controller.py",
        "app/models/__init__.py",
        "app/tasks/__init__.py",
        "app/tasks/application_task.py",
        "app/validators/__init__.py",
        "app/views/layouts/application.html",
        "config/application.py",
        "config/routes.py",
        "config/settings/base.py",
        "config/settings/development.py",
        "config/settings/test.py",
        "config/settings/production.py",
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
        violations.extend(self._command_violations())
        violations.extend(self._task_violations())
        violations.extend(self._channel_violations())
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
        for path in directory.rglob("*.py"):
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
                    groups=path.parent.relative_to(directory).parts,
                    resource_controllers=resource_controllers,
                )
            )
        return violations

    def _inspect_controller(
        self,
        path: Path,
        *,
        groups: tuple[str, ...],
        resource_controllers: set[tuple[tuple[str, ...], str]],
    ) -> list[ConventionViolation]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as error:
            return [
                ConventionViolation(
                    path=path,
                    problem=f"The controller is not valid Python: {error.msg}.",
                    expected="A Python module containing one controller class.",
                    fix=(
                        "Fix the syntax error, then run `python manage.py inspect` "
                        "again."
                    ),
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
        is_resource = (groups, controller_class.name) in resource_controllers
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
                self._resource_violations(
                    path,
                    groups,
                    expected_resource,
                    controller_class,
                )
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
        groups: tuple[str, ...],
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

        view_root = self.root.joinpath("app", "views", *groups, resource)
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

    def _resource_controllers(self) -> set[tuple[tuple[str, ...], str]]:
        routes_path = self.root / "config" / "routes.py"
        if not routes_path.is_file():
            return set()
        try:
            tree = ast.parse(routes_path.read_text(encoding="utf-8"))
        except SyntaxError:
            return set()

        controllers: set[tuple[tuple[str, ...], str]] = set()

        def collect(statements: list[ast.stmt], groups: tuple[str, ...]) -> None:
            for node in statements:
                nested_group = self._group_from_with(node)
                if nested_group:
                    collect(node.body, (*groups, nested_group))
                    continue

                if not isinstance(node, ast.Expr) or not isinstance(
                    node.value, ast.Call
                ):
                    continue
                call = node.value
                is_resources_call = (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "resources"
                )
                if not is_resources_call or not call.args:
                    continue

                if len(call.args) >= 2 and isinstance(call.args[1], ast.Name):
                    controllers.add((groups, call.args[1].id))
                    continue
                path = (
                    call.args[0].value
                    if isinstance(call.args[0], ast.Constant)
                    else None
                )
                if not isinstance(path, str):
                    continue
                resource = path.rstrip("/").rsplit("/", 1)[-1].replace("-", "_")
                controller = "".join(part.capitalize() for part in resource.split("_"))
                controllers.add((groups, f"{controller}Controller"))

        collect(tree.body, ())
        return controllers

    def _group_from_with(self, node: ast.stmt) -> str | None:
        if not isinstance(node, ast.With) or len(node.items) != 1:
            return None
        expression = node.items[0].context_expr
        is_group_call = (
            isinstance(expression, ast.Call)
            and isinstance(expression.func, ast.Attribute)
            and expression.func.attr == "group"
            and len(expression.args) == 1
            and isinstance(expression.args[0], ast.Constant)
            and isinstance(expression.args[0].value, str)
        )
        if not is_group_call:
            return None
        path = expression.args[0].value
        return path.removeprefix("/")

    def _misplaced_files(self) -> list[ConventionViolation]:
        violations = []
        app = self.root / "app"
        if not app.is_dir():
            return violations
        correct = self.root / "app" / "controllers"
        for path in app.rglob("*_controller.py"):
            if path.is_relative_to(correct):
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

    def _command_violations(self) -> list[ConventionViolation]:
        directory = self.root / "app" / "commands"
        if not directory.is_dir():
            return []

        built_in_commands = {
            "generate",
            "inspect",
            "migrate",
            "rollback",
            "routes",
            "server",
            "worker",
        }
        violations = []
        for path in directory.glob("*.py"):
            if path.name == "__init__.py":
                continue
            if not path.stem.isidentifier() or path.stem.startswith("_"):
                violations.append(
                    ConventionViolation(
                        path=path,
                        problem="Command filenames must be Python identifiers.",
                        expected="A name such as publish_posts.py.",
                        fix=f"Rename {path.name} to a valid command name.",
                    )
                )
                continue
            if path.stem in built_in_commands:
                violations.append(
                    ConventionViolation(
                        path=path,
                        problem="The command conflicts with a built-in Bingo command.",
                        expected="A unique application command name.",
                        fix=f"Rename {path.name}.",
                    )
                )
                continue
            violations.extend(self._inspect_command(path))
        return violations

    def _inspect_command(self, path: Path) -> list[ConventionViolation]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as error:
            return [
                ConventionViolation(
                    path=path,
                    problem=f"The command is not valid Python: {error.msg}.",
                    expected="One class named Command.",
                    fix="Fix the syntax error, then run `python manage.py inspect`.",
                )
            ]

        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        command_classes = [node for node in classes if node.name == "Command"]
        has_one_command = len(classes) == 1 and len(command_classes) == 1
        if not has_one_command:
            return [
                ConventionViolation(
                    path=path,
                    problem="A command file must define exactly one Command class.",
                    expected="class Command(BaseCommand): ...",
                    fix="Remove other classes and name the command class Command.",
                )
            ]

        command = command_classes[0]
        inherits_base_command = any(
            isinstance(base, ast.Name) and base.id == "BaseCommand"
            for base in command.bases
        )
        if not inherits_base_command:
            return [
                ConventionViolation(
                    path=path,
                    problem="Command must inherit from Bingo BaseCommand.",
                    expected="class Command(BaseCommand): ...",
                    fix="Import BaseCommand from bingo and inherit from it.",
                )
            ]

        handles = [
            node for node in command.body if getattr(node, "name", None) == "handle"
        ]
        has_async_handle = len(handles) == 1 and isinstance(
            handles[0], ast.AsyncFunctionDef
        )
        if not has_async_handle:
            return [
                ConventionViolation(
                    path=path,
                    problem="Command must define one asynchronous handle method.",
                    expected="async def handle(self, ...): ...",
                    fix="Define handle with async def.",
                )
            ]

        handle = handles[0]
        parameters = [
            *handle.args.posonlyargs,
            *handle.args.args,
            *handle.args.kwonlyargs,
        ]
        if parameters and parameters[0].arg == "self":
            parameters = parameters[1:]
        untyped = [
            parameter.arg for parameter in parameters if parameter.annotation is None
        ]
        if not untyped:
            return []
        names = ", ".join(untyped)
        return [
            ConventionViolation(
                path=path,
                problem=f"Command parameters need type annotations: {names}.",
                expected="Typed parameters so Bingo can build the CLI.",
                fix=f"Add type annotations to: {names}.",
            )
        ]

    def _task_violations(self) -> list[ConventionViolation]:
        directory = self.root / "app" / "tasks"
        if not directory.is_dir():
            return []

        violations = []
        for path in directory.glob("*.py"):
            if path.name in {"__init__.py", "application_task.py"}:
                continue
            if not path.name.endswith("_task.py"):
                violations.append(
                    ConventionViolation(
                        path=path,
                        problem="Task filenames must end in `_task.py`.",
                        expected="A name such as send_welcome_email_task.py.",
                        fix=f"Rename {path.name} to {path.stem}_task.py.",
                    )
                )
                continue
            violations.extend(self._inspect_task(path))
        return violations

    def _inspect_task(self, path: Path) -> list[ConventionViolation]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as error:
            return [
                ConventionViolation(
                    path=path,
                    problem=f"The task is not valid Python: {error.msg}.",
                    expected="One conventional asynchronous task class.",
                    fix="Fix the syntax error, then run `python manage.py inspect`.",
                )
            ]

        expected_class = "".join(
            part.capitalize() for part in path.stem.split("_") if part
        )
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        has_expected_class = len(classes) == 1 and classes[0].name == expected_class
        if not has_expected_class:
            return [
                ConventionViolation(
                    path=path,
                    problem="The filename and task class disagree.",
                    expected=f"Exactly one class named {expected_class}.",
                    fix=f"Keep one class and name it {expected_class}.",
                )
            ]

        task = classes[0]
        inherits_application_task = any(
            isinstance(base, ast.Name) and base.id == "ApplicationTask"
            for base in task.bases
        )
        if not inherits_application_task:
            return [
                ConventionViolation(
                    path=path,
                    problem="Application tasks must inherit from ApplicationTask.",
                    expected=f"class {expected_class}(ApplicationTask): ...",
                    fix="Import and inherit from app.tasks.application_task.",
                )
            ]

        run_methods = [
            node for node in task.body if getattr(node, "name", None) == "run"
        ]
        has_async_run = len(run_methods) == 1 and isinstance(
            run_methods[0], ast.AsyncFunctionDef
        )
        if not has_async_run:
            return [
                ConventionViolation(
                    path=path,
                    problem="Task must define one asynchronous run method.",
                    expected="async def run(self, ...): ...",
                    fix="Define run with async def.",
                )
            ]

        run = run_methods[0]
        has_variable_arguments = (
            run.args.vararg is not None or run.args.kwarg is not None
        )
        if has_variable_arguments:
            return [
                ConventionViolation(
                    path=path,
                    problem="Task run methods require explicit arguments.",
                    expected="Named, typed arguments containing JSON-compatible values.",
                    fix="Replace *args and **kwargs with explicit arguments.",
                )
            ]

        parameters = [*run.args.posonlyargs, *run.args.args, *run.args.kwonlyargs]
        if parameters and parameters[0].arg == "self":
            parameters = parameters[1:]
        untyped = [
            parameter.arg for parameter in parameters if parameter.annotation is None
        ]
        if not untyped:
            return []

        names = ", ".join(untyped)
        return [
            ConventionViolation(
                path=path,
                problem=f"Task arguments need type annotations: {names}.",
                expected="Typed arguments containing JSON-compatible values.",
                fix=f"Add type annotations to: {names}.",
            )
        ]

    def _channel_violations(self) -> list[ConventionViolation]:
        directory = self.root / "app" / "channels"
        if not directory.is_dir():
            return []

        violations = []
        for path in directory.glob("*.py"):
            if path.name in {
                "__init__.py",
                "application_channel.py",
                "application_connection.py",
            }:
                continue
            if not path.name.endswith("_channel.py"):
                violations.append(
                    ConventionViolation(
                        path=path,
                        problem="Channel filenames must end in `_channel.py`.",
                        expected="A name such as chat_channel.py.",
                        fix=f"Rename {path.name} to {path.stem}_channel.py.",
                    )
                )
                continue
            violations.extend(self._inspect_channel(path))
        return violations

    def _inspect_channel(self, path: Path) -> list[ConventionViolation]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as error:
            return [
                ConventionViolation(
                    path=path,
                    problem=f"The channel is not valid Python: {error.msg}.",
                    expected="One conventional asynchronous channel class.",
                    fix="Fix the syntax error, then run `python manage.py inspect`.",
                )
            ]

        expected_class = "".join(
            part.capitalize() for part in path.stem.split("_") if part
        )
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        has_expected_class = len(classes) == 1 and classes[0].name == expected_class
        if not has_expected_class:
            return [
                ConventionViolation(
                    path=path,
                    problem="The filename and channel class disagree.",
                    expected=f"Exactly one class named {expected_class}.",
                    fix=f"Keep one class and name it {expected_class}.",
                )
            ]

        channel = classes[0]
        inherits_application_channel = any(
            isinstance(base, ast.Name) and base.id == "ApplicationChannel"
            for base in channel.bases
        )
        if not inherits_application_channel:
            return [
                ConventionViolation(
                    path=path,
                    problem="Application channels must inherit from ApplicationChannel.",
                    expected=f"class {expected_class}(ApplicationChannel): ...",
                    fix="Import and inherit from app.channels.application_channel.",
                )
            ]

        methods = {
            node.name: node
            for node in channel.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        required = ("subscribed", "received")
        invalid = [
            name
            for name in required
            if not isinstance(methods.get(name), ast.AsyncFunctionDef)
        ]
        unsubscribed = methods.get("unsubscribed")
        if unsubscribed is not None and not isinstance(
            unsubscribed, ast.AsyncFunctionDef
        ):
            invalid.append("unsubscribed")
        if not invalid:
            received = methods["received"]
            parameters = [
                *received.args.posonlyargs,
                *received.args.args,
                *received.args.kwonlyargs,
            ]
            if parameters and parameters[0].arg == "self":
                parameters = parameters[1:]
            has_one_typed_argument = (
                len(parameters) == 1 and parameters[0].annotation is not None
            )
            if has_one_typed_argument:
                return []
            return [
                ConventionViolation(
                    path=path,
                    problem="Channel received must accept one typed data argument.",
                    expected="async def received(self, data: dict): ...",
                    fix="Give received one typed data argument.",
                )
            ]

        names = ", ".join(invalid)
        return [
            ConventionViolation(
                path=path,
                problem=f"Channel lifecycle methods must be asynchronous: {names}.",
                expected="async subscribed, received, and optional unsubscribed methods.",
                fix=f"Define these methods with async def: {names}.",
            )
        ]

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
