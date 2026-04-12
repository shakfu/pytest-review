"""Pytest plugin entry point for pytest-review."""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import importlib.metadata
import json
import os
import subprocess
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    Issue,
    Severity,
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


def _find_parent_class(
    tree: ast.Module, target: ast.FunctionDef | ast.AsyncFunctionDef
) -> ast.ClassDef | None:
    """Return the ClassDef that directly contains *target*, or None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if child is target:
                    return node
    return None


# Built-in static analyzer classes.
_BUILTIN_STATIC_ANALYZER_CLASSES: dict[str, type[StaticAnalyzer]] = {
    "assertions": AssertionsAnalyzer,
    "naming": NamingAnalyzer,
    "complexity": ComplexityAnalyzer,
    "patterns": PatternsAnalyzer,
    "isolation": IsolationStaticAnalyzer,
    "smells": SmellsAnalyzer,
}

# Module-level cache; populated once per process (important for workers).
_static_analyzer_classes_cache: dict[str, type[StaticAnalyzer]] | None = None


def _discover_entry_point_analyzers() -> dict[str, type[StaticAnalyzer | DynamicAnalyzer]]:
    """Discover analyzer classes registered via ``pytest_review`` entry points.

    Third-party packages register analyzers in their ``pyproject.toml``::

        [project.entry-points.pytest_review]
        my-analyzer = "my_package:MyAnalyzer"
    """
    discovered: dict[str, type[StaticAnalyzer | DynamicAnalyzer]] = {}
    try:
        eps = importlib.metadata.entry_points(group="pytest_review")
    except TypeError:
        # Python 3.9 fallback: entry_points() returns a dict-like object
        all_eps = importlib.metadata.entry_points()
        eps = all_eps.get("pytest_review", [])  # type: ignore[union-attr]
    for ep in eps:
        try:
            cls = ep.load()
            if isinstance(cls, type) and issubclass(cls, (StaticAnalyzer, DynamicAnalyzer)):
                discovered[cls.name] = cls
        except Exception:
            warnings.warn(
                f"pytest-review: failed to load analyzer entry point '{ep.name}'",
                stacklevel=2,
            )
    return discovered


def _get_static_analyzer_classes() -> dict[str, type[StaticAnalyzer]]:
    """Return the full static analyzer class mapping (built-in + entry points).

    Cached per process so ``ProcessPoolExecutor`` workers pay the discovery
    cost only once.
    """
    global _static_analyzer_classes_cache  # noqa: PLW0603
    if _static_analyzer_classes_cache is None:
        classes = dict(_BUILTIN_STATIC_ANALYZER_CLASSES)
        for name, cls in _discover_entry_point_analyzers().items():
            if issubclass(cls, StaticAnalyzer):
                classes[name] = cls  # type: ignore[assignment]
        _static_analyzer_classes_cache = classes
    return _static_analyzer_classes_cache


def _compute_file_hash(file_path: Path) -> str:
    """Return a short SHA-256 hex digest of a file's contents."""
    return hashlib.sha256(file_path.read_bytes()).hexdigest()[:16]


def _serialize_results(results: list[AnalyzerResult]) -> list[dict[str, Any]]:
    """Convert analysis results to JSON-serializable dicts for caching."""
    return [
        {
            "analyzer_name": r.analyzer_name,
            "score": r.score,
            "metadata": {
                k: v
                for k, v in r.metadata.items()
                if isinstance(v, (str, int, float, bool, type(None)))
            },
            "issues": [
                {
                    "rule": i.rule,
                    "message": i.message,
                    "severity": i.severity.value,
                    "file_path": str(i.file_path) if i.file_path else None,
                    "line": i.line,
                    "test_name": i.test_name,
                    "suggestion": i.suggestion,
                }
                for i in r.issues
            ],
        }
        for r in results
    ]


