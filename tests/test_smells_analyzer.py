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
