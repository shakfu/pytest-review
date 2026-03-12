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


class AssertionVisitor(ast.NodeVisitor):
    """AST visitor that collects assertion information."""

    def __init__(self) -> None:
        self.assertions: list[ast.Assert] = []
        self.pytest_assertions: list[ast.Call] = []
        self.trivial_assertions: list[tuple[ast.Assert, str]] = []
        self.low_value_assertions: list[tuple[ast.Assert, str]] = []
        self.yoda_conditions: list[tuple[ast.Assert, str]] = []
        self.raises_without_match: list[tuple[ast.Call, str]] = []

    def visit_Assert(self, node: ast.Assert) -> None:
        self.assertions.append(node)
        self._check_trivial(node)
        self._check_low_value(node)
        self._check_yoda(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check for pytest assertion helpers like pytest.raises, pytest.warns
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "pytest"
            and node.func.attr in ("raises", "warns", "approx")
        ):
            self.pytest_assertions.append(node)
            # Check for pytest.raises without match= keyword
            if node.func.attr == "raises":
                has_match = any(
                    isinstance(kw.arg, str) and kw.arg == "match" for kw in node.keywords
                )
                if not has_match and node.args:
                    exc_name = ""
                    if isinstance(node.args[0], ast.Name):
                        exc_name = node.args[0].id
                    elif isinstance(node.args[0], ast.Attribute):
                        exc_name = node.args[0].attr
                    self.raises_without_match.append((node, exc_name))
        self.generic_visit(node)

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

    def _check_low_value(self, node: ast.Assert) -> None:
        """Check for low-value assertions like isinstance() or 'is not None'."""
        test = node.test
        # assert isinstance(x, SomeType)
        if (
            isinstance(test, ast.Call)
            and isinstance(test.func, ast.Name)
            and test.func.id == "isinstance"
        ):
            self.low_value_assertions.append((node, "isinstance check"))
            return
        # assert x is not None
        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.IsNot)
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value is None
        ):
            self.low_value_assertions.append((node, "'is not None' check"))

    def _check_yoda(self, node: ast.Assert) -> None:
        """Check for Yoda conditions like assert 42 == x."""
        test = node.test
        if not isinstance(test, ast.Compare):
            return
        if len(test.ops) != 1:
            return
        if not isinstance(test.ops[0], (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
            return
        left = test.left
        right = test.comparators[0]
        # Flag when left is a constant and right is not
        if isinstance(left, ast.Constant) and not isinstance(right, ast.Constant):
            # Skip None/True/False -- those are idiomatic on the right with is/is not
            if left.value is None or left.value is True or left.value is False:
                return
            self.yoda_conditions.append((node, f"{left.value!r} == ..."))

    @property
    def total_assertions(self) -> int:
        return len(self.assertions) + len(self.pytest_assertions)


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

        # Check for low-value assertions
        for assert_node, reason in visitor.low_value_assertions:
            result.add_issue(
                Issue(
                    rule="assertions.low_value",
                    message=f"Low-value assertion: {reason}",
                    severity=Severity.INFO,
                    file_path=test.file_path,
                    line=assert_node.lineno,
                    test_name=test.name,
                    suggestion="Assert on actual values rather than types or existence",
                )
            )

        # Check for pytest.raises without match=
        for call_node, exc_name in visitor.raises_without_match:
            result.add_issue(
                Issue(
                    rule="assertions.raises_without_match",
                    message=(
                        f"pytest.raises({exc_name}) without match= "
                        f"does not verify the exception message"
                    ),
                    severity=Severity.INFO,
                    file_path=test.file_path,
                    line=call_node.lineno,
                    test_name=test.name,
                    suggestion="Add match= to verify the exception message",
                )
            )

        # Check for Yoda conditions
        for assert_node, reason in visitor.yoda_conditions:
            result.add_issue(
                Issue(
                    rule="assertions.yoda_condition",
                    message=f"Yoda condition: {reason}",
                    severity=Severity.INFO,
                    file_path=test.file_path,
                    line=assert_node.lineno,
                    test_name=test.name,
                    suggestion="Put the expected value on the right: assert x == 42",
                )
            )

        # Store metadata
        result.metadata["assertion_count"] = visitor.total_assertions
        result.metadata["trivial_count"] = len(visitor.trivial_assertions)