def _deserialize_results(data: list[dict[str, Any]]) -> list[AnalyzerResult]:
    """Reconstruct analysis results from cached JSON dicts."""
    results: list[AnalyzerResult] = []
    for entry in data:
        issues = [
            Issue(
                rule=i["rule"],
                message=i["message"],
                severity=Severity(i["severity"]),
                file_path=Path(i["file_path"]) if i["file_path"] else None,
                line=i["line"],
                test_name=i["test_name"],
                suggestion=i.get("suggestion"),
            )
            for i in entry["issues"]
        ]
        results.append(
            AnalyzerResult(
                analyzer_name=entry["analyzer_name"],
                issues=issues,
                score=entry.get("score", 100.0),
                metadata=entry.get("metadata", {}),
            )
        )
    return results


def _analyze_file_static(
    file_path_str: str,
    test_specs: list[tuple[str, str | None]],
    review_config: ReviewConfig,
    analyzer_names: list[str],
    ignore_rules: list[str],
) -> list[AnalyzerResult]:
    """Analyze all tests in a single file.

    Top-level function so it can be pickled and dispatched to a
    ``ProcessPoolExecutor`` worker.
    """
    file_path = Path(file_path_str)
    try:
        source = file_path.read_text()
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []

    # Locate each test node in the AST
    test_infos: list[TestItemInfo] = []
    for test_name, class_name in test_specs:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != test_name:
                continue
            if class_name is not None:
                parent = _find_parent_class(tree, node)
                if parent is None or parent.name != class_name:
                    continue
            func_source = ast.get_source_segment(source, node) or ""
            suppressed = parse_suppressed_rules(func_source)
            test_infos.append(
                TestItemInfo(
                    name=test_name,
                    file_path=file_path,
                    line=node.lineno,
                    node=node,
                    source=func_source,
                    class_name=class_name,
                    suppressed_rules=suppressed,
                )
            )
            break

    # Reconstruct analyzers from config
    ignore_set = set(ignore_rules)
    analyzers: list[StaticAnalyzer] = []
    for name in analyzer_names:
        cls = _get_static_analyzer_classes().get(name)
        if cls is not None:
            a = cls(review_config)
            if a.enabled:
                analyzers.append(a)

    # Run analysis
    results: list[AnalyzerResult] = []
    for analyzer in analyzers:
        for test_info in test_infos:
            result = analyzer.analyze(test_info)
            if ignore_set:
                result.issues = [i for i in result.issues if i.rule not in ignore_set]
            if result.issues:
                results.append(result)
    return results


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
        self._ast_cache: dict[Path, tuple[str, ast.Module]] = {}
        self._workers: int = int(config.getoption("review_workers", default=0))
        self._use_cache: bool = not config.getoption("review_no_cache", default=False)

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
        """Register all built-in and entry-point-discovered analyzers."""
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

        # Discover third-party analyzers via entry points
        for _ep_name, cls in _discover_entry_point_analyzers().items():
            analyzer = cls(self.review_config)
            if isinstance(analyzer, DynamicAnalyzer):
                dynamic_analyzers.append(analyzer)
            elif isinstance(analyzer, StaticAnalyzer):
                static_analyzers.append(analyzer)

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

    def _get_ast(self, file_path: Path) -> tuple[str, ast.Module]:
        """Return (source, parsed AST) for *file_path*, using a per-session cache."""
        cached = self._ast_cache.get(file_path)
        if cached is not None:
            return cached
        source = file_path.read_text()
        tree = ast.parse(source)
        self._ast_cache[file_path] = (source, tree)
        return source, tree

    def collect_test_info(self, item: Function) -> TestItemInfo | None:
        """Extract test information from a pytest item."""
        try:
            file_path = Path(item.fspath) if item.fspath else None
            if file_path is None:
                return None

            source, tree = self._get_ast(file_path)

            # Find the test function in the AST
            test_name = item.name
            class_name = item.cls.__name__ if item.cls else None

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name != test_name:
                    continue
                # When the test belongs to a class, ensure the node is inside
                # the correct ClassDef to avoid misidentifying identically-named
                # methods in different classes within the same file.
                if class_name is not None:
                    parent = _find_parent_class(tree, node)
                    if parent is None or parent.name != class_name:
                        continue

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

    def _get_config_hash(self, analyzer_names: list[str]) -> str:
        """Hash the review config state that affects static analysis output."""
        key_data = {
            "analyzers": analyzer_names,
            "ignore_rules": sorted(self.review_config.ignore_rules),
            "config": {
                name: {"enabled": cfg.enabled, "options": cfg.options}
                for name, cfg in self.review_config.analyzers.items()
            },
        }
        raw = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _should_use_parallel(self, num_files: int, total_tests: int) -> bool:
        """Decide whether to dispatch static analysis to a process pool."""
        if self._workers == 1:
            return False
        if self._workers > 1:
            return True
        # Auto: only worthwhile when the suite is large enough to amortize
        # the per-worker startup and pickling overhead.
        return num_files >= 8 and total_tests >= 200

    def _run_sequential_analysis(
        self, files_to_analyze: dict[Path, list[TestItemInfo]]
    ) -> list[AnalyzerResult]:
        """Run static analyzers sequentially (default path)."""
        results: list[AnalyzerResult] = []
        for test_infos in files_to_analyze.values():
            for analyzer in self._static_analyzers:
                for test_info in test_infos:
                    result = analyzer.analyze(test_info)
                    result = self._filter_ignored_rules(result)
                    if result.issues:
                        results.append(result)
        return results

    def _run_parallel_analysis(
        self,
        files_to_analyze: dict[Path, list[TestItemInfo]],
        analyzer_names: list[str],
        ignore_rules: list[str],
    ) -> list[AnalyzerResult]:
        """Run static analysis in parallel across files via ProcessPoolExecutor."""
        max_workers = (
            self._workers
            if self._workers > 1
            else min(os.cpu_count() or 1, len(files_to_analyze))
        )
        results: list[AnalyzerResult] = []
        try:
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        _analyze_file_static,
                        str(file_path),
                        [(t.name, t.class_name) for t in test_infos],
                        self.review_config,
                        analyzer_names,
                        ignore_rules,
                    ): file_path
                    for file_path, test_infos in files_to_analyze.items()
                }
                for future in futures:
                    try:
                        results.extend(future.result())
                    except Exception:
                        pass  # skip failed files, consistent with collect_test_info
        except (OSError, RuntimeError):
            # Process pool unavailable -- fall back to sequential.
            return self._run_sequential_analysis(files_to_analyze)
        return results

    def run_static_analysis(self) -> None:
        """Run all registered static analyzers on collected tests.

        Supports two optimisations:
        * **Incremental cache** -- results are cached per file keyed on a
          SHA-256 content hash and a config hash.  Unchanged files are
          skipped on subsequent runs.  Disable with ``--review-no-cache``.
        * **Parallel analysis** -- when the suite is large enough (or
          ``--review-workers`` is set), analysis is dispatched to a
          ``ProcessPoolExecutor`` across files.
        """
        if not self._static_analyzers or not self._test_infos:
            return

        analyzer_names = [a.name for a in self._static_analyzers]
        ignore_rules = self.review_config.ignore_rules

        # Group tests by file
        tests_by_file: dict[Path, list[TestItemInfo]] = {}
        for test_info in self._test_infos:
            tests_by_file.setdefault(test_info.file_path, []).append(test_info)

        # Incremental cache: look up previously computed results per file
        cache = self.pytest_config.cache if self._use_cache else None
        config_hash = self._get_config_hash(analyzer_names) if cache else ""
        files_to_analyze: dict[Path, list[TestItemInfo]] = {}

        for file_path, test_infos in tests_by_file.items():
            if cache is not None:
                file_hash = _compute_file_hash(file_path)
                cache_key = f"review/v1/{file_hash}_{config_hash}"
                cached = cache.get(cache_key, None)
                if cached is not None:
                    self._results.extend(_deserialize_results(cached))
                    continue
            files_to_analyze[file_path] = test_infos

        if not files_to_analyze:
            return

        # Analyze uncached files -- parallel or sequential
        num_files = len(files_to_analyze)
        total_tests = sum(len(ts) for ts in files_to_analyze.values())

        if self._should_use_parallel(num_files, total_tests):
            fresh = self._run_parallel_analysis(
                files_to_analyze, analyzer_names, ignore_rules
            )
        else:
            fresh = self._run_sequential_analysis(files_to_analyze)

        # Store fresh results in cache
        if cache is not None:
            results_by_file: dict[Path, list[AnalyzerResult]] = {
                fp: [] for fp in files_to_analyze
            }
            for result in fresh:
                if result.issues and result.issues[0].file_path:
                    fp = result.issues[0].file_path
                    if fp in results_by_file:
                        results_by_file[fp].append(result)
            for file_path in files_to_analyze:
                file_hash = _compute_file_hash(file_path)
                cache_key = f"review/v1/{file_hash}_{config_hash}"
                cache.set(
                    cache_key,
                    _serialize_results(results_by_file.get(file_path, [])),
                )

        self._results.extend(fresh)

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

    def get_display_results(self, min_severity: Severity) -> list[AnalyzerResult]:
        """Return results with issues below ``min_severity`` removed.

        Does not mutate the underlying results -- scoring and ``has_errors``
        continue to operate on the full, unfiltered set.
        """
        filtered: list[AnalyzerResult] = []
        for result in self._results:
            kept = [issue for issue in result.issues if not (issue.severity < min_severity)]
            if not kept:
                continue
            filtered.append(
                AnalyzerResult(
                    analyzer_name=result.analyzer_name,
                    issues=kept,
                    score=result.score,
                    metadata=result.metadata,
                )
            )
        return filtered

    def has_errors(self) -> bool:
        """Check if any analyzer found errors."""
        return any(r.has_errors for r in self._results)

    def _ensure_score_breakdown(self) -> dict[str, object]:
        """Compute and cache the score breakdown."""
        if self._score_breakdown is None:
            # Collect category mappings from analyzers that declare one
            extra_categories: dict[str, str] = {}
            for a in self._static_analyzers:
                if a.category:
                    extra_categories[a.name] = a.category
            for a in self._dynamic_analyzers:
                if a.category:
                    extra_categories[a.name] = a.category
            engine = ScoringEngine(extra_categories=extra_categories or None)
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


