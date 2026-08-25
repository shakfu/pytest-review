"""Analyzer for test isolation."""

from __future__ import annotations

import ast

from pytest_review.analyzers.base import (
    AnalyzerResult,
    Issue,
    Severity,
    StaticAnalyzer,
    TestItemInfo,
)


def _collect_local_names(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect names that are locally defined within a function.

    Includes parameters, assignment targets, import names, for-loop targets,
    with-as targets, and exception handler names.
    """
    locals_: set[str] = set()

    # Parameters (positional, keyword, *args, **kwargs)
    for arg in func_node.args.args + func_node.args.posonlyargs + func_node.args.kwonlyargs:
        locals_.add(arg.arg)
    if func_node.args.vararg:
        locals_.add(func_node.args.vararg.arg)
    if func_node.args.kwarg:
        locals_.add(func_node.args.kwarg.arg)

    # Walk the function body for other local bindings
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    locals_.add(target.id)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name):
            locals_.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                locals_.add(alias.asname if alias.asname else alias.name)
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            locals_.add(node.target.id)
        elif isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
            locals_.add(node.optional_vars.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            locals_.add(node.name)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in node.generators:
                if isinstance(gen.target, ast.Name):
                    locals_.add(gen.target.id)
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            locals_.add(node.target.id)

    return locals_


class MockPatchVisitor(ast.NodeVisitor):
    """Detects mock.patch / patch.object calls not used as context managers."""

    def __init__(self) -> None:
        self.bare_patches: list[tuple[int, str]] = []
        # Call nodes that are managed contexts: `with patch(...)` items and
        # `@patch(...)` / `@mock.patch(...)` decorators (cleanup is guaranteed
        # by the framework in both cases).
        self._with_context_calls: set[int] = set()
        self._decorator_calls: set[int] = set()

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if isinstance(item.context_expr, ast.Call):
                self._with_context_calls.add(id(item.context_expr))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_decorator_calls(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_decorator_calls(node)
        self.generic_visit(node)

    def _record_decorator_calls(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                self._decorator_calls.add(id(decorator))

    def visit_Call(self, node: ast.Call) -> None:
        if id(node) in self._with_context_calls or id(node) in self._decorator_calls:
            self.generic_visit(node)
            return
        if self._is_patch_call(node):
            self.bare_patches.append((node.lineno, self._patch_name(node)))
        self.generic_visit(node)

    @staticmethod
    def _is_patch_call(node: ast.Call) -> bool:
        func = node.func
        # mock.patch(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "patch"
            and isinstance(func.value, ast.Name)
            and func.value.id == "mock"
        ):
            return True
        # patch.object(...)
        if isinstance(func, ast.Attribute) and func.attr == "object":
            if isinstance(func.value, ast.Attribute) and func.value.attr == "patch":
                return True
            if isinstance(func.value, ast.Name) and func.value.id == "patch":
                return True
        # Direct patch(...) call
        return isinstance(func, ast.Name) and func.id == "patch"

    @staticmethod
    def _patch_name(node: ast.Call) -> str:
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr == "object":
                return "patch.object()"
            return f"{func.attr}()"
        if isinstance(func, ast.Name):
            return f"{func.id}()"
        return "patch()"


class GlobalModificationVisitor(ast.NodeVisitor):
    """AST visitor that detects potential global state modifications."""

    # Methods that mutate mutable objects
    MUTATING_METHODS = {
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "add",
        "discard",
        "update",
        "intersection_update",
        "difference_update",
        "symmetric_difference_update",
        "setdefault",
        "popitem",
    }

    def __init__(self, local_names: set[str]) -> None:
        self.global_writes: list[tuple[int, str]] = []  # (line, name)
        self.global_declarations: list[str] = []
        self.class_attr_modifications: list[tuple[int, str]] = []
        self.env_mutations: list[tuple[int, str]] = []
        self.process_mutations: list[tuple[int, str]] = []
        self._local_names = local_names

    def _is_external(self, name: str) -> bool:
        """Check if a name refers to something outside the function scope."""
        return name not in self._local_names

    def visit_Global(self, node: ast.Global) -> None:
        """Detect 'global' keyword usage."""
        for name in node.names:
            self.global_declarations.append(name)
            self.global_writes.append((node.lineno, name))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Detect class/module attribute modifications."""
        # Check if this is a write context (assignment target)
        if isinstance(node.ctx, ast.Store) and isinstance(node.value, ast.Name):
            name = node.value.id
            if self._is_external(name):
                self.class_attr_modifications.append((node.lineno, f"{name}.{node.attr}"))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Detect mutating method calls on class attributes, os.environ, and process state."""
        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            # os.chdir(...) -- process-wide cwd mutation
            if (
                method_name == "chdir"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
            ):
                self.process_mutations.append((node.lineno, "os.chdir()"))
                self.generic_visit(node)
                return
            # Check for os.environ.update/pop/setdefault/clear/...
            if method_name in self.MUTATING_METHODS and self._is_os_environ(node.func.value):
                self.env_mutations.append((node.lineno, f"os.environ.{method_name}()"))
                self.generic_visit(node)
                return
            # sys.path.append / sys.argv.append / ... -- process-wide mutation
            if method_name in self.MUTATING_METHODS and self._is_sys_mutable(node.func.value):
                assert isinstance(node.func.value, ast.Attribute)  # for type narrowing
                self.process_mutations.append(
                    (node.lineno, f"sys.{node.func.value.attr}.{method_name}()")
                )
                self.generic_visit(node)
                return
            # Check for Name.attr.mutating_method() pattern
            if method_name in self.MUTATING_METHODS and isinstance(node.func.value, ast.Attribute):
                inner = node.func.value
                if isinstance(inner.value, ast.Name):
                    name = inner.value.id
                    if self._is_external(name):
                        self.class_attr_modifications.append(
                            (node.lineno, f"{name}.{inner.attr}.{method_name}()")
                        )
        self.generic_visit(node)

    @staticmethod
    def _is_sys_mutable(node: ast.AST) -> bool:
        """Check if node is ``sys.path`` or ``sys.argv``."""
        return (
            isinstance(node, ast.Attribute)
            and node.attr in ("path", "argv")
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
        )

    def _is_os_environ(self, node: ast.AST) -> bool:
        """Check if node is os.environ."""
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "environ"
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        )

    def visit_Subscript(self, node: ast.Subscript) -> None:
        """Detect modifications to module-level dicts/lists, os.environ, and sys.*."""
        if isinstance(node.ctx, ast.Store):
            # Check for os.environ["KEY"] = ...
            if self._is_os_environ(node.value):
                self.env_mutations.append((node.lineno, "os.environ[...] = ..."))
                self.generic_visit(node)
                return
            # sys.path[...] = ... / sys.argv[...] = ...
            if self._is_sys_mutable(node.value):
                assert isinstance(node.value, ast.Attribute)
                self.process_mutations.append((node.lineno, f"sys.{node.value.attr}[...] = ..."))
                self.generic_visit(node)
                return
            if isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name):
                name = node.value.value.id
                attr_name = node.value.attr
                if self._is_external(name):
                    self.class_attr_modifications.append((node.lineno, f"{name}.{attr_name}[...]"))
        self.generic_visit(node)


class IsolationStaticAnalyzer(StaticAnalyzer):
    """Static analyzer for test isolation issues."""

    name = "isolation"
    description = "Detects potential test isolation issues"

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        local_names = _collect_local_names(test.node)
        visitor = GlobalModificationVisitor(local_names)
        visitor.visit(test.node)

        # Report global keyword usage
        for line, name in visitor.global_writes:
            result.add_issue(
                Issue(
                    rule="isolation.global_modification",
                    message=f"Test uses 'global {name}' which modifies shared state",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=line,
                    test_name=test.name,
                    suggestion="Avoid modifying global state; use fixtures or dependency injection",
                )
            )

        # Report class attribute modifications
        for line, attr in visitor.class_attr_modifications:
            result.add_issue(
                Issue(
                    rule="isolation.class_attr_modification",
                    message=f"Test modifies class/module attribute: {attr}",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=line,
                    test_name=test.name,
                    suggestion="Use instance attributes or fixtures instead of class-level state",
                )
            )

        # Report os.environ mutations
        for line, detail in visitor.env_mutations:
            result.add_issue(
                Issue(
                    rule="isolation.env_mutation",
                    message=f"Test mutates os.environ: {detail}",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=line,
                    test_name=test.name,
                    suggestion="Use monkeypatch.setenv/delenv to safely modify env vars",
                )
            )

        # Report process-wide state mutations (os.chdir, sys.path, sys.argv)
        for line, detail in visitor.process_mutations:
            result.add_issue(
                Issue(
                    rule="isolation.process_mutation",
                    message=f"Test mutates process-wide state: {detail}",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=line,
                    test_name=test.name,
                    suggestion=(
                        "Use monkeypatch.chdir / monkeypatch.syspath_prepend / "
                        "monkeypatch.setattr to restore state after the test"
                    ),
                )
            )

        # Check for bare mock.patch calls
        patch_visitor = MockPatchVisitor()
        patch_visitor.visit(test.node)
        for line, detail in patch_visitor.bare_patches:
            result.add_issue(
                Issue(
                    rule="isolation.bare_patch",
                    message=f"Bare {detail} without context manager may leak state",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=line,
                    test_name=test.name,
                    suggestion="Use 'with patch(...)' or a decorator to ensure cleanup",
                )
            )

        result.metadata["global_modifications"] = len(visitor.global_writes)
        result.metadata["class_attr_modifications"] = len(visitor.class_attr_modifications)
        result.metadata["env_mutations"] = len(visitor.env_mutations)
        result.metadata["process_mutations"] = len(visitor.process_mutations)
        result.metadata["bare_patches"] = len(patch_visitor.bare_patches)
