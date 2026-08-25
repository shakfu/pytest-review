# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-26

This release re-scopes pytest-review as a **defect finder that complements ruff**, rather than a general test-quality linter. The rule set went from 47 rules to 28, and every remaining rule is meant to indicate an actual defect: a test that verifies nothing, cannot fail, or leaks into other tests.

The motivating measurement: on a healthy 322-test suite, the previous rule set produced 289 INFO-level findings -- roughly one per test -- of which 230 came from a single rule. It now produces 7 across the same suite, while catching *more* real defects in a deliberately bad one.

**This release contains breaking changes.** See *Migrating from 0.1.x* at the end.

### Added

- **`leaks` analyzer (runtime): `leaks.env`, `leaks.cwd`, `leaks.sys_path` (WARNING).** Compares the process before a test and after its teardown, reporting state the test changed and never restored. This is the class of defect static analysis cannot reach -- the mutation may happen inside a helper or a library call, with nothing in the test's own source to show it. The comparison deliberately runs *after teardown*, so `monkeypatch` and other restoring fixtures are not reported. On first run it found three genuine leaks in this project's own test suite.

- `assertions.always_true` (ERROR) -- `assert (x > 0 for x in items)` asserts on the generator object, which is always truthy, so the comparison never runs. Same for a lambda.

- `assertions.uncalled_assertion` (ERROR) -- `assert mock.assert_called_once` references the method without calling it, so the assertion always passes. Ruff's `PGH005` catches the bare-statement form; this catches it inside an `assert`.

- `assertions.mock_tautology` (ERROR) -- the test asserts on a direct call to a target it patched itself, so it verifies `unittest.mock` rather than any application code. Patching a dependency and asserting on the code that uses it is not reported, nor is asserting on the mock object.

- `smells.vacuous_loop` (WARNING) -- every assertion in the test sits inside a `for` loop, so the test passes having verified nothing if the iterable turns out to be empty. Loops over a non-empty literal or `range(n)` are exempt, as is any test with an assertion outside the loop.

- **Warning for unknown analyzer names** in `--review-only`, `--review-exclude` and `[tool.pytest-review.analyzers]`. Previously `--review-only=naming` against a build without a `naming` analyzer selected nothing, analyzed nothing, and reported success -- a CI job pinned to a removed analyzer would pass while checking nothing.

- Golden regression suite (`tests/test_golden_suite.py`): idiomatic test patterns that must produce zero WARNING+ findings, checked against every static analyzer. The entries are additionally *executed* as a real pytest module, so an entry that documents an API which does not exist fails the suite.

### Changed

- **The quality score is no longer printed by default.** It appears only when `--review-min-score` (or `min_score`) sets a threshold. The findings are the product; leading with a grade invites tuning the number instead of fixing the tests.

- **Quality score recalibrated as a defect *density*.** Severity penalties are now expressed on a per-test scale (an ERROR costs a test all of its credit within its category), each test's penalty saturates so one very bad test cannot outweigh the rest of the suite, and critical penalties scale with the fraction of tests affected rather than accumulating per issue. The score is now invariant to suite size and spans the full A-F range: one empty test in a 100-test suite scores 99.0 (A) instead of 80 (B), while a suite in which every test is empty scores 0 (F). The critical penalty for `assertions.missing` is derived from the assertions category weight rather than chosen, so a suite that verifies nothing lands on 0 by construction.

- **Incremental cache now invalidates when the analysis itself changes**, not only when a file's contents or explicitly-set options change. The key additionally covers the package version, the *resolved* per-analyzer settings (so a changed default threshold invalidates), and a hash of every registered analyzer module's source (so editing a rule invalidates the findings it emitted). Previously an upgrade silently served the previous version's findings for every unchanged file until `--cache-clear` was run, with no indication the output was stale.

- `patterns.slow_call` raised from INFO to WARNING for **network** I/O (`requests`, `httpx`, `urllib`), matching `patterns.sleep_in_test`. Suspected **database** I/O stays at INFO, because it is matched by variable name (`cursor`, `session`, `conn`, `db`) rather than against a known API.

- Default `max_assertions_without_message` was raised from 1 to 4 before that rule was removed entirely; `examples/bad_tests.py` now demonstrates every shipped rule.

### Removed

- **The rule set is now a defect finder, not a style checker: 47 rules -> 28.** Anything ruff already covers was dropped (`patterns.bare_except` = `E722`, `patterns.is_literal` = `F632`, `patterns.mutable_default` = `B006`, `assertions.raises_without_match` = `PT011`, `patterns.print_statement` = `T201`, `patterns.open_without_context` = `SIM115`, `patterns.swallowed_exception` = `S110`, `patterns.broad_raises` = `PT011`, `patterns.legacy_mock`). Enable ruff's `PT` rules alongside this plugin; see the README.

- **The `naming` and `complexity` analyzers were retired entirely.** Test-name conventions are style, and cyclomatic complexity is ruff `C901`. `complexity.low_assertion_ratio` survives as `assertions.low_ratio`, since "lots of setup, nothing verified" is a real defect signal.

