"""Tests for the naming analyzer."""

from __future__ import annotations

import ast
from pathlib import Path

from pytest_review.analyzers.base import Severity, TestItemInfo
from pytest_review.analyzers.naming import NamingAnalyzer
from pytest_review.config import ReviewConfig


def make_test_info(source: str, name: str) -> TestItemInfo:
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


class TestNamingAnalyzer:
    def test_detects_numeric_name(self) -> None:
        source = "def test_1(): pass"
        config = ReviewConfig()
        analyzer = NamingAnalyzer(config)
        test_info = make_test_info(source, "test_1")

        result = analyzer.analyze(test_info)

        non_descriptive = [i for i in result.issues if i.rule == "naming.non_descriptive"]
        assert len(non_descriptive) == 1

    def test_detects_test_foo(self) -> None:
        source = "def test_foo(): pass"
        config = ReviewConfig()
        analyzer = NamingAnalyzer(config)
        test_info = make_test_info(source, "test_foo")

        result = analyzer.analyze(test_info)

        non_descriptive = [i for i in result.issues if i.rule == "naming.non_descriptive"]
        assert len(non_descriptive) == 1

    def test_detects_test_example(self) -> None:
        source = "def test_example(): pass"
        config = ReviewConfig()
        analyzer = NamingAnalyzer(config)
        test_info = make_test_info(source, "test_example")

        result = analyzer.analyze(test_info)

        non_descriptive = [i for i in result.issues if i.rule == "naming.non_descriptive"]
        assert len(non_descriptive) == 1

    def test_detects_short_name(self) -> None:
        source = "def test_add(): pass"
        config = ReviewConfig.from_dict({
            "analyzers": {"naming": {"enabled": True, "min_length": 10}}
        })
        analyzer = NamingAnalyzer(config)
        test_info = make_test_info(source, "test_add")

        result = analyzer.analyze(test_info)

        short_issues = [i for i in result.issues if i.rule == "naming.too_short"]
        assert len(short_issues) == 1
        assert short_issues[0].severity == Severity.INFO

    def test_accepts_descriptive_name(self) -> None:
        source = "def test_user_can_login_with_valid_credentials(): pass"
        config = ReviewConfig()
        analyzer = NamingAnalyzer(config)
        test_info = make_test_info(source, "test_user_can_login_with_valid_credentials")

        result = analyzer.analyze(test_info)

        # Should have no non_descriptive or too_short issues
        non_descriptive = [i for i in result.issues if i.rule == "naming.non_descriptive"]
        short_issues = [i for i in result.issues if i.rule == "naming.too_short"]
        assert len(non_descriptive) == 0
        assert len(short_issues) == 0

    def test_detects_non_snake_case(self) -> None:
        source = "def testUserCanLogin(): pass"
        config = ReviewConfig()
        analyzer = NamingAnalyzer(config)
        test_info = make_test_info(source, "testUserCanLogin")

        result = analyzer.analyze(test_info)

        snake_case_issues = [i for i in result.issues if i.rule == "naming.not_snake_case"]
        assert len(snake_case_issues) == 1

    def test_detects_missing_docstring_when_required(self) -> None:
        source = "def test_something_important(): pass"
        config = ReviewConfig.from_dict({
            "analyzers": {"naming": {"enabled": True, "require_docstring": True}}
        })
        analyzer = NamingAnalyzer(config)
        test_info = make_test_info(source, "test_something_important")

        result = analyzer.analyze(test_info)

        docstring_issues = [i for i in result.issues if i.rule == "naming.missing_docstring"]
        assert len(docstring_issues) == 1

    def test_accepts_test_with_docstring(self) -> None:
        source = '''
def test_with_docs():
    """This test verifies the documentation requirement."""
    pass
'''
        config = ReviewConfig.from_dict({
            "analyzers": {"naming": {"enabled": True, "require_docstring": True}}
        })
        analyzer = NamingAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_with_docs")

        result = analyzer.analyze(test_info)

        docstring_issues = [i for i in result.issues if i.rule == "naming.missing_docstring"]
        assert len(docstring_issues) == 0