def _parse_severity(name: str) -> Severity:
    """Map a severity string (``info``/``warning``/``error``) to a Severity enum."""
    normalized = (name or "warning").lower()
    if normalized == "info":
        return Severity.INFO
    if normalized == "warning":
        return Severity.WARNING
    if normalized == "error":
        return Severity.ERROR
    raise ValueError(
        f"Invalid severity {name!r}; expected one of info, warning, error"
    )


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
        "--review-min-severity",
        action="store",
        default=None,
        dest="review_min_severity",
        choices=["info", "warning", "error"],
        help="Only display issues at or above this severity (default: warning; "
        "can also be set via [tool.pytest-review] min_severity in pyproject.toml). "
        "Does not affect scoring or --review-strict.",
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
    group.addoption(
        "--review-workers",
        action="store",
        type=int,
        default=0,
        dest="review_workers",
        help="Number of parallel worker processes for static analysis. "
        "0 = auto (parallel for large suites), 1 = sequential (default: 0)",
    )
    group.addoption(
        "--review-no-cache",
        action="store_true",
        default=False,
        dest="review_no_cache",
        help="Disable incremental result caching across runs",
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

    # Resolve the effective display severity: CLI flag overrides config.
    cli_severity = config.getoption("review_min_severity", default=None)
    severity_name = cli_severity or plugin.review_config.min_severity
    min_severity = _parse_severity(severity_name)

    results = plugin.get_display_results(min_severity)
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
