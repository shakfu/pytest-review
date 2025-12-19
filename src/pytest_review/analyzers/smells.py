"""Test smell analyzer for pytest-review.

Detects common test smells that indicate potential quality issues.

This analyzer is inspired by the pytest-smell project from the dissertation
"Detecting Test Smells in Python" by Maxim Pacsial.
See: https://github.com/maxpacs98/disertation

Test smell concepts are based on research by:
- Van Deursen et al. "Refactoring Test Code" (2001)
- Meszaros, G. "xUnit Test Patterns" (2007)
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from pytest_review.analyzers.base import AnalyzerResult, Issue, Severity, StaticAnalyzer

if TYPE_CHECKING:
    from pytest_review.analyzers.base import TestItemInfo
    from pytest_review.config import ReviewConfig


class SmellsAnalyzer(StaticAnalyzer):
    """Detects test smells that indicate quality issues."""

    name = "smells"

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)
        analyzer_config = config.get_analyzer_config(self.name)
        self._max_assertions_without_message = analyzer_config.options.get(
            "max_assertions_without_message", 1
        )
        self._check_magic_numbers = analyzer_config.options.get("check_magic_numbers", True)
        self._check_eager_test = analyzer_config.options.get("check_eager_test", True)

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        """Analyze test for smells."""
        visitor = SmellVisitor(test, result, self)
        visitor.visit(test.node)


class SmellVisitor(ast.NodeVisitor):
    """AST visitor that detects test smells."""

    # Magic number exceptions - these are commonly acceptable
    ALLOWED_MAGIC_NUMBERS = {0, 1, -1, 2, 100, 1000}

    def __init__(
        self,
        test: TestItemInfo,
        result: AnalyzerResult,
        analyzer: SmellsAnalyzer,
    ) -> None:
        self._test = test
        self._result = result
        self._analyzer = analyzer
        self._assertions: list[ast.Assert] = []
        self._assertion_messages: list[str] = []
        self._call_targets: set[str] = set()
        self._has_skip_marker = False

    def visit_Assert(self, node: ast.Assert) -> None:
        """Track assertions for roulette and duplicate detection."""
        self._assertions.append(node)

        # Check for assertion message
        if node.msg is None:
            self._assertion_messages.append("")
        else:
            self._assertion_messages.append(ast.dump(node.msg))

        # Check for magic numbers in assertions
        if self._analyzer._check_magic_numbers:
            self._check_magic_number(node)

        # Track what's being tested for eager test detection
        if self._analyzer._check_eager_test:
            self._extract_call_target(node.test)

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Track function calls for eager test detection."""
        if self._analyzer._check_eager_test:
            self._extract_call_target(node)
        self.generic_visit(node)

    def _extract_call_target(self, node: ast.AST) -> None:
        """Extract the function/method being called."""
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                self._call_targets.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                # Get the full attribute chain (e.g., obj.method)
                self._call_targets.add(node.func.attr)
        elif isinstance(node, ast.Compare):
            # Check both sides of comparison
            self._extract_call_target(node.left)
            for comparator in node.comparators:
                self._extract_call_target(comparator)
        elif isinstance(node, ast.BoolOp):
            for value in node.values:
                self._extract_call_target(value)

    def _check_magic_number(self, node: ast.Assert) -> None:
        """Check for magic numbers in assertion."""
        for child in ast.walk(node.test):
            if (
                isinstance(child, ast.Constant)
                and isinstance(child.value, (int, float))
                and child.value not in self.ALLOWED_MAGIC_NUMBERS
            ):
                self._result.add_issue(
                    Issue(
                        rule="smells.magic_number",
                        message=f"Magic number {child.value} in assertion",
                        severity=Severity.INFO,
                        file_path=self._test.file_path,
                        line=child.lineno,
                        test_name=self._test.name,
                        suggestion="Use a named constant or variable for clarity",
                    )
                )
                return  # Only report once per assertion

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check for skip decorators and visit body."""
        self._check_skip_decorator(node)
        self.generic_visit(node)
        self._finalize_checks()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check for skip decorators and visit body."""
        self._check_skip_decorator(node)
        self.generic_visit(node)
        self._finalize_checks()

    def _check_skip_decorator(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Check if test has skip decorator."""
        for decorator in node.decorator_list:
            decorator_name = self._get_decorator_name(decorator)
            if decorator_name in (
                "skip",
                "skipif",
                "pytest.mark.skip",
                "pytest.mark.skipif",
                "unittest.skip",
                "unittest.skipIf",
                "unittest.skipUnless",
            ):
                self._has_skip_marker = True
                self._result.add_issue(
                    Issue(
                        rule="smells.ignored_test",
                        message=f"Test is skipped with @{decorator_name}",
                        severity=Severity.WARNING,
                        file_path=self._test.file_path,
                        line=node.lineno,
                        test_name=self._test.name,
                        suggestion="Ensure skipped tests are tracked and re-enabled when ready",
                    )
                )

    def _get_decorator_name(self, decorator: ast.expr) -> str:
        """Get the full name of a decorator."""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            parts: list[str] = []
            current: ast.expr = decorator
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        elif isinstance(decorator, ast.Call):
            return self._get_decorator_name(decorator.func)
        return ""

    def _finalize_checks(self) -> None:
        """Run checks that need all assertions collected."""
        self._check_assertion_roulette()
        self._check_duplicate_assertions()
        self._check_eager_test()

    def _check_assertion_roulette(self) -> None:
        """Check for multiple assertions without messages."""
        if len(self._assertions) <= 1:
            return

        assertions_without_msg = sum(1 for msg in self._assertion_messages if not msg)
        threshold = self._analyzer._max_assertions_without_message

        if assertions_without_msg > threshold:
            self._result.add_issue(
                Issue(
                    rule="smells.assertion_roulette",
                    message=(
                        f"Test has {assertions_without_msg} assertions without messages "
                        f"(threshold: {threshold})"
                    ),
                    severity=Severity.WARNING,
                    file_path=self._test.file_path,
                    line=self._test.line,
                    test_name=self._test.name,
                    suggestion=(
                        "Add descriptive messages to assertions: "
                        "assert x == y, 'expected x to equal y'"
                    ),
                )
            )

    def _check_duplicate_assertions(self) -> None:
        """Check for duplicate assertion statements."""
        seen: dict[str, int] = {}
        duplicates: list[tuple[int, str]] = []

        for assertion in self._assertions:
            # Create a normalized representation of the assertion
            assertion_repr = ast.dump(assertion.test)
            if assertion_repr in seen:
                duplicates.append((assertion.lineno, assertion_repr))
            else:
                seen[assertion_repr] = assertion.lineno

        if duplicates:
            self._result.add_issue(
                Issue(
                    rule="smells.duplicate_assert",
                    message=f"Test has {len(duplicates)} duplicate assertion(s)",
                    severity=Severity.WARNING,
                    file_path=self._test.file_path,
                    line=duplicates[0][0],
                    test_name=self._test.name,
                    suggestion="Remove duplicates or verify they test different scenarios",
                )
            )

    def _check_eager_test(self) -> None:
        """Check if test verifies multiple distinct methods/functions."""
        if not self._analyzer._check_eager_test:
            return

        # Filter out common assertion helpers and built-ins
        excluded = {
            "len",
            "str",
            "int",
            "float",
            "list",
            "dict",
            "set",
            "tuple",
            "isinstance",
            "hasattr",
            "getattr",
            "type",
            "id",
            "repr",
            "sorted",
            "reversed",
            "enumerate",
            "zip",
            "map",
            "filter",
            "any",
            "all",
            "sum",
            "min",
            "max",
            "abs",
            "round",
            "assertTrue",
            "assertFalse",
            "assertEqual",
            "assertNotEqual",
            "assertIn",
            "assertNotIn",
            "assertIs",
            "assertIsNot",
            "assertIsNone",
            "assertIsNotNone",
            "assertRaises",
        }

        distinct_targets = self._call_targets - excluded

        if len(distinct_targets) > 2:
            self._result.add_issue(
                Issue(
                    rule="smells.eager_test",
                    message=(
                        f"Test calls {len(distinct_targets)} distinct methods: "
                        f"{', '.join(sorted(distinct_targets)[:5])}"
                        f"{'...' if len(distinct_targets) > 5 else ''}"
                    ),
                    severity=Severity.INFO,
                    file_path=self._test.file_path,
                    line=self._test.line,
                    test_name=self._test.name,
                    suggestion="Consider splitting into focused tests for each behavior",
                )
            )
