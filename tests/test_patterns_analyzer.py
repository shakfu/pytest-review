"""Tests for the patterns analyzer."""

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


class TestPatternsAnalyzer:
    def test_detects_bare_except(self) -> None:
        source = """
def test_bare_except():
    try:
        risky()
    except:
        pass
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_bare_except")

        result = analyzer.analyze(test_info)

        bare_except_issues = [i for i in result.issues if i.rule == "patterns.bare_except"]
        assert len(bare_except_issues) == 1
        assert bare_except_issues[0].severity == Severity.WARNING

    def test_detects_swallowed_exception(self) -> None:
        source = """
def test_swallowed():
    try:
        risky()
    except Exception:
        pass
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_swallowed")

        result = analyzer.analyze(test_info)

        swallowed_issues = [i for i in result.issues if i.rule == "patterns.swallowed_exception"]
        assert len(swallowed_issues) == 1

    def test_detects_sleep_in_test(self) -> None:
        source = """
def test_with_sleep():
    import time
    time.sleep(1)
    assert True
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_with_sleep")

        result = analyzer.analyze(test_info)

        sleep_issues = [i for i in result.issues if i.rule == "patterns.sleep_in_test"]
        assert len(sleep_issues) == 1
        assert sleep_issues[0].severity == Severity.WARNING

    def test_detects_print_statement(self) -> None:
        source = """
def test_with_print():
    print("debugging")
    assert True
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_with_print")

        result = analyzer.analyze(test_info)

        print_issues = [i for i in result.issues if i.rule == "patterns.print_statement"]
        assert len(print_issues) == 1
        assert print_issues[0].severity == Severity.INFO

    def test_detects_os_system(self) -> None:
        source = """
def test_with_os_system():
    import os
    os.system("ls")
    assert True
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_with_os_system")

        result = analyzer.analyze(test_info)

        os_system_issues = [i for i in result.issues if i.rule == "patterns.os_system"]
        assert len(os_system_issues) == 1

    def test_detects_is_with_literal(self) -> None:
        source = """
def test_is_literal():
    x = 100
    assert x is 100
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_is_literal")

        result = analyzer.analyze(test_info)

        is_literal_issues = [i for i in result.issues if i.rule == "patterns.is_literal"]
        assert len(is_literal_issues) == 1

    def test_allows_is_with_none(self) -> None:
        source = """
def test_is_none():
    x = None
    assert x is None
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_is_none")

        result = analyzer.analyze(test_info)

        is_literal_issues = [i for i in result.issues if i.rule == "patterns.is_literal"]
        assert len(is_literal_issues) == 0

    def test_allows_is_with_true_false(self) -> None:
        source = """
def test_is_bool():
    x = True
    assert x is True
    assert x is not False
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_is_bool")

        result = analyzer.analyze(test_info)

        is_literal_issues = [i for i in result.issues if i.rule == "patterns.is_literal"]
        assert len(is_literal_issues) == 0

    def test_detects_legacy_mock_import(self) -> None:
        source = """
def test_legacy_mock():
    import mock
    m = mock.Mock()
    assert m
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_legacy_mock")

        result = analyzer.analyze(test_info)

        mock_issues = [i for i in result.issues if i.rule == "patterns.legacy_mock"]
        assert len(mock_issues) == 1

    def test_detects_legacy_mock_from_import(self) -> None:
        source = """
def test_legacy_mock_from():
    from mock import Mock
    m = Mock()
    assert m
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_legacy_mock_from")

        result = analyzer.analyze(test_info)

        mock_issues = [i for i in result.issues if i.rule == "patterns.legacy_mock"]
        assert len(mock_issues) == 1

    def test_clean_test_passes(self) -> None:
        source = """
def test_clean():
    from unittest.mock import Mock
    m = Mock()
    result = m.method()
    assert result is not None
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_clean")

        result = analyzer.analyze(test_info)

        # Should have no critical pattern issues
        critical_rules = [
            "patterns.bare_except",
            "patterns.sleep_in_test",
            "patterns.legacy_mock",
        ]
        critical_issues = [i for i in result.issues if i.rule in critical_rules]
        assert len(critical_issues) == 0

    def test_stores_metadata(self) -> None:
        source = """
def test_metadata():
    print("debug")
    assert True
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_metadata")

        result = analyzer.analyze(test_info)

        assert "pattern_issues" in result.metadata
        assert result.metadata["pattern_issues"] >= 1
