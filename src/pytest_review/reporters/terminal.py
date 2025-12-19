"""Terminal reporter for pytest-review."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _pytest.terminal import TerminalReporter as PytestTerminalReporter

    from pytest_review.analyzers.base import AnalyzerResult, Issue


class TerminalReporter:
    """Formats and outputs review results to the terminal."""

    SEVERITY_SYMBOLS = {
        "info": "i",
        "warning": "!",
        "error": "X",
    }

    SEVERITY_COLORS = {
        "info": "cyan",
        "warning": "yellow",
        "error": "red",
    }

    def __init__(self, terminal: PytestTerminalReporter) -> None:
        self._terminal = terminal
        self._tw = terminal._tw

    def write_header(self) -> None:
        """Write the review section header."""
        self._tw.sep("=", "pytest-review: Test Quality Report", bold=True)

    def write_issue(self, issue: Issue) -> None:
        """Write a single issue to the terminal."""
        severity = issue.severity.value
        symbol = self.SEVERITY_SYMBOLS.get(severity, "?")
        color = self.SEVERITY_COLORS.get(severity, "white")

        # Build location string
        location_parts = []
        if issue.file_path:
            location_parts.append(str(issue.file_path))
            if issue.line:
                location_parts.append(str(issue.line))
        location = ":".join(location_parts)

        # Format: [X] path:line [test_name] message
        self._tw.write(f"  [{symbol}] ", **{color: True})
        if location:
            self._tw.write(f"{location} ")
        if issue.test_name:
            self._tw.write(f"[{issue.test_name}] ", bold=True)
        self._tw.line(issue.message)

        if issue.suggestion:
            self._tw.line(f"      Suggestion: {issue.suggestion}", cyan=True)

    def write_results(self, results: list[AnalyzerResult]) -> None:
        """Write all analyzer results."""
        # Group issues by severity
        all_issues: list[Issue] = []
        for result in results:
            all_issues.extend(result.issues)

        if not all_issues:
            self._tw.line("  No quality issues found.", green=True)
            return

        # Sort by severity (errors first) then by file/line
        all_issues.sort(
            key=lambda i: (
                i.severity,
                str(i.file_path) if i.file_path else "",
                i.line or 0,
            ),
            reverse=True,
        )

        for issue in all_issues:
            self.write_issue(issue)

    def write_summary(self, results: list[AnalyzerResult], total_tests: int) -> None:
        """Write summary statistics."""
        error_count = sum(1 for r in results for i in r.issues if i.severity.value == "error")
        warning_count = sum(1 for r in results for i in r.issues if i.severity.value == "warning")
        info_count = sum(1 for r in results for i in r.issues if i.severity.value == "info")

        self._tw.sep("-", "Summary")
        self._tw.line(f"  Tests analyzed: {total_tests}")

        if error_count > 0:
            self._tw.line(f"  Errors: {error_count}", red=True, bold=True)
        if warning_count > 0:
            self._tw.line(f"  Warnings: {warning_count}", yellow=True)
        if info_count > 0:
            self._tw.line(f"  Info: {info_count}", cyan=True)

        total_issues = error_count + warning_count + info_count
        if total_issues == 0:
            self._tw.line("  Quality: EXCELLENT", green=True, bold=True)
        elif error_count == 0:
            self._tw.line("  Quality: GOOD (no errors)", green=True)
        else:
            self._tw.line("  Quality: NEEDS IMPROVEMENT", red=True)

    def write_score(self, score: float) -> None:
        """Write the overall quality score."""
        grade = self._score_to_grade(score)

        self._tw.line()
        self._tw.write("  Overall Score: ", bold=True)

        color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
        self._tw.line(f"{score:.1f}/100 ({grade})", **{color: True, "bold": True})

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

    def write_footer(self) -> None:
        """Write the closing separator."""
        self._tw.sep("=")
