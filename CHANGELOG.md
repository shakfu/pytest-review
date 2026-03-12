# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
