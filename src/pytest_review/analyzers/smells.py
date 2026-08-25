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
from collections.abc import Iterator
from typing import TYPE_CHECKING

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

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        """Analyze test for smells."""
        visitor = SmellVisitor(test, result, self)
        visitor.visit(test.node)


class SmellVisitor(ast.NodeVisitor):
    """AST visitor that detects test smells."""

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
        self._has_skip_marker = False
        self._runtime_skip_calls: list[tuple[int, str, bool]] = []
        self._if_depth = 0

    def visit_Assert(self, node: ast.Assert) -> None:
        """Track assertions for duplicate detection."""
        self._assertions.append(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Track calls for runtime-skip detection."""
        self._check_runtime_skip(node)
        self.generic_visit(node)

    def _check_runtime_skip(self, node: ast.Call) -> None:
        """Record runtime skip calls in the test body.

        Matches:
        - ``pytest.skip(...)`` / ``pytest.xfail(...)`` (qualified only, to avoid
          false-positives from user code with a ``skip`` helper).
        - ``self.skipTest(...)`` (unittest.TestCase style).

        The third element records whether the call sits inside an ``if``: a
        *guarded* skip is the documented pattern for "skip on this platform",
        not a dead test, so it is not reported by ``_report_runtime_skips``.
        ``pytest.importorskip(...)`` is deliberately excluded because it expresses
        a legitimate optional-dependency gate, not a dead test.
        """
        func = node.func
        if not isinstance(func, ast.Attribute):
            return
        if not isinstance(func.value, ast.Name):
            return
        guarded = self._if_depth > 0
        # pytest.skip / pytest.xfail
        if func.value.id == "pytest" and func.attr in ("skip", "xfail"):
            self._runtime_skip_calls.append((node.lineno, f"pytest.{func.attr}", guarded))
            return
        # self.skipTest (unittest.TestCase.skipTest)
        if func.value.id == "self" and func.attr == "skipTest":
            self._runtime_skip_calls.append((node.lineno, "self.skipTest", guarded))

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
            self._runtime_skip_calls.append((node.lineno, "raise SkipTest", self._if_depth > 0))
            return
        if isinstance(target, ast.Attribute) and target.attr == "SkipTest":
            qualifier = ""
            if isinstance(target.value, ast.Name):
                qualifier = f"{target.value.id}."
            self._runtime_skip_calls.append(
                (node.lineno, f"raise {qualifier}SkipTest", self._if_depth > 0)
            )

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
        self._check_duplicate_assertions()
        self._check_vacuous_loop()
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

    def visit_If(self, node: ast.If) -> None:
        """Track conditional depth so guarded skip calls aren't treated as dead tests."""
        self._if_depth += 1
        self.generic_visit(node)
        self._if_depth -= 1

    def _guard_return_ids(self) -> set[int]:
        """Ids of early-returns that are the sole body of an ``if``.

        ``if not os.environ.get("CI"): return`` is a deliberate test toggle,
        not a bypass hack, so it must not be flagged.
        """
        guard_ids: set[int] = set()
        for node in self._walk_test_body():
            if not isinstance(node, ast.If):
                continue
            for branch in (node.body, node.orelse):
                if len(branch) == 1 and isinstance(branch[0], ast.Return):
                    guard_ids.add(id(branch[0]))
        return guard_ids

    def _check_early_return(self) -> None:
        """Flag ``return`` statements in the test body.

        Tests have no reason to return a value; an early ``return`` is a common
        hack for "temporarily disabling" downstream assertions without deleting
        them, producing a test that silently passes. Guard returns (the sole
        body of an ``if``) are deliberate toggles and are exempt. Nested
        function definitions are excluded by ``_walk_test_body``.
        """
        for node in self._walk_test_body():
            if not isinstance(node, ast.Return):
                continue
            if id(node) in self._guard_return_ids():
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
                            f"Test catches {label}, which silently swallows assertion failures"
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
        """Emit one issue per unguarded ``pytest.skip(...)`` call.

        Skips guarded by an ``if`` (the documented platform-gate pattern) are
        not dead tests and are not reported.
        """
        for lineno, name, guarded in self._runtime_skip_calls:
            if guarded:
                continue
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

    @staticmethod
    def _is_known_nonempty(iterable: ast.expr) -> bool:
        """True when the loop provably runs at least once.

        Looping over a literal with elements, or ``range`` of a positive
        constant, cannot be vacuous, so those must not be reported.
        """
        if isinstance(iterable, (ast.List, ast.Tuple, ast.Set)):
            return len(iterable.elts) > 0
        if isinstance(iterable, ast.Dict):
            return len(iterable.keys) > 0
        if (
            isinstance(iterable, ast.Call)
            and isinstance(iterable.func, ast.Name)
            and iterable.func.id == "range"
            and iterable.args
        ):
            first = iterable.args[0]
            return (
                isinstance(first, ast.Constant)
                and isinstance(first.value, int)
                and first.value > 0
            )
        return False

    def _check_vacuous_loop(self) -> None:
        """Flag a test whose every assertion sits inside a ``for`` body.

        If the iterable turns out to be empty the loop body never runs and the
        test passes having verified nothing -- a failure mode that survives
        refactors silently, because the test stays green.
        """
        if not self._assertions:
            return

        loop_assertions: set[int] = set()
        vacuous_loops: list[ast.For | ast.AsyncFor] = []
        for node in self._walk_test_body():
            if not isinstance(node, (ast.For, ast.AsyncFor)):
                continue
            inner = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
            if not inner:
                continue
            if self._is_known_nonempty(node.iter):
                continue
            if node.orelse:  # for/else runs when the loop did not break
                continue
            loop_assertions.update(id(a) for a in inner)
            vacuous_loops.append(node)

        if not vacuous_loops:
            return
        if any(id(a) not in loop_assertions for a in self._assertions):
            return  # at least one assertion runs unconditionally

        self._result.add_issue(
            Issue(
                rule="smells.vacuous_loop",
                message=(
                    "Every assertion is inside a for loop; the test passes without "
                    "verifying anything if the iterable is empty"
                ),
                severity=Severity.WARNING,
                file_path=self._test.file_path,
                line=vacuous_loops[0].lineno,
                test_name=self._test.name,
                suggestion="Assert the collection is non-empty first, or use parametrize",
            )
        )

    def _statement_blocks(self) -> Iterator[list[ast.stmt]]:
        """Yield every statement list in the test body, innermost blocks included."""
        stack: list[list[ast.stmt]] = [self._test.node.body]
        while stack:
            block = stack.pop()
            yield block
            for stmt in block:
                for field in ("body", "orelse", "finalbody"):
                    nested = getattr(stmt, field, None)
                    if isinstance(nested, list) and nested and isinstance(nested[0], ast.stmt):
                        stack.append(nested)
                for handler in getattr(stmt, "handlers", []) or []:
                    stack.append(handler.body)

    def _check_duplicate_assertions(self) -> None:
        """Flag an assertion repeated with nothing happening in between.

        Only repeats within an unbroken run of assertions count. Re-asserting
        the same expression after an intervening statement is the standard way
        to check an invariant across a state change::

            assert result.has_errors is False
            result.add_issue(...)          # <- state changes here
            assert result.has_errors is True

        Treating that as duplication reports correct code, which is exactly the
        kind of finding this rule set exists to avoid.
        """
        duplicates: list[tuple[int, str]] = []

        for stmt_list in self._statement_blocks():
            # Assertions do not mutate anything, so a run of consecutive
            # assertions is compared as a group; any other statement may change
            # state and starts a new run.
            seen_in_run: set[str] = set()
            for stmt in stmt_list:
                if isinstance(stmt, ast.Assert):
                    current = ast.dump(stmt.test)
                    if current in seen_in_run:
                        duplicates.append((stmt.lineno, current))
                    seen_in_run.add(current)
                else:
                    seen_in_run.clear()

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

    def _check_try_except(self) -> None:
        """Check for try/except blocks in test body."""
        for child in self._walk_test_body():
            # try/finally has no handlers and cannot mask failures
            if isinstance(child, ast.Try) and child.handlers:
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
