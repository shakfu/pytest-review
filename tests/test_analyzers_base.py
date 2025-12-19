"""Tests for base analyzer classes."""

from __future__ import annotations

import ast
from pathlib import Path

from pytest_review.analyzers.base import (
    AnalyzerResult,
    Issue,
    Severity,
    StaticAnalyzer,
    TestItemInfo,
)
from pytest_review.config import ReviewConfig


class TestSeverity:
    def test_values(self) -> None:
        assert Severity.INFO.value == "info"
        assert Severity.WARNING.value == "warning"
        assert Severity.ERROR.value == "error"

    def test_ordering(self) -> None:
        assert Severity.INFO < Severity.WARNING
        assert Severity.WARNING < Severity.ERROR
        assert not Severity.ERROR < Severity.INFO


class TestIssue:
    def test_basic_issue(self) -> None:
        issue = Issue(
            rule="test.rule",
            message="Test message",
            severity=Severity.WARNING,
        )
        assert issue.rule == "test.rule"
        assert issue.message == "Test message"
        assert issue.severity == Severity.WARNING
        assert issue.file_path is None
        assert issue.line is None
        assert issue.test_name is None

    def test_full_issue(self) -> None:
        issue = Issue(
            rule="test.rule",
            message="Test message",
            severity=Severity.ERROR,
            file_path=Path("test_file.py"),
            line=42,
            test_name="test_example",
            suggestion="Fix this",
        )
        assert issue.file_path == Path("test_file.py")
        assert issue.line == 42
        assert issue.test_name == "test_example"
        assert issue.suggestion == "Fix this"

    def test_str_representation(self) -> None:
        issue = Issue(
            rule="test.rule",
            message="Something wrong",
            severity=Severity.ERROR,
            file_path=Path("tests/test_foo.py"),
            line=10,
            test_name="test_bar",
        )
        result = str(issue)
        assert "tests/test_foo.py:10" in result
        assert "[test_bar]" in result
        assert "Something wrong" in result

    def test_str_without_location(self) -> None:
        issue = Issue(
            rule="test.rule",
            message="Something wrong",
            severity=Severity.ERROR,
        )
        result = str(issue)
        assert "Something wrong" in result


class TestAnalyzerResult:
    def test_default_values(self) -> None:
        result = AnalyzerResult(analyzer_name="test")
        assert result.analyzer_name == "test"
        assert result.issues == []
        assert result.score == 100.0
        assert result.metadata == {}

    def test_has_errors(self) -> None:
        result = AnalyzerResult(analyzer_name="test")
        assert result.has_errors is False

        result.add_issue(Issue("r1", "msg", Severity.WARNING))
        assert result.has_errors is False

        result.add_issue(Issue("r2", "msg", Severity.ERROR))
        assert result.has_errors is True

    def test_has_warnings(self) -> None:
        result = AnalyzerResult(analyzer_name="test")
        assert result.has_warnings is False

        result.add_issue(Issue("r1", "msg", Severity.INFO))
        assert result.has_warnings is False

        result.add_issue(Issue("r2", "msg", Severity.WARNING))
        assert result.has_warnings is True

    def test_issue_count(self) -> None:
        result = AnalyzerResult(analyzer_name="test")
        assert result.issue_count == 0

        result.add_issue(Issue("r1", "msg1", Severity.INFO))
        result.add_issue(Issue("r2", "msg2", Severity.WARNING))
        assert result.issue_count == 2


class TestTestItemInfo:
    def test_basic_test_info(self) -> None:
        source = "def test_example(): pass"
        tree = ast.parse(source)
        func_node = tree.body[0]
        assert isinstance(func_node, ast.FunctionDef)

        info = TestItemInfo(
            name="test_example",
            file_path=Path("test_file.py"),
            line=1,
            node=func_node,
            source=source,
        )

        assert info.name == "test_example"
        assert info.full_name == "test_example"
        assert info.class_name is None

    def test_test_info_with_class(self) -> None:
        source = "def test_example(): pass"
        tree = ast.parse(source)
        func_node = tree.body[0]
        assert isinstance(func_node, ast.FunctionDef)

        info = TestItemInfo(
            name="test_example",
            file_path=Path("test_file.py"),
            line=1,
            node=func_node,
            source=source,
            class_name="TestClass",
        )

        assert info.full_name == "TestClass::test_example"


class DummyAnalyzer(StaticAnalyzer):
    """A simple analyzer for testing."""

    name = "dummy"
    description = "Dummy analyzer for testing"

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        if "bad" in test.name:
            result.add_issue(
                Issue(
                    rule="dummy.bad_name",
                    message="Test name contains 'bad'",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=test.name,
                )
            )


class TestStaticAnalyzer:
    def test_analyze_returns_result(self) -> None:
        config = ReviewConfig()
        analyzer = DummyAnalyzer(config)

        source = "def test_good(): pass"
        tree = ast.parse(source)
        func_node = tree.body[0]
        assert isinstance(func_node, ast.FunctionDef)

        test_info = TestItemInfo(
            name="test_good",
            file_path=Path("test.py"),
            line=1,
            node=func_node,
            source=source,
        )

        result = analyzer.analyze(test_info)
        assert result.analyzer_name == "dummy"
        assert result.issue_count == 0

    def test_analyze_detects_issues(self) -> None:
        config = ReviewConfig()
        analyzer = DummyAnalyzer(config)

        source = "def test_bad_example(): pass"
        tree = ast.parse(source)
        func_node = tree.body[0]
        assert isinstance(func_node, ast.FunctionDef)

        test_info = TestItemInfo(
            name="test_bad_example",
            file_path=Path("test.py"),
            line=1,
            node=func_node,
            source=source,
        )

        result = analyzer.analyze(test_info)
        assert result.issue_count == 1
        assert result.issues[0].rule == "dummy.bad_name"

    def test_analyzer_enabled_by_default(self) -> None:
        config = ReviewConfig()
        analyzer = DummyAnalyzer(config)
        assert analyzer.enabled is True

    def test_analyzer_respects_config(self) -> None:
        config = ReviewConfig.from_dict({"analyzers": {"dummy": {"enabled": False}}})
        analyzer = DummyAnalyzer(config)
        assert analyzer.enabled is False

    def test_analyze_all(self) -> None:
        config = ReviewConfig()
        analyzer = DummyAnalyzer(config)

        tests = []
        for name in ["test_good", "test_bad", "test_also_bad"]:
            source = f"def {name}(): pass"
            tree = ast.parse(source)
            func_node = tree.body[0]
            assert isinstance(func_node, ast.FunctionDef)
            tests.append(
                TestItemInfo(
                    name=name,
                    file_path=Path("test.py"),
                    line=1,
                    node=func_node,
                    source=source,
                )
            )

        results = analyzer.analyze_all(tests)
        assert len(results) == 3
        total_issues = sum(r.issue_count for r in results)
        assert total_issues == 2  # two tests with "bad" in name
