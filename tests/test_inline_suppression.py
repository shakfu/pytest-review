"""Tests for inline suppression via # review: ignore[rule] comments."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pytest_review.analyzers.assertions import AssertionsAnalyzer
from pytest_review.analyzers.base import (
    TestItemInfo,
    parse_suppressed_rules,
)
from pytest_review.config import ReviewConfig


class TestParseSuppressedRules:
    def test_no_comments_returns_empty_set(self) -> None:
        source = "def test_example():\n    assert True\n"
        assert parse_suppressed_rules(source) == set()

    def test_single_rule(self) -> None:
        source = "def test_example():  # review: ignore[assertions.trivial]\n    assert True\n"
        assert parse_suppressed_rules(source) == {"assertions.trivial"}

    def test_multiple_rules_in_one_comment(self) -> None:
        source = (
            "# review: ignore[assertions.trivial,assertions.missing]\ndef test_x():\n    pass\n"
        )
        assert parse_suppressed_rules(source) == {"assertions.trivial", "assertions.missing"}

    def test_multiple_comments(self) -> None:
        source = (
            "# review: ignore[assertions.trivial]\n"
            "def test_x():  # review: ignore[smells.early_return]\n"
            "    assert True\n"
        )
        assert parse_suppressed_rules(source) == {"assertions.trivial", "smells.early_return"}

    def test_whitespace_tolerance(self) -> None:
        source = "#  review:  ignore[ foo.bar , baz.qux ]\ndef test_x(): pass\n"
        assert parse_suppressed_rules(source) == {"foo.bar", "baz.qux"}

    def test_ignores_unrelated_comments(self) -> None:
        source = "# this is a normal comment\n# review: ignore[a.b]\ndef test_x(): pass\n"
        assert parse_suppressed_rules(source) == {"a.b"}


class TestInlineSuppressionInAnalyzer:
    def _make_test_info(
        self, source: str, name: str = "test_example", suppressed: set[str] | None = None
    ) -> TestItemInfo:
        tree = ast.parse(source)
        func_node = tree.body[0]
        assert isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef))
        return TestItemInfo(
            name=name,
            file_path=Path("test_file.py"),
            line=1,
            node=func_node,
            source=source,
            suppressed_rules=suppressed or set(),
        )

    def test_suppressed_rule_is_filtered_from_results(self) -> None:
        source = "def test_example():\n    assert True\n"
        test_info = self._make_test_info(source, suppressed={"assertions.trivial"})

        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        result = analyzer.analyze(test_info)

        trivial_issues = [i for i in result.issues if i.rule == "assertions.trivial"]
        assert len(trivial_issues) == 0

    def test_non_suppressed_rules_remain(self) -> None:
        source = "def test_example():\n    pass\n"
        test_info = self._make_test_info(source, suppressed={"smells.early_return"})

        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        result = analyzer.analyze(test_info)

        missing_issues = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing_issues) == 1

    def test_no_suppression_all_issues_reported(self) -> None:
        source = "def test_example():\n    assert True\n"
        test_info = self._make_test_info(source)

        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        result = analyzer.analyze(test_info)

        trivial_issues = [i for i in result.issues if i.rule == "assertions.trivial"]
        assert len(trivial_issues) == 1


class TestInlineSuppressionIntegration:
    """Integration tests using pytester."""

    def test_inline_suppression_hides_issue_from_report(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            # review: ignore[assertions.trivial]
            def test_intentionally_trivial_assertion():
                assert True
        """)
        result = pytester.runpytest("--review", "--review-only=assertions")
        result.assert_outcomes(passed=1)
        assert "assertions.trivial" not in result.stdout.str()

    def test_non_suppressed_issues_still_reported(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            # review: ignore[smells.early_return]
            def test_empty():
                pass
        """)
        result = pytester.runpytest("--review", "--review-only=assertions")
        result.assert_outcomes(passed=1)
        output = result.stdout.str()
        assert "assertions.missing" in output or "no assertions" in output.lower()

    def test_multiple_rules_suppressed(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            # review: ignore[assertions.trivial,smells.early_return]
            def test_x():
                assert True
        """)
        result = pytester.runpytest("--review", "--review-only=assertions,smells")
        result.assert_outcomes(passed=1)
        assert "assertions.trivial" not in result.stdout.str()
