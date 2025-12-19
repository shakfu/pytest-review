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

    def visit_Assert(self, node: ast.Assert) -> None:
        self.assertions.append(node)
        self._check_trivial(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check for pytest assertion helpers like pytest.raises, pytest.warns
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "pytest":
                if node.func.attr in ("raises", "warns", "approx"):
                    self.pytest_assertions.append(node)
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
        elif isinstance(test, ast.Compare):
            if len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
                left = ast.dump(test.left)
                right = ast.dump(test.comparators[0])
                if left == right:
                    self.trivial_assertions.append((node, "comparing value to itself"))

    @property
    def total_assertions(self) -> int:
        return len(self.assertions) + len(self.pytest_assertions)


class AssertionsAnalyzer(StaticAnalyzer):
    """Analyzes assertion quality in tests."""

    name = "assertions"
    description = "Checks for missing, trivial, or weak assertions"

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)
        self._min_assertions = int(self.get_option("min_assertions", 1) or 1)

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

        # Store metadata
        result.metadata["assertion_count"] = visitor.total_assertions
        result.metadata["trivial_count"] = len(visitor.trivial_assertions)
