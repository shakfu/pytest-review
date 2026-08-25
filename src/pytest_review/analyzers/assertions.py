"""Analyzer for assertion quality in tests."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from pytest_review.analyzers.base import (
    AnalyzerResult,
    Issue,
    Severity,
    StaticAnalyzer,
    TestItemInfo,
)

if TYPE_CHECKING:
    from pytest_review.config import ReviewConfig


def _dotted_name(node: ast.expr) -> str:
    """Return ``a.b.c`` for an attribute chain, or "" when it is not one."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return ""
    parts.append(current.id)
    return ".".join(reversed(parts))


def _patched_targets(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Dotted targets this test patches, from decorators and ``with`` items."""
    targets: set[str] = set()

    def _record(call: ast.Call) -> None:
        name = _dotted_name(call.func)
        if not (name == "patch" or name.endswith(".patch")):
            return
        if call.args and isinstance(call.args[0], ast.Constant):
            value = call.args[0].value
            if isinstance(value, str):
                targets.add(value)

    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call):
            _record(decorator)
    for child in ast.walk(node):
        if isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                if isinstance(item.context_expr, ast.Call):
                    _record(item.context_expr)
    return targets


class AssertionVisitor(ast.NodeVisitor):
    """AST visitor that collects assertion information."""

    # Mock assertion methods that are silently truthy when referenced, not called
    _MOCK_ASSERTIONS = frozenset(
        {"called", "call_count", "called_once", "called_with", "called_once_with"}
    )

    # pytest helpers that act as assertions (qualified or bare)
    _PYTEST_HELPERS = frozenset({"raises", "warns", "approx"})

    def __init__(self) -> None:
        self.assertions: list[ast.Assert] = []
        self.pytest_assertions: list[ast.Call] = []
        self.helper_assertions: list[ast.Call] = []
        self.trivial_assertions: list[tuple[ast.Assert, str]] = []
        self.always_true: list[tuple[ast.Assert, str]] = []
        self.uncalled_assertions: list[tuple[ast.Assert, str]] = []

    def visit_Assert(self, node: ast.Assert) -> None:
        self.assertions.append(node)
        self._check_trivial(node)
        self._check_always_true(node)
        self._check_uncalled_assertion(node)
        self.generic_visit(node)

    def _check_always_true(self, node: ast.Assert) -> None:
        """Assertions on objects that are truthy regardless of the data.

        ``assert (x > 0 for x in items)`` asserts on the *generator object*,
        which is always truthy, so the comparison inside it never runs. Same for
        a lambda: the function object is asserted, never the call.
        """
        test = node.test
        if isinstance(test, ast.GeneratorExp):
            self.always_true.append((node, "a generator expression, which is always truthy"))
        elif isinstance(test, ast.Lambda):
            self.always_true.append((node, "a lambda, which is always truthy"))

    def _check_uncalled_assertion(self, node: ast.Assert) -> None:
        """``assert mock.assert_called_once`` -- the method is never called.

        Referencing a bound method is always truthy, so the assertion passes no
        matter what the mock did. Ruff's PGH005 catches the bare-statement form
        (``mock.assert_called_once``) but not this one, where it hides inside an
        ``assert``.
        """
        test = node.test
        if isinstance(test, ast.Attribute) and (
            test.attr.startswith("assert_") or test.attr in self._MOCK_ASSERTIONS
        ):
            self.uncalled_assertions.append((node, test.attr))

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._get_call_name(node.func)

        if call_name in self._PYTEST_HELPERS:
            self.pytest_assertions.append(node)
        elif self._is_assertion_helper_name(call_name):
            # Mock assertions (mock.assert_called_once, assert_called_with),
            # unittest-style assertions (self.assertEqual, self.assertTrue),
            # and user-defined helpers (assert_rss_bounded, assert_valid_response).
            self.helper_assertions.append(node)

        self.generic_visit(node)

    @staticmethod
    def _get_call_name(func: ast.expr) -> str:
        """Return the final name of a call target (e.g. ``foo`` for ``a.b.foo``)."""
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return ""

    @staticmethod
    def _is_assertion_helper_name(name: str) -> bool:
        """Return True for names that conventionally denote an assertion helper.

        Covers three families:
        - ``assert_*`` snake_case helpers (mock ``assert_called_once``,
          user-defined ``assert_rss_bounded``).
        - unittest-style camelCase helpers (``assertEqual``, ``assertTrue``,
          ``assertRaises``, ``assertIn``, ...).
        - the bare ``assert_`` name itself.
        """
        if not name or not name.startswith("assert"):
            return False
        if name == "assert_" or name.startswith("assert_"):
            return True
        prefix_len = len("assert")
        # assertEqual, assertTrue, assertRaises, ... (next char is uppercase)
        return len(name) > prefix_len and name[prefix_len].isupper()

    def _check_trivial(self, node: ast.Assert) -> None:
        """Check if assertion is trivial (assert True, assert False, etc.)."""
        test = node.test

        # assert True / assert False
        if isinstance(test, ast.Constant):
            if test.value is True:
                self.trivial_assertions.append((node, "assert True"))
            elif test.value is False:
                self.trivial_assertions.append((node, "assert False"))

        # assert 1, assert "string", etc. (always truthy)
        elif isinstance(test, ast.Constant) and test.value:
            self.trivial_assertions.append((node, f"assert {test.value!r} (always truthy)"))

        # assert x == x (tautology)
        elif (
            isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
        ):
            left = ast.dump(test.left)
            right = ast.dump(test.comparators[0])
            if left == right:
                self.trivial_assertions.append((node, "comparing value to itself"))

    @property
    def total_assertions(self) -> int:
        return len(self.assertions) + len(self.pytest_assertions) + len(self.helper_assertions)


class AssertionsAnalyzer(StaticAnalyzer):
    """Analyzes assertion quality in tests."""

    name = "assertions"
    description = "Checks for missing, trivial, or weak assertions"

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)
        typed = config.get_assertions_config()
        self._min_assertions = typed.min_assertions

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        visitor = AssertionVisitor()
        visitor.visit(test.node)

        # Check for empty tests (no assertions)
        if visitor.total_assertions == 0:
            result.add_issue(
                Issue(
                    rule="assertions.missing",
                    message="Test has no assertions",
                    severity=Severity.ERROR,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=test.name,
                    suggestion="Add at least one assertion to verify expected behavior",
                )
            )

        # Check for too few assertions
        elif visitor.total_assertions < self._min_assertions:
            result.add_issue(
                Issue(
                    rule="assertions.insufficient",
                    message=f"Test has only {visitor.total_assertions} assertion(s), "
                    f"minimum is {self._min_assertions}",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=test.name,
                )
            )

        # Check for trivial assertions
        for assert_node, reason in visitor.trivial_assertions:
            result.add_issue(
                Issue(
                    rule="assertions.trivial",
                    message=f"Trivial assertion: {reason}",
                    severity=Severity.ERROR,
                    file_path=test.file_path,
                    line=assert_node.lineno,
                    test_name=test.name,
                    suggestion="Replace with a meaningful assertion that tests actual behavior",
                )
            )

        for assert_node, what in visitor.always_true:
            result.add_issue(
                Issue(
                    rule="assertions.always_true",
                    message=f"Assertion is on {what}; it cannot fail",
                    severity=Severity.ERROR,
                    file_path=test.file_path,
                    line=assert_node.lineno,
                    test_name=test.name,
                    suggestion="Wrap in all()/any(), or assert the materialised list",
                )
            )

        for assert_node, attr in visitor.uncalled_assertions:
            result.add_issue(
                Issue(
                    rule="assertions.uncalled_assertion",
                    message=(
                        f"'{attr}' is referenced but never called, so the assertion "
                        f"is always true"
                    ),
                    severity=Severity.ERROR,
                    file_path=test.file_path,
                    line=assert_node.lineno,
                    test_name=test.name,
                    suggestion=f"Call it: {attr}(...)",
                )
            )

        # A test that asserts on a direct call to something it patched is
        # verifying unittest.mock, not the code under test: the patched object's
        # behaviour is entirely defined by the test itself.
        patched = _patched_targets(test.node)
        if patched:
            for assert_node in visitor.assertions:
                for call in (n for n in ast.walk(assert_node) if isinstance(n, ast.Call)):
                    called = _dotted_name(call.func)
                    if not called:
                        continue
                    if any(
                        called == target or target.endswith(f".{called}") for target in patched
                    ):
                        result.add_issue(
                            Issue(
                                rule="assertions.mock_tautology",
                                message=(
                                    f"Assertion calls '{called}', which this test patched; "
                                    f"it verifies the mock, not the code under test"
                                ),
                                severity=Severity.ERROR,
                                file_path=test.file_path,
                                line=assert_node.lineno,
                                test_name=test.name,
                                suggestion=(
                                    "Assert on the code that *uses* the patched dependency"
                                ),
                            )
                        )
                        break

        # Check assertion-to-logic ratio. A test whose body is almost all setup
        # and almost no verification is a defect signal, not a style opinion:
        # it is doing work nobody checks.
        statement_count = sum(1 for node in ast.walk(test.node) if isinstance(node, ast.stmt))
        total = visitor.total_assertions
        if statement_count >= 10 and total > 0 and total / statement_count < 0.1:
            result.add_issue(
                Issue(
                    rule="assertions.low_ratio",
                    message=(
                        f"Low assertion-to-logic ratio: {total} assertion(s) "
                        f"across {statement_count} statements"
                    ),
                    severity=Severity.INFO,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=test.name,
                    suggestion="Test has too much setup/logic relative to what it verifies",
                )
            )

        # Store metadata
        result.metadata["assertion_count"] = visitor.total_assertions
        result.metadata["trivial_count"] = len(visitor.trivial_assertions)
