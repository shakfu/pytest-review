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
        config = ReviewConfig.from_dict(
            {"analyzers": {"assertions": {"enabled": True, "min_assertions": 2}}}
        )
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_one_assertion")

        result = analyzer.analyze(test_info)

        insufficient_issues = [i for i in result.issues if i.rule == "assertions.insufficient"]
        assert len(insufficient_issues) == 1

    def test_detects_isinstance_assertion(self) -> None:
        source = """
def test_isinstance():
    result = get_result()
    assert isinstance(result, dict)
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_isinstance")

        result = analyzer.analyze(test_info)

        low_value = [i for i in result.issues if i.rule == "assertions.low_value"]
        assert len(low_value) == 1
        assert "isinstance" in low_value[0].message
        assert low_value[0].severity == Severity.INFO

    def test_detects_is_not_none_assertion(self) -> None:
        source = """
def test_not_none():
    result = get_result()
    assert result is not None
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_not_none")

        result = analyzer.analyze(test_info)

        low_value = [i for i in result.issues if i.rule == "assertions.low_value"]
        assert len(low_value) == 1
        assert "is not None" in low_value[0].message

    def test_no_low_value_for_equality_check(self) -> None:
        source = """
def test_equality():
    result = get_result()
    assert result == 42
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_equality")

        result = analyzer.analyze(test_info)

        low_value = [i for i in result.issues if i.rule == "assertions.low_value"]
        assert len(low_value) == 0

    def test_detects_raises_without_match(self) -> None:
        source = """
def test_raises_no_match():
    import pytest
    with pytest.raises(ValueError):
        do_something()
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_raises_no_match")

        result = analyzer.analyze(test_info)

        match_issues = [i for i in result.issues if i.rule == "assertions.raises_without_match"]
        assert len(match_issues) == 1
        assert "ValueError" in match_issues[0].message
        assert match_issues[0].severity == Severity.INFO

    def test_no_raises_issue_with_match(self) -> None:
        source = """
def test_raises_with_match():
    import pytest
    with pytest.raises(ValueError, match="invalid"):
        do_something()
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_raises_with_match")

        result = analyzer.analyze(test_info)

        match_issues = [i for i in result.issues if i.rule == "assertions.raises_without_match"]
        assert len(match_issues) == 0

    def test_detects_yoda_condition(self) -> None:
        source = """
def test_yoda():
    x = 42
    assert 42 == x
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_yoda")

        result = analyzer.analyze(test_info)

        yoda_issues = [i for i in result.issues if i.rule == "assertions.yoda_condition"]
        assert len(yoda_issues) == 1
        assert "42" in yoda_issues[0].message
        assert yoda_issues[0].severity == Severity.INFO

    def test_no_yoda_for_normal_order(self) -> None:
        source = """
def test_normal():
    x = 42
    assert x == 42
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_normal")

        result = analyzer.analyze(test_info)

        yoda_issues = [i for i in result.issues if i.rule == "assertions.yoda_condition"]
        assert len(yoda_issues) == 0

    def test_no_yoda_for_none_comparison(self) -> None:
        source = """
def test_none_check():
    x = get_value()
    assert None == x
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_none_check")

        result = analyzer.analyze(test_info)

        yoda_issues = [i for i in result.issues if i.rule == "assertions.yoda_condition"]
        assert len(yoda_issues) == 0

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
