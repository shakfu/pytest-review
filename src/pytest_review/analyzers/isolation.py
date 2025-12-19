"""Analyzer for test isolation."""

from __future__ import annotations

import ast
import sys
from typing import TYPE_CHECKING, Any

from pytest_review.analyzers.base import (
    AnalyzerResult,
    DynamicAnalyzer,
    Issue,
    Severity,
    StaticAnalyzer,
    TestItemInfo,
)

if TYPE_CHECKING:
    from pytest_review.config import ReviewConfig


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

    def __init__(self) -> None:
        self.global_writes: list[tuple[int, str]] = []  # (line, name)
        self.global_declarations: list[str] = []
        self.class_attr_modifications: list[tuple[int, str]] = []
        self._in_function = False

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
            # Common class reference patterns
            if name in ("cls", "self.__class__") or name[0].isupper():
                self.class_attr_modifications.append((node.lineno, f"{name}.{node.attr}"))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Detect mutating method calls on class attributes."""
        # Check for ClassName.attr.mutating_method() pattern
        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            if method_name in self.MUTATING_METHODS and isinstance(node.func.value, ast.Attribute):
                inner = node.func.value
                if isinstance(inner.value, ast.Name):
                    name = inner.value.id
                    # Common class reference patterns
                    if name in ("cls", "self.__class__") or name[0].isupper():
                        self.class_attr_modifications.append(
                            (node.lineno, f"{name}.{inner.attr}.{method_name}()")
                        )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        """Detect modifications to module-level dicts/lists."""
        if (
            isinstance(node.ctx, ast.Store)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
        ):
            module_name = node.value.value.id
            attr_name = node.value.attr
            # Check if it looks like a module reference
            if module_name in sys.modules or module_name[0].islower():
                self.class_attr_modifications.append(
                    (node.lineno, f"{module_name}.{attr_name}[...]")
                )
        self.generic_visit(node)


class IsolationStaticAnalyzer(StaticAnalyzer):
    """Static analyzer for test isolation issues."""

    name = "isolation"
    description = "Detects potential test isolation issues"

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        visitor = GlobalModificationVisitor()
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

        result.metadata["global_modifications"] = len(visitor.global_writes)
        result.metadata["class_attr_modifications"] = len(visitor.class_attr_modifications)


class IsolationDynamicAnalyzer(DynamicAnalyzer):
    """Dynamic analyzer that tracks actual state modifications during test runs."""

    name = "isolation_runtime"
    description = "Tracks runtime state modifications"

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)
        self._module_snapshots: dict[str, dict[str, Any]] = {}
        self._test_modifications: dict[str, list[str]] = {}
        self._current_test: str | None = None
        self._monitored_modules: set[str] = set()

    def configure_monitoring(self, module_names: list[str]) -> None:
        """Configure which modules to monitor for state changes."""
        self._monitored_modules = set(module_names)

    def _snapshot_module(self, module_name: str) -> dict[str, Any]:
        """Take a snapshot of a module's public attributes."""
        if module_name not in sys.modules:
            return {}

        module = sys.modules[module_name]
        snapshot: dict[str, Any] = {}

        for name in dir(module):
            if name.startswith("_"):
                continue
            try:
                value = getattr(module, name)
                # Only track simple types that we can compare
                if isinstance(value, (int, float, str, bool, list, dict, set, tuple)):
                    # For mutable types, make a shallow copy
                    if isinstance(value, list):
                        snapshot[name] = list(value)
                    elif isinstance(value, dict):
                        snapshot[name] = dict(value)
                    elif isinstance(value, set):
                        snapshot[name] = set(value)
                    else:
                        snapshot[name] = value
            except Exception:
                pass

        return snapshot

    def _compare_snapshots(self, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        """Compare two snapshots and return list of modified attributes."""
        modified = []

        # Check for modifications and additions
        for name, after_value in after.items():
            if name not in before:
                modified.append(f"{name} (added)")
            elif before[name] != after_value:
                modified.append(f"{name} (modified)")

        # Check for deletions
        for name in before:
            if name not in after:
                modified.append(f"{name} (deleted)")

        return modified

    def on_test_start(self, test_name: str) -> None:
        """Called when a test starts executing."""
        self._current_test = test_name
        self._module_snapshots = {}

        # Take snapshots of monitored modules
        for module_name in self._monitored_modules:
            self._module_snapshots[module_name] = self._snapshot_module(module_name)

    def on_test_end(self, test_name: str, passed: bool, duration: float) -> None:
        """Called when a test finishes executing."""
        modifications = []

        # Compare snapshots
        for module_name in self._monitored_modules:
            before = self._module_snapshots.get(module_name, {})
            after = self._snapshot_module(module_name)
            module_mods = self._compare_snapshots(before, after)
            for mod in module_mods:
                modifications.append(f"{module_name}.{mod}")

        if modifications:
            self._test_modifications[test_name] = modifications

        self._current_test = None

    def get_results(self) -> list[AnalyzerResult]:
        """Get accumulated results after test run."""
        results = []

        for test_name, modifications in self._test_modifications.items():
            result = AnalyzerResult(analyzer_name=self.name)
            for mod in modifications:
                result.add_issue(
                    Issue(
                        rule="isolation.runtime_modification",
                        message=f"Test modified shared state: {mod}",
                        severity=Severity.WARNING,
                        test_name=test_name,
                        suggestion="Ensure test cleanup restores original state",
                    )
                )
            result.metadata["modifications"] = modifications
            results.append(result)

        return results
