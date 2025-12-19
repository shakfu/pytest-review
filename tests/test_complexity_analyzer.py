"""Tests for the complexity analyzer."""

from __future__ import annotations

import ast
from pathlib import Path

from pytest_review.analyzers.base import TestItemInfo
from pytest_review.analyzers.complexity import ComplexityAnalyzer
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


class TestComplexityAnalyzer:
    def test_simple_test_passes(self) -> None:
        source = """
def test_simple():
    result = 1 + 1
    assert result == 2
"""
        config = ReviewConfig()
        analyzer = ComplexityAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_simple")

        result = analyzer.analyze(test_info)

        assert result.issue_count == 0

    def test_detects_too_many_statements(self) -> None:
        # Create a test with many statements
        statements = "\n    ".join([f"x{i} = {i}" for i in range(25)])
        source = f"""
def test_many_statements():
    {statements}
    assert True
"""
        config = ReviewConfig.from_dict(
            {"analyzers": {"complexity": {"enabled": True, "max_statements": 20}}}
        )
        analyzer = ComplexityAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_many_statements")

        result = analyzer.analyze(test_info)

        statement_issues = [i for i in result.issues if i.rule == "complexity.too_many_statements"]
        assert len(statement_issues) == 1

    def test_detects_deep_nesting(self) -> None:
        source = """
def test_deep_nesting():
    if True:
        if True:
            if True:
                if True:
                    assert True
"""
        config = ReviewConfig.from_dict(
            {"analyzers": {"complexity": {"enabled": True, "max_depth": 3}}}
        )
        analyzer = ComplexityAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_deep_nesting")

        result = analyzer.analyze(test_info)

        depth_issues = [i for i in result.issues if i.rule == "complexity.deep_nesting"]
        assert len(depth_issues) == 1

    def test_detects_high_cyclomatic_complexity(self) -> None:
        source = """
def test_complex():
    x = 1
    if x > 0:
        pass
    elif x < 0:
        pass
    else:
        pass

    for i in range(10):
        if i % 2 == 0:
            pass

    while x > 0:
        x -= 1
"""
        config = ReviewConfig.from_dict(
            {"analyzers": {"complexity": {"enabled": True, "max_complexity": 3}}}
        )
        analyzer = ComplexityAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_complex")

        result = analyzer.analyze(test_info)

        complexity_issues = [i for i in result.issues if i.rule == "complexity.high_cyclomatic"]
        assert len(complexity_issues) == 1

    def test_counts_boolean_operators(self) -> None:
        source = """
def test_boolean_complexity():
    x = 1
    if x > 0 and x < 10 or x == 100:
        assert True
"""
        config = ReviewConfig.from_dict(
            {"analyzers": {"complexity": {"enabled": True, "max_complexity": 2}}}
        )
        analyzer = ComplexityAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_boolean_complexity")

        result = analyzer.analyze(test_info)

        # Should have high complexity due to and/or
        complexity_issues = [i for i in result.issues if i.rule == "complexity.high_cyclomatic"]
        assert len(complexity_issues) == 1

    def test_stores_metadata(self) -> None:
        source = """
def test_metadata():
    x = 1
    y = 2
    if x > 0:
        for i in range(10):
            pass
    assert True
"""
        config = ReviewConfig()
        analyzer = ComplexityAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_metadata")

        result = analyzer.analyze(test_info)

        assert "statement_count" in result.metadata
        assert "max_depth" in result.metadata
        assert "cyclomatic_complexity" in result.metadata
        assert result.metadata["max_depth"] == 2  # if -> for

    def test_with_context_counts_depth(self) -> None:
        source = """
def test_with_statement():
    with open("file") as f:
        if True:
            for line in f:
                assert line
"""
        config = ReviewConfig.from_dict(
            {"analyzers": {"complexity": {"enabled": True, "max_depth": 2}}}
        )
        analyzer = ComplexityAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_with_statement")

        result = analyzer.analyze(test_info)

        # with -> if -> for = depth 3
        depth_issues = [i for i in result.issues if i.rule == "complexity.deep_nesting"]
        assert len(depth_issues) == 1
