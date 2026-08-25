"""Tests for the smells analyzer."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pytest_review.analyzers.base import TestItemInfo
from pytest_review.analyzers.smells import SmellsAnalyzer
from pytest_review.config import ReviewConfig


def make_test_info(source: str, name: str = "test_example") -> TestItemInfo:
    """Create a TestItemInfo from source code."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return TestItemInfo(
                name=name,
                file_path=Path("/test.py"),
                line=node.lineno,
                node=node,
                source=source,
            )
    raise ValueError(f"Could not find function {name}")


class TestSmellsAnalyzer:
    def test_detects_duplicate_assertions(self) -> None:
        """Duplicate assertions are a smell."""
        source = """
def test_example():
    assert x == 1
    assert y == 2
    assert x == 1
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        assert result.has_warnings
        rules = [issue.rule for issue in result.issues]
        assert "smells.duplicate_assert" in rules

    def _rules(self, source: str) -> list[str]:
        analyzer = SmellsAnalyzer(ReviewConfig())
        return [i.rule for i in analyzer.analyze(make_test_info(source)).issues]

    def test_detects_vacuous_loop(self) -> None:
        """Every assertion inside a loop -> the test passes on an empty iterable."""
        source = """
def test_example(items):
    for item in items:
        assert item.ok
"""
        assert "smells.vacuous_loop" in self._rules(source)

    def test_loop_over_nonempty_literal_is_not_vacuous(self) -> None:
        source = """
def test_example():
    for value in [1, 2, 3]:
        assert value > 0
"""
        assert "smells.vacuous_loop" not in self._rules(source)

    def test_loop_over_positive_range_is_not_vacuous(self) -> None:
        source = """
def test_example():
    for i in range(3):
        assert i >= 0
"""
        assert "smells.vacuous_loop" not in self._rules(source)

    def test_unconditional_assertion_makes_loop_safe(self) -> None:
        """One assertion outside the loop means the test cannot pass vacuously."""
        source = """
def test_example(items):
    assert items
    for item in items:
        assert item.ok
"""
        assert "smells.vacuous_loop" not in self._rules(source)

    def test_no_duplicate_for_invariant_across_a_state_change(self) -> None:
        """Re-asserting an expression after a mutation is correct, not duplication.

        This is the standard way to check that an operation had an effect. The
        rule keys on repeats within an unbroken run of assertions, so any
        intervening statement starts a new run.
        """
        source = """
def test_example():
    result = make()
    assert result.has_errors is False
    result.add_issue(err)
    assert result.has_errors is False
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        result = analyzer.analyze(make_test_info(source))

        rules = [issue.rule for issue in result.issues]
        assert "smells.duplicate_assert" not in rules

    def test_no_duplicate_for_similar_assertions(self) -> None:
        """Similar but different assertions are fine."""
        source = """
def test_example():
    assert x == 1
    assert y == 1
    assert z == 1
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.duplicate_assert" not in rules

    def test_detects_skip_decorator(self) -> None:
        """Skipped tests are flagged."""
        source = """
@pytest.mark.skip(reason="not implemented")
def test_example():
    assert True
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        assert result.has_warnings
        rules = [issue.rule for issue in result.issues]
        assert "smells.ignored_test" in rules

    def test_detects_skipif_decorator(self) -> None:
        """Conditionally skipped tests are flagged."""
        source = """
@pytest.mark.skipif(True, reason="conditional")
def test_example():
    assert True
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        assert result.has_warnings
        rules = [issue.rule for issue in result.issues]
        assert "smells.ignored_test" in rules

    def test_detects_bare_mark_skip_decorator(self) -> None:
        """``@mark.skip`` (from ``pytest import mark``) is flagged."""
        source = """
@mark.skip(reason="not ready")
def test_example():
    assert True
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.ignored_test" in rules

    def test_detects_runtime_pytest_skip(self) -> None:
        """``pytest.skip(...)`` inside a test body is flagged."""
        source = """
def test_example():
    pytest.skip("not implemented")
    assert True
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.ignored_test" in rules
        skip_issues = [i for i in result.issues if i.rule == "smells.ignored_test"]
        assert any("pytest.skip" in issue.message for issue in skip_issues)

    def test_detects_runtime_pytest_xfail(self) -> None:
        """``pytest.xfail(...)`` inside a test body is flagged."""
        source = """
