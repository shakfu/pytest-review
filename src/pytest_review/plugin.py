"""Pytest plugin entry point for pytest-review."""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pytest_review.analyzers import (
    AssertionsAnalyzer,
    ComplexityAnalyzer,
    NamingAnalyzer,
    PatternsAnalyzer,
    SmellsAnalyzer,
)
from pytest_review.analyzers.base import (
    AnalyzerResult,
    DynamicAnalyzer,
    StaticAnalyzer,
    TestItemInfo,
)
from pytest_review.analyzers.isolation import IsolationStaticAnalyzer
from pytest_review.analyzers.performance import PerformanceAnalyzer
from pytest_review.config import ReviewConfig
from pytest_review.reporters.html import HtmlReporter
from pytest_review.reporters.json import JsonReporter
from pytest_review.reporters.terminal import TerminalReporter
from pytest_review.scoring import ScoringEngine

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.config.argparsing import Parser
    from _pytest.python import Function
    from _pytest.terminal import TerminalReporter as PytestTerminalReporter


class ReviewPlugin:
    """Main plugin class that coordinates analyzers and reporting."""

    def __init__(self, config: Config) -> None:
        self.pytest_config = config
        self.review_config = ReviewConfig.from_pyproject()
        self._static_analyzers: list[StaticAnalyzer] = []
        self._dynamic_analyzers: list[DynamicAnalyzer] = []
        self._results: list[AnalyzerResult] = []
        self._test_infos: list[TestItemInfo] = []
        self._enabled = self._should_enable(config)
        self._test_start_times: dict[str, float] = {}
        # For backwards compatibility
        self._analyzers = self._static_analyzers

    def _should_enable(self, config: Config) -> bool:
        """Determine if the plugin should run."""
        return bool(config.getoption("review", default=False))

    def register_analyzer(self, analyzer: StaticAnalyzer | DynamicAnalyzer) -> None:
        """Register an analyzer with the plugin."""
        if not analyzer.enabled:
            return

        if isinstance(analyzer, DynamicAnalyzer):
            self._dynamic_analyzers.append(analyzer)
        else:
            self._static_analyzers.append(analyzer)

    def register_default_analyzers(self) -> None:
        """Register all built-in analyzers."""
        # Get the --review-only filter if specified
        only = self.pytest_config.getoption("review_only", default=None)
        allowed: set[str] | None = None
        if only:
            allowed = {name.strip() for name in only.split(",")}

        # Static analyzers
        static_analyzers: list[StaticAnalyzer] = [
            AssertionsAnalyzer(self.review_config),
            NamingAnalyzer(self.review_config),
            ComplexityAnalyzer(self.review_config),
            PatternsAnalyzer(self.review_config),
            IsolationStaticAnalyzer(self.review_config),
            SmellsAnalyzer(self.review_config),
        ]

        # Dynamic analyzers
        dynamic_analyzers: list[DynamicAnalyzer] = [
            PerformanceAnalyzer(self.review_config),
        ]

        for static_analyzer in static_analyzers:
            if allowed is not None and static_analyzer.name not in allowed:
                continue
            self.register_analyzer(static_analyzer)

        for dynamic_analyzer in dynamic_analyzers:
            if allowed is not None and dynamic_analyzer.name not in allowed:
                continue
            self.register_analyzer(dynamic_analyzer)

    def collect_test_info(self, item: Function) -> TestItemInfo | None:
        """Extract test information from a pytest item."""
        try:
            file_path = Path(item.fspath) if item.fspath else None
            if file_path is None:
                return None

            source = file_path.read_text()
            tree = ast.parse(source)

            # Find the test function in the AST
            test_name = item.name
            class_name = item.cls.__name__ if item.cls else None

            for node in ast.walk(tree):
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == test_name
                ):
                    # Extract just this function's source
                    func_source = ast.get_source_segment(source, node) or ""
                    return TestItemInfo(
                        name=test_name,
                        file_path=file_path,
                        line=node.lineno,
                        node=node,
                        source=func_source,
                        class_name=class_name,
                    )
        except (OSError, SyntaxError):
            pass
        return None

    def run_static_analysis(self) -> None:
        """Run all registered static analyzers on collected tests."""
        for analyzer in self._static_analyzers:
            for test_info in self._test_infos:
                result = analyzer.analyze(test_info)
                if result.issues:
                    self._results.append(result)

    def run_analysis(self) -> None:
        """Run all registered analyzers on collected tests."""
        # Run static analyzers
        self.run_static_analysis()

        # Collect results from dynamic analyzers
        for analyzer in self._dynamic_analyzers:
            for result in analyzer.get_results():
                if result.issues:
                    self._results.append(result)

    def on_test_start(self, node_id: str, test_name: str) -> None:
        """Called when a test starts executing."""
        self._test_start_times[node_id] = time.perf_counter()
        for analyzer in self._dynamic_analyzers:
            analyzer.on_test_start(test_name)

    def on_test_end(self, node_id: str, test_name: str, passed: bool) -> None:
        """Called when a test finishes executing."""
        start_time = self._test_start_times.pop(node_id, time.perf_counter())
        duration = time.perf_counter() - start_time
        for analyzer in self._dynamic_analyzers:
            analyzer.on_test_end(test_name, passed, duration)

    def get_results(self) -> list[AnalyzerResult]:
        """Get all analysis results."""
        return self._results

    def has_errors(self) -> bool:
        """Check if any analyzer found errors."""
        return any(r.has_errors for r in self._results)

    def calculate_score(self) -> float:
        """Calculate overall quality score."""
        if not self._test_infos:
            return 100.0

        scoring_engine = ScoringEngine()
        return scoring_engine.get_simple_score(self._results, len(self._test_infos))

    def get_score_breakdown(self) -> dict[str, object]:
        """Get detailed score breakdown."""
        scoring_engine = ScoringEngine()
        breakdown = scoring_engine.calculate_score(self._results, len(self._test_infos))
        return breakdown.to_dict()


