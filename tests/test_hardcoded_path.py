"""Tests for hardcoded path detection in the patterns analyzer."""

from __future__ import annotations

import ast
from pathlib import Path

from pytest_review.analyzers.base import Severity, TestItemInfo
from pytest_review.analyzers.patterns import PatternsAnalyzer
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


class TestHardcodedPath:
    def test_detects_absolute_path_arg(self) -> None:
        source = """
def test_open_tmp():
    with open("/tmp/data.txt") as f:
        assert f.read()
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_open_tmp")

        result = analyzer.analyze(test_info)

        path_issues = [i for i in result.issues if i.rule == "patterns.hardcoded_path"]
        assert len(path_issues) == 1
        assert path_issues[0].severity == Severity.INFO

    def test_detects_pathlib_path_arg(self) -> None:
        source = """
def test_pathlib_path():
    p = Path("/home/user/config.yaml")
    assert p.exists()
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_pathlib_path")

        result = analyzer.analyze(test_info)

        path_issues = [i for i in result.issues if i.rule == "patterns.hardcoded_path"]
        assert len(path_issues) == 1

    def test_no_flag_for_expected_output_string(self) -> None:
        """A URL path in an expected output is not a filesystem path."""
        source = """
def test_html():
    html = render('/home/user/profile')
    assert html == '<a href="/home/user/profile">x</a>'
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_html")

        result = analyzer.analyze(test_info)

        path_issues = [i for i in result.issues if i.rule == "patterns.hardcoded_path"]
        assert len(path_issues) == 0