def test_example():
    pytest.xfail("known bug")
    assert compute() == 42
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        skip_issues = [i for i in result.issues if i.rule == "smells.ignored_test"]
        assert any("pytest.xfail" in issue.message for issue in skip_issues)

    def test_guarded_raise_skip_test_not_flagged(self) -> None:
        """``raise SkipTest`` inside an ``if`` is also a gate, not a dead test."""
        source = """
def test_example():
    if sys.platform == "win32":
        raise SkipTest("unix-only")
    assert compute() == 42
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        skip_issues = [i for i in result.issues if i.rule == "smells.ignored_test"]
        assert len(skip_issues) == 0

    def test_does_not_flag_importorskip(self) -> None:
        """``pytest.importorskip(...)`` is not flagged (legitimate gate)."""
        source = """
def test_example():
    numpy = pytest.importorskip("numpy")
    assert numpy.zeros(3).sum() == 0
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        skip_issues = [i for i in result.issues if i.rule == "smells.ignored_test"]
        assert len(skip_issues) == 0

    def test_does_not_flag_user_defined_skip(self) -> None:
        """Bare ``skip(...)`` (not qualified ``pytest.skip``) is not flagged."""
        source = """
def test_example():
    skip = compute_skip_count()
    assert skip == 0
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        skip_issues = [i for i in result.issues if i.rule == "smells.ignored_test"]
        assert len(skip_issues) == 0

    def test_detects_self_skip_test(self) -> None:
        """``self.skipTest(...)`` (unittest style) is flagged."""
        source = """
def test_example(self):
    self.skipTest("not ready")
    self.assertEqual(compute(), 42)
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        skip_issues = [i for i in result.issues if i.rule == "smells.ignored_test"]
        assert any("self.skipTest" in issue.message for issue in skip_issues)

    def test_detects_raise_skip_test(self) -> None:
        """``raise unittest.SkipTest(...)`` is flagged."""
        source = """
def test_example():
    raise unittest.SkipTest("not implemented")
    assert compute() == 42
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        skip_issues = [i for i in result.issues if i.rule == "smells.ignored_test"]
        assert any("SkipTest" in issue.message for issue in skip_issues)

    def test_detects_bare_raise_skip_test(self) -> None:
        """``raise SkipTest(...)`` (imported from unittest) is flagged."""
        source = """
def test_example():
    raise SkipTest("not ready")
    assert True
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        skip_issues = [i for i in result.issues if i.rule == "smells.ignored_test"]
        assert len(skip_issues) >= 1

    def test_does_not_flag_guard_return(self) -> None:
        """A ``return`` that is the sole body of an ``if`` is a toggle, not a bypass."""
        source = """
def test_example():
    if flaky:
        return
    assert compute() == 42
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        early_return = [i for i in result.issues if i.rule == "smells.early_return"]
        assert len(early_return) == 0

    def test_detects_unconditional_early_return(self) -> None:
        """An unconditional mid-body ``return`` bypasses assertions."""
        source = """
def test_example():
    result = compute()
    if result > 0:
        assert result == 42
    return
    assert result == 0
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        early_return = [i for i in result.issues if i.rule == "smells.early_return"]
        assert len(early_return) == 1

    def test_detects_trailing_return(self) -> None:
        """Even a trailing ``return`` is flagged (tests should not return)."""
        source = """
def test_example():
    assert compute() == 42
    return
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        early_return = [i for i in result.issues if i.rule == "smells.early_return"]
        assert len(early_return) == 1

    def test_return_in_nested_function_not_flagged(self) -> None:
        """``return`` inside a helper nested in the test is not attributed to the test."""
        source = """
def test_example():
    def helper():
        return 42
    assert helper() == 42
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        early_return = [i for i in result.issues if i.rule == "smells.early_return"]
        assert len(early_return) == 0

    def test_lambda_return_not_flagged(self) -> None:
        """Lambda bodies are not scanned for early_return."""
        source = """
def test_example():
    fn = lambda x: x + 1
    assert fn(41) == 42
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        early_return = [i for i in result.issues if i.rule == "smells.early_return"]
        assert len(early_return) == 0

    def test_detects_swallowed_assertion_error(self) -> None:
        """``except AssertionError`` is flagged as ERROR."""
        source = """
