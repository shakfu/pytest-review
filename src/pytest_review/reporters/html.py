"""HTML reporter for pytest-review."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pytest_review.analyzers.base import AnalyzerResult, Issue, Severity

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>pytest-review Report</title>
    <style>
        :root {{
            --color-error: #dc3545;
            --color-warning: #ffc107;
            --color-info: #17a2b8;
            --color-success: #28a745;
            --color-bg: #f8f9fa;
            --color-card: #ffffff;
            --color-text: #212529;
            --color-muted: #6c757d;
            --color-border: #dee2e6;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background-color: var(--color-bg);
            color: var(--color-text);
            line-height: 1.6;
            padding: 2rem;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        header {{
            text-align: center;
            margin-bottom: 2rem;
        }}

        h1 {{
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }}

        .timestamp {{
            color: var(--color-muted);
            font-size: 0.875rem;
        }}

        .score-card {{
            background: var(--color-card);
            border-radius: 1rem;
            padding: 2rem;
            text-align: center;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .score-value {{
            font-size: 4rem;
            font-weight: bold;
            line-height: 1;
        }}

        .score-grade {{
            font-size: 1.5rem;
            color: var(--color-muted);
            margin-top: 0.5rem;
        }}

        .score-a {{ color: var(--color-success); }}
        .score-b {{ color: #5cb85c; }}
        .score-c {{ color: var(--color-warning); }}
        .score-d {{ color: #fd7e14; }}
        .score-f {{ color: var(--color-error); }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}

        .stat-card {{
            background: var(--color-card);
            border-radius: 0.5rem;
            padding: 1rem;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .stat-value {{
            font-size: 2rem;
            font-weight: bold;
        }}

        .stat-label {{
            color: var(--color-muted);
            font-size: 0.875rem;
            text-transform: uppercase;
        }}

        .stat-error .stat-value {{ color: var(--color-error); }}
        .stat-warning .stat-value {{ color: var(--color-warning); }}
        .stat-info .stat-value {{ color: var(--color-info); }}

        .section {{
            background: var(--color-card);
            border-radius: 0.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }}

        .section-header {{
            background: var(--color-bg);
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--color-border);
            font-weight: 600;
        }}

        .issue-list {{
            list-style: none;
        }}

        .issue-item {{
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--color-border);
            display: flex;
            align-items: flex-start;
            gap: 1rem;
        }}

        .issue-item:last-child {{
            border-bottom: none;
        }}

        .issue-severity {{
            width: 24px;
            height: 24px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 0.75rem;
            flex-shrink: 0;
        }}

        .severity-error {{
            background: var(--color-error);
            color: white;
        }}

        .severity-warning {{
            background: var(--color-warning);
            color: #212529;
        }}

        .severity-info {{
            background: var(--color-info);
            color: white;
        }}

        .issue-content {{
            flex: 1;
        }}

        .issue-message {{
            font-weight: 500;
            margin-bottom: 0.25rem;
        }}

        .issue-location {{
            font-size: 0.875rem;
            color: var(--color-muted);
            font-family: monospace;
        }}

        .issue-suggestion {{
            font-size: 0.875rem;
            color: var(--color-info);
            margin-top: 0.5rem;
        }}

        .issue-rule {{
            font-size: 0.75rem;
            color: var(--color-muted);
            font-family: monospace;
        }}

        .empty-state {{
            padding: 3rem;
            text-align: center;
            color: var(--color-muted);
        }}

        .empty-state-icon {{
            font-size: 3rem;
            margin-bottom: 1rem;
        }}

        .rule-breakdown {{
            padding: 1rem 1.5rem;
        }}

        .rule-item {{
            display: flex;
            justify-content: space-between;
            padding: 0.5rem 0;
            border-bottom: 1px solid var(--color-border);
        }}

        .rule-item:last-child {{
            border-bottom: none;
        }}

        .rule-name {{
            font-family: monospace;
            font-size: 0.875rem;
        }}

        .rule-count {{
            font-weight: bold;
        }}

        footer {{
            text-align: center;
            color: var(--color-muted);
            font-size: 0.875rem;
            margin-top: 2rem;
        }}

        @media (max-width: 768px) {{
            body {{
                padding: 1rem;
            }}

            .score-value {{
                font-size: 3rem;
            }}

            .stats-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>pytest-review Report</h1>
            <p class="timestamp">Generated: {timestamp}</p>
        </header>

        <div class="score-card">
            <div class="score-value score-{grade_lower}">{score:.1f}</div>
            <div class="score-grade">Grade: {grade}</div>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{tests_analyzed}</div>
                <div class="stat-label">Tests Analyzed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{total_issues}</div>
                <div class="stat-label">Total Issues</div>
            </div>
            <div class="stat-card stat-error">
                <div class="stat-value">{error_count}</div>
                <div class="stat-label">Errors</div>
            </div>
            <div class="stat-card stat-warning">
                <div class="stat-value">{warning_count}</div>
                <div class="stat-label">Warnings</div>
            </div>
            <div class="stat-card stat-info">
                <div class="stat-value">{info_count}</div>
                <div class="stat-label">Info</div>
            </div>
        </div>

        <div class="section">
            <div class="section-header">Issues</div>
            {issues_html}
        </div>

        <div class="section">
            <div class="section-header">Issues by Rule</div>
            <div class="rule-breakdown">
                {rules_html}
            </div>
        </div>

        <footer>
            Generated by pytest-review
        </footer>
    </div>
</body>
</html>
"""