# Global plugin instance
_plugin: ReviewPlugin | None = None


def pytest_addoption(parser: Parser) -> None:
    """Add pytest-review command line options."""
    group = parser.getgroup("review", "Test quality review options")
    group.addoption(
        "--review",
        action="store_true",
        default=False,
        dest="review",
        help="Enable test quality review",
    )
    group.addoption(
        "--review-strict",
        action="store_true",
        default=False,
        dest="review_strict",
        help="Fail tests if quality issues are found",
    )
    group.addoption(
        "--review-format",
        action="store",
        default="terminal",
        dest="review_format",
        choices=["terminal", "json", "html"],
        help="Output format for review report (default: terminal)",
    )
    group.addoption(
        "--review-output",
        action="store",
        default=None,
        dest="review_output",
        help="Output file for review report (default: stdout)",
    )
    group.addoption(
        "--review-min-score",
        action="store",
        type=int,
        default=0,
        dest="review_min_score",
        help="Minimum quality score required (0-100, default: 0)",
    )
    group.addoption(
        "--review-only",
        action="store",
        default=None,
        dest="review_only",
        help="Comma-separated list of analyzers to run",
    )


def pytest_configure(config: Config) -> None:
    """Configure the plugin."""
    global _plugin

    # Register marker
    config.addinivalue_line("markers", "review_skip: skip this test from quality review")

    # Create plugin instance
    _plugin = ReviewPlugin(config)

    # Register plugin if enabled via CLI
    if config.getoption("review", default=False):
        _plugin.register_default_analyzers()
        config.pluginmanager.register(_plugin, "review_plugin")


def pytest_collection_modifyitems(
    session: pytest.Session, config: Config, items: list[pytest.Item]
) -> None:
    """Collect test information after test collection."""
    global _plugin

    if _plugin is None or not _plugin._enabled:
        return

    for item in items:
        if isinstance(item, pytest.Function):
            # Skip tests marked with review_skip
            if item.get_closest_marker("review_skip"):
                continue

            test_info = _plugin.collect_test_info(item)
            if test_info:
                _plugin._test_infos.append(test_info)


@pytest.hookimpl(hookwrapper=True)  # type: ignore[untyped-decorator]
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> object:
    """Hook into test execution to track timing."""
    global _plugin

    if _plugin is None or not _plugin._enabled:
        yield
        return

    # Notify start
    _plugin.on_test_start(item.nodeid, item.name)

    yield

    # We'll get the result in pytest_runtest_makereport


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> None:
    """Called after each test phase (setup, call, teardown)."""
    global _plugin

    if _plugin is None or not _plugin._enabled:
        return

    # Only process the 'call' phase (actual test execution)
    if call.when == "call":
        passed = call.excinfo is None
        _plugin.on_test_end(item.nodeid, item.name, passed)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Run analysis and report after tests complete."""
    global _plugin

    if _plugin is None or not _plugin._enabled:
        return

    # Run all analyzers
    _plugin.run_analysis()


def pytest_terminal_summary(
    terminalreporter: PytestTerminalReporter, exitstatus: int, config: Config
) -> None:
    """Add review summary to terminal output."""
    global _plugin

    if _plugin is None or not _plugin._enabled:
        return

    results = _plugin.get_results()
    total_tests = len(_plugin._test_infos)
    score = _plugin.calculate_score()

    # Get output format and file
    output_format = config.getoption("review_format", default="terminal")
    output_file = config.getoption("review_output", default=None)

    # Handle different output formats
    if output_format == "json":
        json_reporter = JsonReporter()
        json_reporter.generate_report(results, total_tests, score)

        if output_file:
            json_reporter.write_to_file(output_file)
            terminalreporter._tw.line(
                f"\npytest-review: JSON report written to {output_file}",
                green=True,
            )
        else:
            # Print JSON to stdout
            terminalreporter._tw.line("\n" + json_reporter.get_json())

    elif output_format == "html":
        html_reporter = HtmlReporter()
        html_reporter.generate_report(results, total_tests, score)

        if output_file:
            html_reporter.write_to_file(output_file)
            terminalreporter._tw.line(
                f"\npytest-review: HTML report written to {output_file}",
                green=True,
            )
        else:
            # Default filename for HTML
            default_path = Path("pytest-review-report.html")
            html_reporter.write_to_file(default_path)
            terminalreporter._tw.line(
                f"\npytest-review: HTML report written to {default_path}",
                green=True,
            )

    else:
        # Terminal output (default)
        reporter = TerminalReporter(terminalreporter)
        reporter.write_header()
        reporter.write_results(results)
        reporter.write_summary(results, total_tests)
        reporter.write_score(score)
        reporter.write_footer()

    # Handle strict mode and min score
    strict = config.getoption("review_strict", default=False)
    min_score = config.getoption("review_min_score", default=0)

    if strict and _plugin.has_errors():
        terminalreporter._tw.line(
            "\nFAILED: Quality errors found (--review-strict enabled)",
            red=True,
            bold=True,
        )
        session = config._store.get(pytest.StashKey[pytest.Session](), None)
        if session:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    if score < min_score:
        terminalreporter._tw.line(
            f"\nFAILED: Quality score {score:.1f} below minimum {min_score}",
            red=True,
            bold=True,
        )
