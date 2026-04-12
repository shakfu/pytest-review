# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.4]

### Added

- **Plugin API for custom analyzers**: third-party packages can now register analyzers via the `pytest_review` entry point group. Declare `[project.entry-points.pytest_review]` in your `pyproject.toml` pointing to a `StaticAnalyzer` or `DynamicAnalyzer` subclass. Discovered analyzers integrate automatically with `--review-only`/`--review-exclude`, `pyproject.toml` configuration, scoring, and parallel workers. Set the `category` class attribute to one of the 5 scoring categories (`assertions`, `clarity`, `isolation`, `simplicity`, `performance`) to contribute to the quality score.
- **Incremental caching**: static analysis results are now cached per file, keyed on the SHA-256 content hash and a config hash. Unchanged files are skipped on subsequent runs. Disable with `--review-no-cache`.
- **Parallel analysis**: `--review-workers=N` dispatches static analysis to a `ProcessPoolExecutor` across files. `--review-workers=0` (default) auto-enables parallelism for large suites (200+ tests across 8+ files). `--review-workers=1` forces sequential execution.
- `smells.ignored_test` now flags runtime `pytest.skip(...)` and `pytest.xfail(...)` calls inside test bodies, in addition to the existing `@pytest.mark.skip` / `@pytest.mark.skipif` decorator detection. `pytest.importorskip(...)` is deliberately excluded because it expresses a legitimate optional-dependency gate.
- `smells.ignored_test` decorator detection now recognizes `@mark.skip` / `@mark.skipif` (from `from pytest import mark`), not just fully qualified `@pytest.mark.skip`.
- `smells.ignored_test` now also catches unittest-style runtime skips: `self.skipTest(...)`, `raise unittest.SkipTest(...)`, and bare `raise SkipTest(...)`.
- New heuristic: `smells.early_return` flags `return` statements inside a test body. Tests have no reason to return, and an early `return` is a common hack to silently disable downstream assertions. Nested helper functions are excluded from the scan.
- New heuristic: `smells.swallowed_assertion` (ERROR) flags `except AssertionError`, `except Exception`, and `except BaseException` inside test bodies -- all three silently swallow assertion failures, turning dead tests into apparently passing ones. Bare `except:` is intentionally left to `patterns.bare_except` to avoid double-reporting.
- New heuristic: `isolation.process_mutation` flags process-wide state mutations: `os.chdir(...)`, `sys.path.append/insert/extend/...`, `sys.path[...] = ...`, `sys.argv.append(...)`, and `sys.argv[...] = ...`. Previously `sys.path.append` was reported under the generic `isolation.class_attr_modification` rule with an unhelpful suggestion; `os.chdir` was not caught at all.

### Changed

- `ScoringEngine._group_by_category` and `_calculate_category_score` now use `Issue` instead of `Any` in their type signatures.

### Fixed

- `SmellVisitor` ran `_finalize_checks` once per nested function definition inside a test, which could produce duplicate reports (e.g. assertion roulette counted twice) when a test contained helper functions. Finalization now runs exactly once, for the outer test function.
- `collect_test_info()` re-read and re-parsed the entire file for every test function, resulting in O(N) full-file parses for a file with N tests. Parsed ASTs are now cached per file path for the duration of the session.
- `collect_test_info()` matched test functions by name only, ignoring the enclosing class. Identically-named methods in different classes within the same file (e.g. `TestA.test_login` and `TestB.test_login`) could be misidentified. The match now verifies the parent `ClassDef` when the test belongs to a class.
- `_check_conditional_logic()` and `_check_try_except()` in `SmellVisitor` used `ast.walk()`, which traverses into nested function definitions. This was inconsistent with `_check_early_return()` and `_check_swallowed_assertion()`, which correctly used `_walk_test_body()` to exclude nested scopes. Both methods now use `_walk_test_body()`.
- Removed unreachable `"urlopen": set()` entry from `PatternVisitor._SLOW_CALLS`. The `urlopen` key could never match because the lookup requires a module name, not a method name; `urllib.request.urlopen()` is handled by a dedicated code path.

## [0.1.3]

### Added

- `--review-min-severity` option (and corresponding `min_severity` key in `[tool.pytest-review]`) to filter displayed issues by severity. Accepts `info`, `warning`, or `error`. CLI flag overrides the config value. Filtering is display-only: scoring, `--review-strict`, and `--review-min-score` continue to operate on the full, unfiltered set of issues.
- `assertions.missing` now recognizes mock assertion methods (`mock.assert_called_once()`, `assert_called_with()`, `assert_any_call()`, `assert_not_called()`, `assert_has_calls()`), unittest-style helpers (`self.assertEqual()`, `assertTrue()`, `assertRaises()`, etc.), user-defined assertion helpers whose names begin with `assert_` (e.g. `assert_rss_bounded()`), and unqualified `raises()` / `warns()` / `approx()` imported from `pytest`.

### Changed

- **Breaking:** The default display threshold is now `warning`. `info`-level issues (e.g. `assertions.low_value`, `assertions.yoda_condition`, `assertions.raises_without_match`, `naming.too_short`, `smells.magic_number`) are hidden from terminal/JSON/HTML reports by default. Run with `--review-min-severity=info` or set `min_severity = "info"` in `pyproject.toml` to restore the previous behavior. Scores are unaffected.

### Fixed

- False positives in `assertions.missing` for tests whose only assertions were mock assertion methods, unittest-style assertions, or user-defined `assert_*` helpers. Previously these were counted as assertion-less because the detector only recognized `assert` statements and qualified `pytest.raises`/`warns`/`approx`.

## [0.1.2]

### Added