class HtmlReporter:
    """Generates HTML reports from analysis results."""

    SEVERITY_SYMBOLS = {
        Severity.ERROR: "X",
        Severity.WARNING: "!",
        Severity.INFO: "i",
    }

    def __init__(self) -> None:
        self._html: str = ""

    def generate_report(
        self,
        results: list[AnalyzerResult],
        total_tests: int,
        score: float,
    ) -> str:
        """Generate an HTML report from analysis results."""
        # Collect all issues
        all_issues: list[Issue] = []
        for result in results:
            all_issues.extend(result.issues)

        # Sort by severity (errors first)
        all_issues.sort(key=lambda i: i.severity, reverse=True)

        # Count by severity
        error_count = sum(1 for i in all_issues if i.severity == Severity.ERROR)
        warning_count = sum(1 for i in all_issues if i.severity == Severity.WARNING)
        info_count = sum(1 for i in all_issues if i.severity == Severity.INFO)

        # Count by rule
        rule_counts: dict[str, int] = {}
        for issue in all_issues:
            rule_counts[issue.rule] = rule_counts.get(issue.rule, 0) + 1

        # Generate issues HTML
        if all_issues:
            issues_html = '<ul class="issue-list">'
            for issue in all_issues:
                issues_html += self._render_issue(issue)
            issues_html += "</ul>"
        else:
            issues_html = """
            <div class="empty-state">
                <div class="empty-state-icon">&#10004;</div>
                <p>No quality issues found. Great job!</p>
            </div>
            """

        # Generate rules HTML
        if rule_counts:
            rules_html = ""
            for rule, count in sorted(rule_counts.items(), key=lambda x: -x[1]):
                rules_html += f"""
                <div class="rule-item">
                    <span class="rule-name">{self._escape(rule)}</span>
                    <span class="rule-count">{count}</span>
                </div>
                """
        else:
            rules_html = '<p style="color: var(--color-muted);">No issues to categorize.</p>'

        grade = self._score_to_grade(score)

        self._html = HTML_TEMPLATE.format(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            score=score,
            grade=grade,
            grade_lower=grade.lower(),
            tests_analyzed=total_tests,
            total_issues=len(all_issues),
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            issues_html=issues_html,
            rules_html=rules_html,
        )

        return self._html

    def _render_issue(self, issue: Issue) -> str:
        """Render a single issue as HTML."""
        severity_class = f"severity-{issue.severity.value}"
        symbol = self.SEVERITY_SYMBOLS.get(issue.severity, "?")

        location = ""
        if issue.file_path:
            location = str(issue.file_path)
            if issue.line:
                location += f":{issue.line}"

        suggestion_html = ""
        if issue.suggestion:
            suggestion_html = f'<div class="issue-suggestion">{self._escape(issue.suggestion)}</div>'

        test_name = f" [{issue.test_name}]" if issue.test_name else ""

        return f"""
        <li class="issue-item">
            <div class="issue-severity {severity_class}">{symbol}</div>
            <div class="issue-content">
                <div class="issue-message">{self._escape(issue.message)}</div>
                <div class="issue-location">{self._escape(location)}{self._escape(test_name)}</div>
                <div class="issue-rule">{self._escape(issue.rule)}</div>
                {suggestion_html}
            </div>
        </li>
        """

    @staticmethod
    def _escape(text: str) -> str:
        """Escape HTML special characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

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
        if not self._html:
            raise ValueError("No report generated. Call generate_report first.")

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._html)

    def get_html(self) -> str:
        """Get the report as an HTML string."""
        if not self._html:
            raise ValueError("No report generated. Call generate_report first.")
        return self._html
