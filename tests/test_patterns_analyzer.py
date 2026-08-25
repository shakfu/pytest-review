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
        # Network I/O is matched against a known module/method list, so it is
        # reported at the same tier as time.sleep(). Database detection matches
        # on variable names instead and stays at INFO -- see the test below.
        assert issues[0].severity == Severity.WARNING

    def test_database_call_stays_info_because_it_matches_on_names(self) -> None:
        """DB detection is a guess; network detection is not.

        ``cursor.execute()`` matches any variable happening to be named cursor,
        session, conn or db, so it must not carry the same weight as a call to a
        known network API.
        """
        source = """
def test_db_call():
    cursor.execute("SELECT 1")
    assert True
"""
        analyzer = PatternsAnalyzer(ReviewConfig())
        result = analyzer.analyze(make_test_info(source.strip(), "test_db_call"))

        issues = [i for i in result.issues if i.rule == "patterns.slow_call"]
        assert len(issues) == 1
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
    import time
    time.sleep(1)
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
