"""Tests for the isolation analyzer."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pytest_review.analyzers.base import Severity, TestItemInfo
from pytest_review.analyzers.isolation import IsolationStaticAnalyzer
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


class TestIsolationStaticAnalyzer:
    def test_detects_global_keyword(self) -> None:
        source = """
def test_modifies_global():
    global counter
    counter += 1
    assert counter > 0
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_modifies_global")

        result = analyzer.analyze(test_info)

        global_issues = [i for i in result.issues if i.rule == "isolation.global_modification"]
        assert len(global_issues) == 1
        assert "global counter" in global_issues[0].message
        assert global_issues[0].severity == Severity.WARNING

    def test_detects_class_attribute_modification(self) -> None:
        source = """
def test_modifies_class_attr():
    cls.shared_state = "modified"
    assert cls.shared_state == "modified"
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_modifies_class_attr")

        result = analyzer.analyze(test_info)

        class_issues = [i for i in result.issues if i.rule == "isolation.class_attr_modification"]
        assert len(class_issues) == 1
        assert "cls.shared_state" in class_issues[0].message

    def test_detects_uppercase_class_modification(self) -> None:
        source = """
def test_modifies_config():
    Config.DEBUG = True
    assert Config.DEBUG
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_modifies_config")

        result = analyzer.analyze(test_info)

        class_issues = [i for i in result.issues if i.rule == "isolation.class_attr_modification"]
        assert len(class_issues) == 1
        assert "Config.DEBUG" in class_issues[0].message

    def test_clean_test_passes(self) -> None:
        source = """
def test_clean_isolation():
    local_var = "value"
    result = process(local_var)
    assert result is not None
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_clean_isolation")

        result = analyzer.analyze(test_info)

        # Should have no isolation issues
        isolation_issues = [i for i in result.issues if i.rule.startswith("isolation.")]
        assert len(isolation_issues) == 0

    def test_stores_metadata(self) -> None:
        source = """
def test_with_globals():
    global a, b
    a = 1
    b = 2
    assert a + b == 3
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_with_globals")

        result = analyzer.analyze(test_info)

        assert result.metadata["global_modifications"] == 2

    def test_instance_attribute_is_allowed(self) -> None:
        source = """
def test_instance_attr():
    self.value = 123
    assert self.value == 123
"""
        config = ReviewConfig()
        analyzer = IsolationStaticAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_instance_attr")

        result = analyzer.analyze(test_info)

        # self.attr modifications are fine (instance, not class)
        # The analyzer doesn't flag 'self' since it's instance-level
        class_issues = [i for i in result.issues if i.rule == "isolation.class_attr_modification"]
        # 'self' starts with lowercase so won't be flagged as class modification
        assert len(class_issues) == 0


class TestIsolationAnalyzerIntegration:
    """Integration tests using pytester."""

    def test_detects_global_in_real_test(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            counter = 0

            def test_increments_global_counter_problematically():
                global counter
                counter += 1
                assert counter == 1
        """)
        result = pytester.runpytest("--review", "--review-only=isolation")
        result.assert_outcomes(passed=1)
        assert "global" in result.stdout.str().lower()

    def test_clean_test_no_issues(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_properly_isolated_with_local_state():
                local_counter = 0
                local_counter += 1
                assert local_counter == 1
        """)
        result = pytester.runpytest("--review", "--review-only=isolation")
        result.assert_outcomes(passed=1)
        assert "No quality issues found" in result.stdout.str()