def test_example():
    try:
        assert compute() == 42
    except AssertionError:
        pass
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        swallowed = [i for i in result.issues if i.rule == "smells.swallowed_assertion"]
        assert len(swallowed) == 1
        assert swallowed[0].severity.value == "error"
        assert "AssertionError" in swallowed[0].message

    def test_detects_swallowed_exception(self) -> None:
        """``except Exception`` is flagged because it also swallows AssertionError."""
        source = """
def test_example():
    try:
        assert compute() == 42
    except Exception:
        pass
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        swallowed = [i for i in result.issues if i.rule == "smells.swallowed_assertion"]
        assert len(swallowed) == 1
        assert "Exception" in swallowed[0].message

    def test_detects_swallowed_assertion_in_tuple(self) -> None:
        """``except (AssertionError, KeyError):`` is still flagged."""
        source = """
def test_example():
    try:
        assert compute() == 42
    except (KeyError, AssertionError):
        pass
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        swallowed = [i for i in result.issues if i.rule == "smells.swallowed_assertion"]
        assert len(swallowed) == 1

    def test_specific_exception_not_flagged(self) -> None:
        """``except ValueError`` does not swallow AssertionError and is not flagged."""
        source = """
def test_example():
    try:
        do_work()
    except ValueError:
        pytest.fail("unexpected ValueError")
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        swallowed = [i for i in result.issues if i.rule == "smells.swallowed_assertion"]
        assert len(swallowed) == 0

    def test_bare_except_not_double_flagged_here(self) -> None:
        """Bare ``except:`` is not flagged by swallowed_assertion (bare_except handles it)."""
        source = """
def test_example():
    try:
        assert compute() == 42
    except:
        pass
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        swallowed = [i for i in result.issues if i.rule == "smells.swallowed_assertion"]
        assert len(swallowed) == 0

    def test_detects_try_except_in_test(self) -> None:
        source = """
def test_example():
    try:
        result = risky_operation()
    except ValueError:
        result = None
    assert result is not None
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.try_except_in_test" in rules

    def test_no_try_except_without_try(self) -> None:
        source = """
def test_example():
    result = safe_operation()
    assert result == 42
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.try_except_in_test" not in rules

    def test_no_try_except_for_finally_block(self) -> None:
        """``try/finally`` has no handlers and cannot mask failures."""
        source = """
def test_example():
    try:
        write_output()
    finally:
        cleanup()
    assert True
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.try_except_in_test" not in rules

    def test_stores_metadata(self) -> None:
        """Analyzer stores metadata in result."""
        source = """
def test_example():
    assert 1 == 1
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        assert result.analyzer_name == "smells"


class TestSmellsAnalyzerIntegration:
    """Integration tests using pytester."""

    def test_detects_assertion_roulette_in_real_test(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_multiple_assertions_no_messages():
                x = 1
                assert x == 1
                assert x + 1 == 2
                assert x + 2 == 3
                assert x + 3 == 4
                assert x + 4 == 5
        """)

        result = pytester.runpytest("--review", "--review-only=smells")
        result.assert_outcomes(passed=1)
        assert "assertion_roulette" in result.stdout.str()

    def test_detects_skipped_test_in_real_run(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            import pytest

            @pytest.mark.skip(reason="demo")
            def test_skipped():
                assert True
        """)

        result = pytester.runpytest("--review", "--review-only=smells", "-v")
        result.assert_outcomes(skipped=1)
        # The issue is detected but output goes to captured stdout
        assert "skipped with @pytest.mark.skip" in result.stdout.str()

    def test_detects_runtime_skip_in_real_run(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            import pytest

            def test_runtime_skipped():
                pytest.skip("demo")
                assert True
        """)

        result = pytester.runpytest("--review", "--review-only=smells", "-v")
        result.assert_outcomes(skipped=1)
        assert "pytest.skip" in result.stdout.str()
        assert "runtime" in result.stdout.str()