- `smells.eager_test`, `smells.magic_number`, `smells.assertion_roulette`, `smells.conditional_test`, `smells.too_many_fixtures`, `assertions.low_value`, `assertions.yoda_condition` and `naming.missing_verb` were dropped: style opinions that fired constantly on healthy code without indicating a defect.

- Note there is deliberately **no "too many mocks" rule**. The right number depends on how many collaborators the code has, so a threshold would be an opinion rather than a defect.

### Fixed

False positives, all found by running the analyzers over realistic, idiomatic test code:

- `isolation.bare_patch` no longer flags `@patch(...)` / `@mock.patch(...)` decorators, which guarantee cleanup by the framework and are the most common mock idiom.

- `smells.ignored_test` and `smells.conditional_test` no longer flag the documented `if cond: pytest.skip(...)` / `raise SkipTest` platform-gate pattern, including `elif`-chained gates. Unguarded runtime skips are still reported.

- `smells.try_except_in_test` no longer flags `try/finally` blocks, which have no handlers and cannot mask failures.

- `smells.early_return` no longer flags `return` statements that are the sole body of an `if` (deliberate test toggles); only unconditional mid-body returns are reported.

- `smells.duplicate_assert` no longer flags an assertion repeated *across a state change* (`assert x is False` / mutate / `assert x is True`), which is the standard way to check that an operation had an effect. Only repeats within an unbroken run of assertions are reported.

- `assertions.low_value` no longer treated two guards on one variable as vouching for each other (before the rule was removed).

- `patterns.hardcoded_path` no longer flags absolute-path-looking string constants in general (e.g. expected output or URL strings); it now only flags string arguments to path-consuming calls (`open`, `Path`, `os.*`, `os.path.*`, `shutil.*`, `glob.*`, `tempfile.*`), at INFO.

- `complexity` metrics no longer counted nested helper bodies or double-counted comprehensions (before that analyzer was removed).

### Migrating from 0.1.x

- **Remove `naming` and `complexity` from `[tool.pytest-review.analyzers]`**, along with any `--review-only`/`--review-exclude` references to them. Unknown names now warn rather than being silently ignored.

- **Enable ruff's pytest rules** to cover what was dropped: `select = ["E", "F", "B", "SIM", "PT"]`.

- **Suppression comments referencing removed rules** (`# review: ignore[naming.too_short]`) are harmless but no longer do anything.

- **Expect different scores.** The scoring model changed, so a `min_score` threshold tuned against 0.1.x will not mean the same thing. Re-baseline it against a run of your suite.

- **Clear the cache once** (`pytest --cache-clear`) if upgrading from 0.1.5 or earlier: those versions keyed the cache without the plugin version, so stale findings could otherwise be served.

## [0.1.5]

### Fixed

- **Parametrized tests were skipped by static analysis entirely.** Test items were matched against the AST by `item.name`, which for a parametrized case is `test_foo[case0]` while the function node is named `test_foo`, so no match was ever found. Parametrized tests are now resolved via `Function.originalname` (falling back to stripping the parameter suffix). Because every case shares one source function, the function is analyzed once rather than once per case, so issues are not duplicated and score penalties are not multiplied.

- **The incremental cache could return another file's results.** The cache key combined only the content hash and the config hash, so two test files with byte-identical contents shared a single entry and each could be served the other's cached `Issue.file_path` values -- reports pointed at the wrong file and per-file findings were duplicated or lost. The key now also includes the file path, normalized relative to the pytest root. Existing cache entries are invalidated by the key-format bump.

- **`strict` and `min_score` in `[tool.pytest-review]` were parsed but never enforced.** Session finish and terminal reporting read only the CLI options, so a project configuring `strict = true` or `min_score = 80` in `pyproject.toml` silently got a passing exit status in CI. Both settings are now honoured, with CLI options taking precedence.

- **Duplicate test names collapsed in the performance analyzer.** Runtime durations and slow-test issues were keyed on `item.name`, so identically named tests in different modules or classes overwrote each other, undercounting timing statistics and dropping slow-test findings. Dynamic analyzers now receive the pytest node id.

- `--review` crashed with `AttributeError: 'Config' object has no attribute 'cache'` when pytest ran with `-p no:cacheprovider`.

- `make example-verify` did not pass `--review-min-severity=info`, so INFO-severity rules were filtered out of the JSON report and the target failed despite all rules being detected correctly.

### Changed

- The `DynamicAnalyzer.on_test_start` / `on_test_end` hooks now document their first parameter as a unique test identifier (renamed `test_name` to `test_id`); the plugin passes pytest's node id rather than a bare function name. Third-party dynamic analyzers keying state on this value gain correct disambiguation; those that displayed it will now show a node id.

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

The smells analyzer is inspired by the [pytest-smell](https://github.com/maxpacs98/disertation) project. Test smell concepts based on research by Van Deursen et al. and Meszaros.

[Unreleased]: https://github.com/shakeeb-alireza/pytest-review/compare/v0.2.0...HEAD [0.2.0]: https://github.com/shakeeb-alireza/pytest-review/compare/v0.1.5...v0.2.0 [0.1.0]: https://github.com/shakeeb-alireza/pytest-review/releases/tag/v0.1.0
