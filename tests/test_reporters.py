"""Tests for the reporters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pytest_review.analyzers.base import AnalyzerResult, Issue, Severity
from pytest_review.reporters.html import HtmlReporter
from pytest_review.reporters.json import JsonReporter


class TestJsonReporter:
    def test_generates_valid_json(self) -> None:
        reporter = JsonReporter()
        results = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[
                    Issue(
                        rule="assertions.missing",
                        message="Test has no assertions",
                        severity=Severity.ERROR,
                        test_name="test_empty",
                    )
                ],
            )
        ]

        report = reporter.generate_report(results, total_tests=5, score=80.0)
        json_str = report.to_json()

        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["score"] == 80.0
        assert parsed["grade"] == "B"
        assert parsed["tests_analyzed"] == 5

    def test_counts_issues_by_severity(self) -> None:
        reporter = JsonReporter()
        results = [
            AnalyzerResult(
                analyzer_name="test",
                issues=[
                    Issue("r1", "msg1", Severity.ERROR),
                    Issue("r2", "msg2", Severity.ERROR),
                    Issue("r3", "msg3", Severity.WARNING),
                    Issue("r4", "msg4", Severity.INFO),
                ],
            )
        ]

        report = reporter.generate_report(results, total_tests=1, score=50.0)

        assert report.by_severity["error"] == 2
        assert report.by_severity["warning"] == 1
        assert report.by_severity["info"] == 1

    def test_counts_issues_by_rule(self) -> None:
        reporter = JsonReporter()
        results = [
            AnalyzerResult(
                analyzer_name="test",
                issues=[
                    Issue("rule.a", "msg1", Severity.ERROR),
                    Issue("rule.a", "msg2", Severity.ERROR),
                    Issue("rule.b", "msg3", Severity.WARNING),
                ],
            )
        ]

        report = reporter.generate_report(results, total_tests=1, score=50.0)

        assert report.by_rule["rule.a"] == 2
        assert report.by_rule["rule.b"] == 1

    def test_groups_by_analyzer(self) -> None:
        reporter = JsonReporter()
        results = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[Issue("assertions.missing", "msg", Severity.ERROR)],
            ),
            AnalyzerResult(
                analyzer_name="naming",
                issues=[Issue("naming.short", "msg", Severity.WARNING)],
            ),
        ]

        report = reporter.generate_report(results, total_tests=2, score=70.0)

        assert "assertions" in report.by_analyzer
        assert "naming" in report.by_analyzer
        assert report.by_analyzer["assertions"]["issue_count"] == 1
        assert report.by_analyzer["naming"]["issue_count"] == 1

    def test_writes_to_file(self, tmp_path: Path) -> None:
        reporter = JsonReporter()
        results: list[AnalyzerResult] = []

        reporter.generate_report(results, total_tests=0, score=100.0)

        output_file = tmp_path / "report.json"
        reporter.write_to_file(output_file)

        assert output_file.exists()
        content = json.loads(output_file.read_text())
        assert content["score"] == 100.0

    def test_summary_includes_passed_status(self) -> None:
        reporter = JsonReporter()

        # No errors = passed
        results: list[AnalyzerResult] = []
        report = reporter.generate_report(results, total_tests=5, score=100.0)
        assert report.summary["passed"] is True

        # With errors = not passed
        results = [
            AnalyzerResult(
                analyzer_name="test",
                issues=[Issue("rule", "msg", Severity.ERROR)],
            )
        ]
        report = reporter.generate_report(results, total_tests=5, score=50.0)
        assert report.summary["passed"] is False


class TestHtmlReporter:
    def test_generates_valid_html(self) -> None:
        reporter = HtmlReporter()
        results: list[AnalyzerResult] = []

        html = reporter.generate_report(results, total_tests=5, score=100.0)

        assert "<!DOCTYPE html>" in html
        assert "pytest-review" in html
        assert "100.0" in html  # Score

    def test_includes_issues_in_html(self) -> None:
        reporter = HtmlReporter()
        results = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[
                    Issue(
                        rule="assertions.missing",
                        message="Test has no assertions",
                        severity=Severity.ERROR,
                        test_name="test_empty",
                        suggestion="Add an assertion",
                    )
                ],
            )
        ]

        html = reporter.generate_report(results, total_tests=1, score=50.0)

        assert "Test has no assertions" in html
        assert "assertions.missing" in html
        assert "Add an assertion" in html

    def test_escapes_html_in_messages(self) -> None:
        reporter = HtmlReporter()
        results = [
            AnalyzerResult(
                analyzer_name="test",
                issues=[
                    Issue(
                        rule="test.rule",
                        message="Contains <script>alert('xss')</script>",
                        severity=Severity.WARNING,
                    )
                ],
            )
        ]

        html = reporter.generate_report(results, total_tests=1, score=90.0)

        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_shows_empty_state_when_no_issues(self) -> None:
        reporter = HtmlReporter()
        results: list[AnalyzerResult] = []

        html = reporter.generate_report(results, total_tests=5, score=100.0)

        assert "No quality issues found" in html

    def test_writes_to_file(self, tmp_path: Path) -> None:
        reporter = HtmlReporter()
        results: list[AnalyzerResult] = []

        reporter.generate_report(results, total_tests=0, score=100.0)

        output_file = tmp_path / "report.html"
        reporter.write_to_file(output_file)

        assert output_file.exists()
        content = output_file.read_text()
        assert "<!DOCTYPE html>" in content

    def test_grade_colors(self) -> None:
        reporter = HtmlReporter()

        # Test different grades
        for score, grade in [(95, "a"), (85, "b"), (75, "c"), (65, "d"), (50, "f")]:
            html = reporter.generate_report([], total_tests=1, score=score)
            assert f"score-{grade}" in html


class TestReporterIntegration:
    """Integration tests using pytester."""

    def test_json_output_to_file(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_sample_for_json_report_generation():
                result = 1 + 1
                assert result == 2
        """)

        output_file = pytester.path / "report.json"
        result = pytester.runpytest(
            "--review",
            "--review-format=json",
            f"--review-output={output_file}",
        )
        result.assert_outcomes(passed=1)
        assert "JSON report written to" in result.stdout.str()
        assert output_file.exists()

        content = json.loads(output_file.read_text())
        assert "score" in content
        assert "grade" in content

    def test_html_output_to_file(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_sample_for_html_report_generation():
                result = 1 + 1
                assert result == 2
        """)

        output_file = pytester.path / "report.html"
        result = pytester.runpytest(
            "--review",
            "--review-format=html",
            f"--review-output={output_file}",
        )
        result.assert_outcomes(passed=1)
        assert "HTML report written to" in result.stdout.str()
        assert output_file.exists()

        content = output_file.read_text()
        assert "<!DOCTYPE html>" in content
