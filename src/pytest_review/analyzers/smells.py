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
from typing import TYPE_CHECKING, Iterator

from pytest_review.analyzers.base import AnalyzerResult, Issue, Severity, StaticAnalyzer

if TYPE_CHECKING:
    from pytest_review.analyzers.base import TestItemInfo
    from pytest_review.config import ReviewConfig


# Exception types that swallow AssertionError when caught
_ASSERTION_SWALLOWING_EXCEPTIONS = frozenset({"AssertionError", "Exception", "BaseException"})


class SmellsAnalyzer(StaticAnalyzer):
    """Detects test smells that indicate quality issues."""

    name = "smells"

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)
        typed = config.get_smells_config()
        self._max_assertions_without_message = typed.max_assertions_without_message
        self._check_magic_numbers = typed.check_magic_numbers
        self._check_eager_test = typed.check_eager_test

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
        self._runtime_skip_calls: list[tuple[int, str]] = []

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
        """Track function calls for eager-test and runtime-skip detection."""
        if self._analyzer._check_eager_test:
            self._extract_call_target(node)
        self._check_runtime_skip(node)
        self.generic_visit(node)

    def _check_runtime_skip(self, node: ast.Call) -> None:
        """Record runtime skip calls in the test body.

        Matches:
        - ``pytest.skip(...)`` / ``pytest.xfail(...)`` (qualified only, to avoid
          false-positives from user code with a ``skip`` helper).
        - ``self.skipTest(...)`` (unittest.TestCase style).

        ``pytest.importorskip(...)`` is deliberately excluded because it expresses
        a legitimate optional-dependency gate, not a dead test.
        """
        func = node.func
        if not isinstance(func, ast.Attribute):
            return
        if not isinstance(func.value, ast.Name):
            return
        # pytest.skip / pytest.xfail
        if func.value.id == "pytest" and func.attr in ("skip", "xfail"):
            self._runtime_skip_calls.append((node.lineno, f"pytest.{func.attr}"))
            return
        # self.skipTest (unittest.TestCase.skipTest)
        if func.value.id == "self" and func.attr == "skipTest":
            self._runtime_skip_calls.append((node.lineno, "self.skipTest"))

    def visit_Raise(self, node: ast.Raise) -> None:
        """Detect ``raise SkipTest(...)`` / ``raise unittest.SkipTest(...)``."""
        self._check_raise_skip(node)
        self.generic_visit(node)

    def _check_raise_skip(self, node: ast.Raise) -> None:
        exc = node.exc
        if exc is None:
            return
        # ``raise SkipTest(...)`` -> exc is a Call; ``raise SkipTest`` -> exc is Name/Attr
        target = exc.func if isinstance(exc, ast.Call) else exc
        if isinstance(target, ast.Name) and target.id == "SkipTest":
            self._runtime_skip_calls.append((node.lineno, "raise SkipTest"))
            return
        if isinstance(target, ast.Attribute) and target.attr == "SkipTest":
            qualifier = ""
            if isinstance(target.value, ast.Name):
                qualifier = f"{target.value.id}."
            self._runtime_skip_calls.append((node.lineno, f"raise {qualifier}SkipTest"))

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
        # Only check decorators on the test function itself, not on nested helpers.
        if node is self._test.node:
            self._check_skip_decorator(node)
        self.generic_visit(node)
        # _finalize_checks runs once, for the outer test only, so body-scanning
        # checks (early_return, swallowed_assertion, ...) aren't duplicated.
        if node is self._test.node:
            self._finalize_checks()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check for skip decorators and visit body."""
        if node is self._test.node:
            self._check_skip_decorator(node)
        self.generic_visit(node)
        if node is self._test.node:
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
                "mark.skip",
                "mark.skipif",
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
        self._check_conditional_logic()
        self._check_fixture_overuse()
        self._check_try_except()
        self._check_early_return()
        self._check_swallowed_assertion()
        self._report_runtime_skips()

    def _walk_test_body(self) -> Iterator[ast.AST]:
        """Yield every node in the test function body, excluding nested scopes.

        Nested function definitions, lambdas, and class bodies are skipped
        entirely (neither the scope node itself nor its contents are yielded),
        so smells inside helpers defined inside the test are not attributed to
        the test itself.
        """

        _NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

        def _walk(node: ast.AST) -> Iterator[ast.AST]:
            if isinstance(node, _NESTED_SCOPES):
                return
            yield node
            for child in ast.iter_child_nodes(node):
                yield from _walk(child)

        for stmt in self._test.node.body:
            yield from _walk(stmt)

    def _check_early_return(self) -> None:
        """Flag ``return`` statements in the test body.

        Tests have no reason to return a value; an early ``return`` is a common
        hack for "temporarily disabling" downstream assertions without deleting
        them, producing a test that silently passes. Nested function definitions
        are excluded by ``_walk_test_body``.
        """
        for node in self._walk_test_body():
            if not isinstance(node, ast.Return):
                continue
            self._result.add_issue(
                Issue(
                    rule="smells.early_return",
                    message="Test contains a 'return' which bypasses subsequent assertions",
                    severity=Severity.WARNING,
                    file_path=self._test.file_path,
                    line=node.lineno,
                    test_name=self._test.name,
                    suggestion=(
                        "Remove the 'return'; if the test should be conditional, "
                        "use @pytest.mark.skipif or split into separate tests"
                    ),
                )
            )

    def _check_swallowed_assertion(self) -> None:
        """Flag ``except AssertionError/Exception/BaseException`` inside a test.

        Catching one of these types silently swallows assertion failures, so the
        test appears to pass while its checks are effectively dead. Bare
        ``except:`` is already reported by ``patterns.bare_except`` and is not
        flagged here to avoid double reporting.
        """
        seen_lines: set[int] = set()
        for node in self._walk_test_body():
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if handler.type is None:
                    continue  # bare except -- handled by patterns.bare_except
                caught = self._exception_names_in(handler.type)
                swallowing = caught & _ASSERTION_SWALLOWING_EXCEPTIONS
                if not swallowing or handler.lineno in seen_lines:
                    continue
                seen_lines.add(handler.lineno)
                label = ", ".join(sorted(swallowing))
                self._result.add_issue(
                    Issue(
                        rule="smells.swallowed_assertion",
                        message=(
                            f"Test catches {label}, which silently swallows "
                            "assertion failures"
                        ),
                        severity=Severity.ERROR,
                        file_path=self._test.file_path,
                        line=handler.lineno,
                        test_name=self._test.name,
                        suggestion=(
                            "Use pytest.raises(...) for expected exceptions and "
                            "let AssertionError propagate"
                        ),
                    )
                )

    @staticmethod
    def _exception_names_in(node: ast.AST) -> set[str]:
        """Return the set of exception names referenced in an ``except`` type spec."""
        names: set[str] = set()
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                names.update(SmellVisitor._exception_names_in(elt))
        return names

    def _report_runtime_skips(self) -> None:
        """Emit one issue per ``pytest.skip(...)`` / ``pytest.xfail(...)`` call."""
        for lineno, name in self._runtime_skip_calls:
            self._result.add_issue(
                Issue(
                    rule="smells.ignored_test",
                    message=f"Test calls {name}(...) at runtime",
                    severity=Severity.WARNING,
                    file_path=self._test.file_path,
                    line=lineno,
                    test_name=self._test.name,
                    suggestion=(
                        "Prefer @pytest.mark.skipif at collection time, or remove "
                        "the skip once the underlying issue is resolved"
                    ),
                )
            )

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

    def _check_conditional_logic(self) -> None:
        """Check for if/else branches in test body."""
        for child in self._walk_test_body():
            if isinstance(child, ast.If):
                self._result.add_issue(
                    Issue(
                        rule="smells.conditional_test",
                        message="Test contains conditional logic (if/else)",
                        severity=Severity.WARNING,
                        file_path=self._test.file_path,
                        line=child.lineno,
                        test_name=self._test.name,
                        suggestion="Split into separate tests or use @pytest.mark.parametrize",
                    )
                )
                return  # Report once per test

    def _check_try_except(self) -> None:
        """Check for try/except blocks in test body."""
        for child in self._walk_test_body():
            if isinstance(child, ast.Try):
                self._result.add_issue(
                    Issue(
                        rule="smells.try_except_in_test",
                        message="Test contains try/except which may mask failures",
                        severity=Severity.WARNING,
                        file_path=self._test.file_path,
                        line=child.lineno,
                        test_name=self._test.name,
                        suggestion="Use pytest.raises() instead of try/except in tests",
                    )
                )
                return  # Report once per test

    def _check_fixture_overuse(self) -> None:
        """Check for too many parameters (fixtures)."""
        node = self._test.node
        args = node.args
        # Count all parameters except 'self' and 'cls'
        param_names = [a.arg for a in args.args if a.arg not in ("self", "cls")]
        param_count = (
            len(param_names)
            + len(args.kwonlyargs)
            + (1 if args.vararg else 0)
            + (1 if args.kwarg else 0)
        )
        if param_count > 5:
            self._result.add_issue(
                Issue(
                    rule="smells.too_many_fixtures",
                    message=(
                        f"Test has {param_count} parameters (fixtures); consider composing fixtures"
                    ),
                    severity=Severity.INFO,
                    file_path=self._test.file_path,
                    line=self._test.line,
                    test_name=self._test.name,
                    suggestion="Combine related fixtures into a composite fixture",
                )
            )
