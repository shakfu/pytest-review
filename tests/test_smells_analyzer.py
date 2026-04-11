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
    def test_detects_assertion_roulette(self) -> None:
        """Multiple assertions without messages is a smell."""
        source = """
def test_example():
    assert 1 == 1
    assert 2 == 2
    assert 3 == 3
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        assert result.has_warnings
        rules = [issue.rule for issue in result.issues]
        assert "smells.assertion_roulette" in rules

    def test_no_roulette_with_messages(self) -> None:
        """Assertions with messages are fine."""
        source = """
def test_example():
    assert 1 == 1, "one equals one"
    assert 2 == 2, "two equals two"
    assert 3 == 3, "three equals three"
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.assertion_roulette" not in rules

    def test_no_roulette_single_assertion(self) -> None:
        """Single assertion without message is fine."""
        source = """
def test_example():
    assert 1 == 1
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.assertion_roulette" not in rules

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

    def test_detects_magic_numbers(self) -> None:
        """Magic numbers in assertions are a smell."""
        source = """
def test_example():
    assert result == 42
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.magic_number" in rules

    def test_allows_common_numbers(self) -> None:
        """Common numbers like 0, 1, 2 are allowed."""
        source = """
def test_example():
    assert result == 0
    assert count == 1
    assert value == 2
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.magic_number" not in rules

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

    def test_detects_conditional_runtime_skip(self) -> None:
        """``pytest.skip(...)`` nested inside a branch is still flagged."""
        source = """
def test_example():
    if sys.platform == "win32":
        pytest.skip("unix-only")
    assert compute() == 42
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        skip_issues = [i for i in result.issues if i.rule == "smells.ignored_test"]
        assert len(skip_issues) >= 1

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

    def test_detects_early_return(self) -> None:
        """Early ``return`` in a test body is flagged."""
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

    def test_detects_eager_test(self) -> None:
        """Tests calling many distinct methods are flagged."""
        source = """
def test_example():
    result1 = foo()
    result2 = bar()
    result3 = baz()
    result4 = qux()
    assert result1 == 1
    assert result2 == 2
    assert result3 == 3
    assert result4 == 4
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.eager_test" in rules

    def test_no_eager_for_single_method(self) -> None:
        """Tests focusing on one method are fine."""
        source = """
def test_example():
    result1 = calculate(1)
    result2 = calculate(2)
    assert result1 == 1
    assert result2 == 4
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.eager_test" not in rules

    def test_detects_conditional_logic(self) -> None:
        source = """
def test_example():
    result = compute()
    if result > 0:
        assert result == 42
    else:
        assert result == 0
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.conditional_test" in rules

    def test_no_conditional_without_if(self) -> None:
        source = """
def test_example():
    result = compute()
    assert result == 42
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.conditional_test" not in rules

    def test_detects_too_many_fixtures(self) -> None:
        source = """
def test_example(db, cache, api_client, logger, config, mailer):
    assert db is not None
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.too_many_fixtures" in rules

    def test_no_fixture_overuse_with_few_params(self) -> None:
        source = """
def test_example(db, cache):
    assert db is not None
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.too_many_fixtures" not in rules

    def test_fixture_overuse_excludes_self(self) -> None:
        source = """
def test_example(self, db, cache, api, logger, config):
    assert db is not None
"""
        analyzer = SmellsAnalyzer(ReviewConfig())
        test_info = make_test_info(source)
        result = analyzer.analyze(test_info)

        rules = [issue.rule for issue in result.issues]
        assert "smells.too_many_fixtures" not in rules

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
