"""Tests for the assertions analyzer."""

from __future__ import annotations

import ast
from pathlib import Path

from pytest_review.analyzers.assertions import AssertionsAnalyzer
from pytest_review.analyzers.base import Severity, TestItemInfo
from pytest_review.config import ReviewConfig


def make_test_info(source: str, name: str = "test_example") -> TestItemInfo:
    """Helper to create TestItemInfo from source code."""
    tree = ast.parse(source)
    func_node = tree.body[0]
    assert isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef))
    return TestItemInfo(
        name=name,
        file_path=Path("test_file.py"),
        line=1,
        node=func_node,
        source=source,
    )


class TestAssertionsAnalyzer:
    def test_detects_empty_test(self) -> None:
        source = """
def test_empty():
    pass
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_empty")

        result = analyzer.analyze(test_info)

        assert result.issue_count == 1
        assert result.issues[0].rule == "assertions.missing"
        assert result.issues[0].severity == Severity.ERROR

    def test_detects_assert_true(self) -> None:
        source = """
def test_trivial():
    assert True
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_trivial")

        result = analyzer.analyze(test_info)

        # Should have trivial assertion issue
        trivial_issues = [i for i in result.issues if i.rule == "assertions.trivial"]
        assert len(trivial_issues) == 1
        assert "assert True" in trivial_issues[0].message

    def test_detects_assert_false(self) -> None:
        source = """
def test_always_fails():
    assert False
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_always_fails")

        result = analyzer.analyze(test_info)

        trivial_issues = [i for i in result.issues if i.rule == "assertions.trivial"]
        assert len(trivial_issues) == 1
        assert "assert False" in trivial_issues[0].message

    def test_detects_tautology(self) -> None:
        source = """
def test_tautology():
    x = 5
    assert x == x
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_tautology")

        result = analyzer.analyze(test_info)

        trivial_issues = [i for i in result.issues if i.rule == "assertions.trivial"]
        assert len(trivial_issues) == 1
        assert "comparing value to itself" in trivial_issues[0].message

    def test_accepts_valid_assertion(self) -> None:
        source = """
def test_valid():
    result = 1 + 1
    assert result == 2
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_valid")

        result = analyzer.analyze(test_info)

        assert result.issue_count == 0

    def test_counts_pytest_raises(self) -> None:
        source = """
def test_raises():
    import pytest
    with pytest.raises(ValueError):
        raise ValueError("test")
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_raises")

        result = analyzer.analyze(test_info)

        # pytest.raises counts as an assertion
        assert result.metadata["assertion_count"] == 1
        missing_issues = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing_issues) == 0

    def test_respects_min_assertions_config(self) -> None:
        source = """
def test_one_assertion():
    assert True is True
"""
        config = ReviewConfig.from_dict({
            "analyzers": {"assertions": {"enabled": True, "min_assertions": 2}}
        })
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_one_assertion")

        result = analyzer.analyze(test_info)

        insufficient_issues = [i for i in result.issues if i.rule == "assertions.insufficient"]
        assert len(insufficient_issues) == 1

    def test_stores_metadata(self) -> None:
        source = """
def test_with_assertions():
    x = 1
    assert x == 1
    assert x > 0
    assert True  # trivial
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_with_assertions")

        result = analyzer.analyze(test_info)

        assert result.metadata["assertion_count"] == 3
        assert result.metadata["trivial_count"] == 1
