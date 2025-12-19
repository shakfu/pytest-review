"""JSON reporter for pytest-review."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pytest_review.analyzers.base import AnalyzerResult, Issue, Severity


@dataclass
class ReviewReport:
    """Complete review report data structure."""

    version: str = "1.0"
    generated_at: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    score: float = 100.0
    grade: str = "A"
    tests_analyzed: int = 0
    issues: list[dict[str, Any]] = field(default_factory=list)
    by_analyzer: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    by_rule: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)


class JsonReporter:
    """Generates JSON reports from analysis results."""

    def __init__(self) -> None:
        self._report: ReviewReport | None = None

    def generate_report(
        self,
        results: list[AnalyzerResult],
        total_tests: int,
        score: float,
    ) -> ReviewReport:
        """Generate a complete report from analysis results."""
        report = ReviewReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            tests_analyzed=total_tests,
            score=score,
            grade=self._score_to_grade(score),
        )

        # Collect all issues
        all_issues: list[Issue] = []
        for result in results:
            all_issues.extend(result.issues)

        # Convert issues to dicts
        report.issues = [self._issue_to_dict(issue) for issue in all_issues]

        # Count by severity
        report.by_severity = {
            "error": sum(1 for i in all_issues if i.severity == Severity.ERROR),
            "warning": sum(1 for i in all_issues if i.severity == Severity.WARNING),
            "info": sum(1 for i in all_issues if i.severity == Severity.INFO),
        }

        # Count by rule
        rule_counts: dict[str, int] = {}
        for issue in all_issues:
            rule_counts[issue.rule] = rule_counts.get(issue.rule, 0) + 1
        report.by_rule = rule_counts

        # Group by analyzer
        analyzer_data: dict[str, dict[str, Any]] = {}
        for result in results:
            name = result.analyzer_name
            if name not in analyzer_data:
                analyzer_data[name] = {
                    "issue_count": 0,
                    "issues": [],
                    "metadata": {},
                }
            analyzer_data[name]["issue_count"] += result.issue_count
            analyzer_data[name]["issues"].extend(
                [self._issue_to_dict(i) for i in result.issues]
            )
            # Merge metadata
            for key, value in result.metadata.items():
                if key not in analyzer_data[name]["metadata"]:
                    analyzer_data[name]["metadata"][key] = value
        report.by_analyzer = analyzer_data

        # Summary
        report.summary = {
            "total_issues": len(all_issues),
            "errors": report.by_severity["error"],
            "warnings": report.by_severity["warning"],
            "info": report.by_severity["info"],
            "tests_analyzed": total_tests,
            "score": score,
            "grade": report.grade,
            "passed": report.by_severity["error"] == 0,
        }

        self._report = report
        return report

    def _issue_to_dict(self, issue: Issue) -> dict[str, Any]:
        """Convert an Issue to a dictionary."""
        return {
            "rule": issue.rule,
            "message": issue.message,
            "severity": issue.severity.value,
            "file_path": str(issue.file_path) if issue.file_path else None,
            "line": issue.line,
            "test_name": issue.test_name,
            "suggestion": issue.suggestion,
        }

    @staticmethod
    def _score_to_grade(score: float) -> str:
        """Convert numeric score to letter grade."""
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"

    def write_to_file(self, path: Path | str) -> None:
        """Write the report to a file."""
        if self._report is None:
            raise ValueError("No report generated. Call generate_report first.")

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._report.to_json())

    def get_json(self) -> str:
        """Get the report as a JSON string."""
        if self._report is None:
            raise ValueError("No report generated. Call generate_report first.")
        return self._report.to_json()
