"""Pytest plugin entry point for pytest-review."""

from __future__ import annotations

import ast
import fnmatch
import subprocess
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
    parse_suppressed_rules,
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

# Stash key scopes plugin instance to the pytest session config
_review_key = pytest.StashKey["ReviewPlugin"]()


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
        self._score_breakdown: dict[str, object] | None = None

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
        # Get the --review-only and --review-exclude filters
        only = self.pytest_config.getoption("review_only", default=None)
        allowed: set[str] | None = None
        if only:
            allowed = {name.strip() for name in only.split(",")}

        exclude = self.pytest_config.getoption("review_exclude", default=None)
        excluded: set[str] = set()
        if exclude:
            excluded = {name.strip() for name in exclude.split(",")}

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
            if static_analyzer.name in excluded:
                continue
            self.register_analyzer(static_analyzer)

        for dynamic_analyzer in dynamic_analyzers:
            if allowed is not None and dynamic_analyzer.name not in allowed:
                continue
            if dynamic_analyzer.name in excluded:
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
                    suppressed = parse_suppressed_rules(func_source)
                    return TestItemInfo(
                        name=test_name,
                        file_path=file_path,
                        line=node.lineno,
                        node=node,
                        source=func_source,
                        class_name=class_name,
                        suppressed_rules=suppressed,
                    )
        except OSError as exc:
            import warnings

            warnings.warn(
                f"pytest-review: could not read {item.fspath}: {exc}",
                stacklevel=1,
            )
        except SyntaxError as exc:
            import warnings

            warnings.warn(
                f"pytest-review: could not parse {item.fspath}: {exc}",
                stacklevel=1,
            )
        return None

    def _get_changed_files(self, base: str) -> set[Path] | None:
        """Get test files changed relative to a base branch.

        Returns None if git is unavailable or the diff fails, so callers
        can fall back to analyzing everything.
        """
        if base == "auto":
            # Detect main or master
            for candidate in ("main", "master"):
                result = subprocess.run(
                    ["git", "rev-parse", "--verify", candidate],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    base = candidate
                    break
            else:
                import warnings

                warnings.warn(
                    "pytest-review: --review-diff could not detect base branch "
                    "(tried main, master). Analyzing all tests.",
                    stacklevel=2,
                )
                return None

        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            import warnings

            warnings.warn(
                f"pytest-review: git diff failed: {result.stderr.strip()}. Analyzing all tests.",
                stacklevel=2,
            )
            return None

        cwd = Path.cwd()
        return {
            (cwd / line.strip()).resolve() for line in result.stdout.splitlines() if line.strip()
        }

    def _is_path_ignored(self, file_path: Path) -> bool:
        """Check if a file path matches any ignore pattern."""
        ignore_paths = self.review_config.ignore_paths
        if not ignore_paths:
            return False
        path_str = str(file_path)
        return any(fnmatch.fnmatch(path_str, pattern) for pattern in ignore_paths)

    def _filter_ignored_rules(self, result: AnalyzerResult) -> AnalyzerResult:
        """Remove issues matching ignored rules."""
        ignore_rules = self.review_config.ignore_rules
        if not ignore_rules:
            return result
        result.issues = [issue for issue in result.issues if issue.rule not in ignore_rules]
        return result

    def run_static_analysis(self) -> None:
        """Run all registered static analyzers on collected tests."""
        for analyzer in self._static_analyzers:
            for test_info in self._test_infos:
                result = analyzer.analyze(test_info)
                result = self._filter_ignored_rules(result)
                if result.issues:
                    self._results.append(result)

    def run_analysis(self) -> None:
        """Run all registered analyzers on collected tests."""
        # Run static analyzers
        self.run_static_analysis()

        # Collect results from dynamic analyzers
        for analyzer in self._dynamic_analyzers:
            for result in analyzer.get_results():
                result = self._filter_ignored_rules(result)
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

    def _ensure_score_breakdown(self) -> dict[str, object]:
        """Compute and cache the score breakdown."""
        if self._score_breakdown is None:
            engine = ScoringEngine()
            breakdown = engine.calculate_score(self._results, len(self._test_infos))
            self._score_breakdown = breakdown.to_dict()
        return self._score_breakdown

    def calculate_score(self) -> float:
        """Calculate overall quality score."""
        if not self._test_infos:
            return 100.0
        breakdown = self._ensure_score_breakdown()
        return float(breakdown["total_score"])  # type: ignore[arg-type]

    def get_score_breakdown(self) -> dict[str, object]:
        """Get detailed score breakdown."""
        return self._ensure_score_breakdown()

    def get_performance_stats(self) -> dict[str, float]:
        """Get aggregate performance statistics from the performance analyzer."""
        for analyzer in self._dynamic_analyzers:
            if isinstance(analyzer, PerformanceAnalyzer):
                return analyzer.get_statistics()
        return {}


def _get_plugin(config: Config) -> ReviewPlugin | None:
    """Retrieve the plugin instance from config.stash, or None."""
    result: ReviewPlugin | None = config.stash.get(_review_key, None)
    return result


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
    group.addoption(
        "--review-exclude",
        action="store",
        default=None,
        dest="review_exclude",
        help="Comma-separated list of analyzers to exclude",
    )
    group.addoption(
        "--review-diff",
        action="store",
        nargs="?",
        const="auto",
        default=None,
        dest="review_diff",
        help="Only analyze tests in files changed relative to a base branch "
        "(default: auto-detect main/master)",
    )


def pytest_configure(config: Config) -> None:
    """Configure the plugin."""
    # Register marker
    config.addinivalue_line("markers", "review_skip: skip this test from quality review")

    # Create plugin instance and store in config.stash
    plugin = ReviewPlugin(config)
    config.stash[_review_key] = plugin

    # Register plugin if enabled via CLI
    if config.getoption("review", default=False):
        plugin.register_default_analyzers()
        config.pluginmanager.register(plugin, "review_plugin")


def pytest_collection_modifyitems(
    session: pytest.Session, config: Config, items: list[pytest.Item]
) -> None:
    """Collect test information after test collection."""
    plugin = _get_plugin(config)
    if plugin is None or not plugin._enabled:
        return

    # Diff mode: only analyze tests in changed files
    diff_base = config.getoption("review_diff", default=None)
    changed_files: set[Path] | None = None
    if diff_base is not None:
        changed_files = plugin._get_changed_files(diff_base)

    for item in items:
        if isinstance(item, pytest.Function):
            # Skip tests marked with review_skip
            if item.get_closest_marker("review_skip"):
                continue

            # Skip tests in ignored paths
            if item.fspath and plugin._is_path_ignored(Path(item.fspath)):
                continue

            # Skip tests not in changed files (diff mode)
            if (
                changed_files is not None
                and item.fspath
                and Path(item.fspath).resolve() not in changed_files
            ):
                continue

            test_info = plugin.collect_test_info(item)
            if test_info:
                plugin._test_infos.append(test_info)


@pytest.hookimpl(hookwrapper=True)  # type: ignore[untyped-decorator]
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> object:
    """Hook into test execution to track timing."""
    plugin = _get_plugin(item.config)
    if plugin is None or not plugin._enabled:
        yield
        return

    # Notify start
    plugin.on_test_start(item.nodeid, item.name)

    yield

    # We'll get the result in pytest_runtest_makereport


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> None:
    """Called after each test phase (setup, call, teardown)."""
    plugin = _get_plugin(item.config)
    if plugin is None or not plugin._enabled:
        return

    # Only process the 'call' phase (actual test execution)
    if call.when == "call":
        passed = call.excinfo is None
        plugin.on_test_end(item.nodeid, item.name, passed)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Run analysis, check thresholds, and set exit status."""
    plugin = _get_plugin(session.config)
    if plugin is None or not plugin._enabled:
        return

    # Run all analyzers
    plugin.run_analysis()

    # Check strict mode and min score, set exit status if needed
    config = session.config
    strict = config.getoption("review_strict", default=False)
    min_score = config.getoption("review_min_score", default=0)

    if strict and plugin.has_errors():
        session.exitstatus = pytest.ExitCode.TESTS_FAILED

    if min_score > 0:
        score = plugin.calculate_score()
        if score < min_score:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(
    terminalreporter: PytestTerminalReporter, exitstatus: int, config: Config
) -> None:
    """Add review summary to terminal output."""
    plugin = _get_plugin(config)
    if plugin is None or not plugin._enabled:
        return

    results = plugin.get_results()
    total_tests = len(plugin._test_infos)
    score = plugin.calculate_score()

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
            import warnings

            default_path = Path("pytest-review-report.html")
            html_reporter.write_to_file(default_path)
            warnings.warn(
                f"pytest-review: No --review-output specified for HTML format; "
                f"writing to {default_path}",
                stacklevel=1,
            )
            terminalreporter._tw.line(
                f"\npytest-review: HTML report written to {default_path}",
                yellow=True,
            )

    else:
        # Terminal output (default)
        reporter = TerminalReporter(terminalreporter)
        reporter.write_header()
        reporter.write_results(results)
        reporter.write_summary(results, total_tests)
        perf_stats = plugin.get_performance_stats()
        reporter.write_performance_stats(perf_stats)
        reporter.write_score(score)
        reporter.write_footer()

    # Display strict mode and min score failure messages
    strict = config.getoption("review_strict", default=False)
    min_score = config.getoption("review_min_score", default=0)

    if strict and plugin.has_errors():
        terminalreporter._tw.line(
            "\nFAILED: Quality errors found (--review-strict enabled)",
            red=True,
            bold=True,
        )

    if min_score > 0 and score < min_score:
        terminalreporter._tw.line(
            f"\nFAILED: Quality score {score:.1f} below minimum {min_score}",
            red=True,
            bold=True,
        )