- `--review-diff` option to analyze only tests in files changed relative to a base branch. Supports auto-detection of main/master or an explicit branch name (e.g., `--review-diff=develop`).
- `--review-exclude` option to exclude specific analyzers (complement to `--review-only`).
- Performance aggregate statistics in terminal output: mean, median, P95, min, max, and slow/very-slow counts.
- Inline suppression via `# review: ignore[rule1,rule2]` comments to suppress specific rules per test.
- Typed configuration dataclasses per analyzer, replacing untyped `get_option() -> object`.
- Warnings when test files cannot be read or parsed, instead of silently skipping them.
- Warning when `--review-format=html` is used without `--review-output`.
- Analyzer attribution in terminal output (issues now show which analyzer flagged them).
- New heuristic: `patterns.subprocess_no_check` flags `subprocess.run()` calls without `check=True`.
- New heuristic: `patterns.broad_raises` flags `pytest.raises(Exception)` as too broad.
- New heuristic: `isolation.env_mutation` flags direct `os.environ` mutations with suggestion to use `monkeypatch.setenv`.
- New heuristic: `smells.conditional_test` flags `if/else` branches inside test bodies.
- New heuristic: `smells.too_many_fixtures` flags tests with more than 5 parameters (fixtures).
- New heuristic: `assertions.low_value` flags `assert isinstance(...)` and `assert x is not None` as weak assertions.
- New heuristic: `assertions.raises_without_match` flags `pytest.raises()` without `match=` keyword.
- New heuristic: `naming.redundant_prefix` flags stuttering names like `test_test_connection`.
- New heuristic: `naming.missing_verb` flags test names that don't start with an action verb after `test_`.
- New heuristic: `patterns.mutable_default` flags mutable default arguments (`[]`, `{}`, `set()`) in function definitions.
- New heuristic: `isolation.bare_patch` flags `mock.patch()` / `patch.object()` calls not used as context managers.
- New heuristic: `smells.try_except_in_test` flags `try/except` blocks inside test bodies.
- New heuristic: `complexity.low_assertion_ratio` flags tests where assertions are less than 10% of statements.
- New heuristic: `complexity.excessive_parametrize` flags `@pytest.mark.parametrize` with more than 20 cases.
- New heuristic: `assertions.yoda_condition` flags reversed comparisons like `assert 42 == x`.
- New heuristic: `patterns.slow_call` flags unmocked network calls (`requests`, `httpx`, `urllib`) and database operations (`cursor.execute`, `session.query`).

### Fixed

- Exit status was not set correctly due to broken `config._store.get()` call; now uses `session.exitstatus` in `pytest_sessionfinish`.
- `ignore_paths` and `ignore_rules` from config were parsed but never applied; they now filter tests and issues as documented.
- `elif` branches were double-counted in cyclomatic complexity calculation.
- Docstrings were incorrectly counted as statements in the complexity analyzer.
- `config.from_dict()` mutated its input dictionary via `.pop()`; now uses non-mutating dict comprehension.
- `open()` detection in patterns analyzer produced false positives for properly context-managed `with open()` calls.
- Isolation analyzer used fragile `name[0].isupper()` heuristic; replaced with scope analysis that tracks local names (parameters, assignments, imports) to accurately detect external state modifications.
- Missing `tomli` dependency for Python < 3.11.
- Missing `max_complexity` and `very_slow_threshold_ms` in `pyproject.toml` config.
- Redundant score computation (two separate `ScoringEngine` instances per report); now cached.

### Changed

- Plugin state management: replaced module-level `global _plugin` with `config.stash` (pytest 7.0+), scoping the plugin instance to the session.
- `ScoringEngine` no longer stores instance state (`_results`, `_total_tests`); methods accept data as parameters.

### Removed

- Dead code: `DynamicCollector` (never imported) and `IsolationDynamicAnalyzer` (stub with no implementation).
- Backwards-compatibility alias `self._analyzers = self._static_analyzers` in plugin.

## [0.1.1]

### Fixed

- Fixed some entries, like project url and optional dependencies in pyproject.toml which were incorrect.

## [0.1.0]

### Added

- Initial release of pytest-review

#### Core Features
- pytest plugin integration with `--review` flag
- Quality scoring system with letter grades (A-F)
- Multiple output formats: terminal, JSON, HTML
- Configurable via `pyproject.toml`

#### Analyzers
- **assertions**: Detects empty tests, trivial assertions (`assert True`), tautologies
- **naming**: Checks for descriptive test names, snake_case convention, minimum length
- **complexity**: Flags high statement count, deep nesting, cyclomatic complexity
- **patterns**: Identifies anti-patterns (bare except, `time.sleep`, print statements, `os.system`)
- **isolation**: Detects global state modifications, class attribute mutations
- **performance**: Tracks slow tests at runtime
- **smells**: Detects test smells (assertion roulette, duplicate asserts, eager tests, magic numbers, skipped tests)

#### CLI Options
- `--review`: Enable test quality review
- `--review-format`: Output format (terminal/json/html)
- `--review-output`: Write report to file
- `--review-strict`: Fail if quality errors are found
- `--review-min-score`: Minimum required score (0-100)
- `--review-only`: Run specific analyzers only

#### Reporters
- Terminal reporter with colored output
- JSON reporter with structured data
- HTML reporter with styled dashboard

### Acknowledgments

The smells analyzer is inspired by the [pytest-smell](https://github.com/maxpacs98/disertation) project.
Test smell concepts based on research by Van Deursen et al. and Meszaros.

[Unreleased]: https://github.com/shakeeb-alireza/pytest-review/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/shakeeb-alireza/pytest-review/releases/tag/v0.1.0
