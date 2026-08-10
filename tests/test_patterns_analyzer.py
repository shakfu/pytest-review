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

    def test_detects_subprocess_run_without_check(self) -> None:
        source = """
def test_subprocess_no_check():
    import subprocess
    subprocess.run(["ls", "-la"])
    assert True
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_subprocess_no_check")

        result = analyzer.analyze(test_info)

        issues = [i for i in result.issues if i.rule == "patterns.subprocess_no_check"]
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_allows_subprocess_run_with_check(self) -> None:
        source = """
def test_subprocess_with_check():
    import subprocess
    subprocess.run(["ls"], check=True)
    assert True
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_subprocess_with_check")

        result = analyzer.analyze(test_info)

        issues = [i for i in result.issues if i.rule == "patterns.subprocess_no_check"]
        assert len(issues) == 0

    def test_detects_broad_pytest_raises(self) -> None:
        source = """
def test_broad_raises():
    with pytest.raises(Exception):
        do_something()
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_broad_raises")

        result = analyzer.analyze(test_info)

        issues = [i for i in result.issues if i.rule == "patterns.broad_raises"]
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_allows_specific_pytest_raises(self) -> None:
        source = """
def test_specific_raises():
    with pytest.raises(ValueError):
        do_something()
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_specific_raises")

        result = analyzer.analyze(test_info)

        issues = [i for i in result.issues if i.rule == "patterns.broad_raises"]
        assert len(issues) == 0

    def test_detects_mutable_default_list(self) -> None:
        source = """
def test_mutable_default():
    def helper(items=[]):
        items.append(1)
    helper()
    assert True
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_mutable_default")

        result = analyzer.analyze(test_info)

        issues = [i for i in result.issues if i.rule == "patterns.mutable_default"]
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_detects_mutable_default_dict(self) -> None:
        source = """
def test_mutable_dict():
    def helper(config={}):
        pass
    helper()
    assert True
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_mutable_dict")

        result = analyzer.analyze(test_info)

        issues = [i for i in result.issues if i.rule == "patterns.mutable_default"]
        assert len(issues) == 1

    def test_no_mutable_default_with_none(self) -> None:
        source = """
def test_safe_default():
    def helper(items=None):
        items = items or []
    helper()
    assert True
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_safe_default")

        result = analyzer.analyze(test_info)

        issues = [i for i in result.issues if i.rule == "patterns.mutable_default"]
        assert len(issues) == 0

    def test_detects_requests_get(self) -> None:
        source = """
def test_network_call():
    import requests
    response = requests.get("https://example.com")
    assert response.status_code == 200
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_network_call")

        result = analyzer.analyze(test_info)

        issues = [i for i in result.issues if i.rule == "patterns.slow_call"]
        assert len(issues) == 1
        assert "requests.get" in issues[0].message
        assert issues[0].severity == Severity.INFO

    def test_detects_httpx_post(self) -> None:
        source = """
def test_httpx_call():
    import httpx
    response = httpx.post("https://example.com", json={})
    assert response.status_code == 200
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_httpx_call")

        result = analyzer.analyze(test_info)

        issues = [i for i in result.issues if i.rule == "patterns.slow_call"]
        assert len(issues) == 1
        assert "httpx.post" in issues[0].message

    def test_detects_cursor_execute(self) -> None:
        source = """
def test_db_call():
    cursor.execute("SELECT 1")
    assert True
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_db_call")

        result = analyzer.analyze(test_info)

        issues = [i for i in result.issues if i.rule == "patterns.slow_call"]
        assert len(issues) == 1
        assert "cursor.execute" in issues[0].message

    def test_no_slow_call_for_local_method(self) -> None:
        source = """
def test_local_call():
    result = compute()
    assert result == 42
"""
        config = ReviewConfig()
        analyzer = PatternsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_local_call")

        result = analyzer.analyze(test_info)

        issues = [i for i in result.issues if i.rule == "patterns.slow_call"]
        assert len(issues) == 0

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
        pattern_issues = result.metadata["pattern_issues"]
        assert isinstance(pattern_issues, int)
        assert pattern_issues >= 1
