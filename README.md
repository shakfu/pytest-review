# pytest-review

A pytest plugin that reviews the quality of your tests.

[![PyPI version](https://badge.fury.io/py/pytest-review.svg)](https://badge.fury.io/py/pytest-review) [![Python versions](https://img.shields.io/pypi/pyversions/pytest-review.svg)](https://pypi.org/project/pytest-review/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

pytest-review finds defects in your test suite: tests that verify nothing, tests that cannot fail, and tests that leak state into other tests. It runs as a pytest plugin, so it sees real test items, real parametrization, and real runtime.

**It is deliberately not a style checker.** Anything ruff already catches is out of scope, and so are style-only opinions -- see [Relationship to ruff](#relationship-to-ruff).

## Features

- **Static Analysis**: AST-based detection of test quality issues

- **Dynamic Analysis**: Runtime performance tracking

- **Multiple Output Formats**: Terminal, JSON, and HTML reports

- **Configurable**: Customize thresholds and enable/disable analyzers

- **Optional CI Gate**: Fail a build below a quality threshold with `--review-min-score`

- **Incremental Caching**: Skip re-analysis of unchanged files across runs

- **Parallel Analysis**: Distribute static analysis across multiple processes

- **Plugin API**: Register custom analyzers via entry points

### Analyzers

| Analyzer | Description |
|----------|-------------|
| **assertions** | Tests that verify nothing: no assertions, `assert True`, tautologies, near-zero assertion-to-logic ratio |
| **smells** | Tests that cannot fail: swallowed assertions, dead code after `return`, permanently skipped tests |
| **isolation** | Tests that leak: global and class-attribute mutation, `os.environ`, `os.chdir`, `sys.path` |
| **patterns** | Tests that are slow or fragile: `time.sleep`, network and DB calls, unchecked `subprocess.run` |
| **performance** | Slow tests, measured at runtime |
| **leaks** | State a test left behind, measured at runtime: `os.environ`, cwd, `sys.path` |

## Installation

```bash
pip install pytest-review
```

## Quick Start

Run pytest with the `--review` flag:

```bash
pytest --review
```

Example output:

```
====================== pytest-review: Test Quality Report ======================
  [X] <assertions> examples/bad_tests.py:59 [test_empty_no_assertions] Test has no assertions
      Suggestion: Add at least one assertion to verify expected behavior
  [X] <smells> examples/bad_tests.py:339 [test_swallows_assertion_failure] Test catches Exception, which silently swallows assertion failures
      Suggestion: Let assertion failures propagate; use pytest.raises() for expected exceptions
  [!] <isolation> examples/bad_tests.py:352 [test_mutates_process_state] Test calls os.chdir(), which mutates process-wide state
      Suggestion: Use the monkeypatch fixture, which restores state automatically
----------------------------------- Summary ------------------------------------
  Tests analyzed: 30
  Errors: 17
  Warnings: 12
  Quality: NEEDS IMPROVEMENT
--------------------------------- Performance ----------------------------------
  Tests timed: 29
  Total: 16ms
  Mean: 1ms | Median: 0ms | P95: 1ms
================================================================================
```

(Findings trimmed; run it yourself with `pytest examples/bad_tests.py --review`. No score is printed because no threshold is set -- add `--review-min-score=70` to gate a build on it.)

(Findings above are trimmed; the run is `pytest examples/bad_tests.py --review`, and the summary figures are that file's real output.)

By default, `info`-level suggestions are hidden. Pass `--review-min-severity=info` to see them.

## Command Line Options

| Option | Description |
|--------|-------------|
| `--review` | Enable test quality review |
| `--review-format` | Output format: `terminal` (default), `json`, `html` |
| `--review-output` | Write report to file |
| `--review-strict` | Fail if quality errors are found |
| `--review-min-score` | Minimum required score (0-100) |
| `--review-min-severity` | Only show issues at or above this severity: `info`, `warning` (default), `error`. Display only -- does not affect scoring or `--review-strict`. |
| `--review-only` | Comma-separated list of analyzers to run |
| `--review-exclude` | Comma-separated list of analyzers to exclude |
| `--review-diff` | Only analyze tests in files changed relative to a base branch (default: auto-detect `main`/`master`) |
| `--review-workers` | Number of parallel worker processes for static analysis. `0` = auto (default), `1` = sequential |
| `--review-no-cache` | Disable incremental result caching across runs |

### Examples

```bash
# Generate HTML report
pytest --review --review-format=html --review-output=report.html

# Generate JSON report
pytest --review --review-format=json --review-output=report.json

# Run only specific analyzers
pytest --review --review-only=assertions,isolation

# Fail CI if score below 80
pytest --review --review-min-score=80

# Strict mode: fail on any errors
pytest --review --review-strict

# Show errors only (hide warnings and info)
pytest --review --review-min-severity=error

# Show everything, including info-level suggestions
pytest --review --review-min-severity=info

# Force sequential analysis (disable parallelism)
pytest --review --review-workers=1

# Disable result caching
pytest --review --review-no-cache
```

## Configuration

Configure pytest-review in your `pyproject.toml`:

```toml
[tool.pytest-review]
enabled = true
strict = false
min_score = 0
min_severity = "warning"  # display threshold: info, warning, or error

[tool.pytest-review.analyzers]
assertions = { enabled = true, min_assertions = 1 }
patterns = { enabled = true }
isolation = { enabled = true }
performance = { enabled = true, slow_threshold_ms = 500, very_slow_threshold_ms = 2000 }
smells = { enabled = true }
```

### Skipping Tests

Use the `review_skip` marker to exclude specific tests from review:

```python
import pytest

@pytest.mark.review_skip
def test_intentionally_complex():
    # This test won't be analyzed
    ...
```

## Scoring (optional CI gate)

The score exists to gate a build, not to be a headline. **It is not printed unless you set `--review-min-score`** (or `min_score` in config): the findings are what you act on, and leading with a grade invites tuning the number instead of fixing the tests.

When a threshold is in force, the score is calculated using weighted categories:

| Category | Weight | Analyzers |
|----------|--------|-----------|
| Assertions | 30% | assertions |
| Clarity | 25% | smells |
| Isolation | 20% | isolation |
| Simplicity | 15% | patterns |
| Performance | 10% | performance |

The score is a **defect density**, so it does not change simply because a suite is large: a 1,000-test suite and a 10-test suite with the same proportion of defective tests score the same.

Within each category, severity penalties are what a single defective test forfeits:

- **Error**: 100 (the test forfeits all of its credit in that category)

- **Warning**: 35

- **Info**: 7

Each test's penalty saturates at 100, so one very bad test cannot consume the budget of tests that are fine. The category score is the mean of those per-test penalties across the whole suite, which means a category reaches 0 only when every test in the suite is defective.

Critical penalties are applied globally on top, scaled by the fraction of tests affected:

- **Missing assertions**: up to -70 points. This is not a chosen number -- it is exactly the score left standing once the assertions category is wiped out, so a suite in which *every* test verifies nothing scores 0.

- **Trivial assertions**: up to -25 points. Deliberately smaller, because `assertions.trivial` also fires on a test that contains `assert True` *alongside* real assertions: it marks dead weight rather than a worthless test.

So one empty test in a 100-test suite costs 0.7 points, while a suite of nothing but empty tests scores 0 (F).

### Grade Scale

| Grade | Score Range |
|-------|-------------|
| A | 90-100 |
| B | 80-89 |
| C | 70-79 |
| D | 60-69 |
| F | 0-59 |

## Issue Types

Every rule is meant to indicate an actual defect. There are 21 of them, and the list is short on purpose: a rule that fires on healthy code costs more trust than it earns.

### Errors (X)

Tests that are broken or verify nothing:

- `assertions.missing` - test has no assertions

- `assertions.trivial` - `assert True`, or comparing a value to itself

- `assertions.always_true` - asserting on a generator expression or lambda. The *object* is truthy, so the comparison inside it never runs

- `assertions.uncalled_assertion` - `assert mock.assert_called_once` -- referenced but never called, so the assertion always passes. (Ruff's `PGH005` catches the bare-statement form; this catches the one hiding inside an `assert`.)

- `assertions.mock_tautology` - the test asserts on a call to something it patched itself, so it verifies `unittest.mock` rather than any application code:

  ```python
  @mock.patch("pkg.svc.fetch")
  def test_fetch(mock_fetch):
      mock_fetch.return_value = 5
      assert pkg.svc.fetch() == 5      # asserts the mock returned what you set
  ```

  Patching a dependency and asserting on the code that *uses* it is the correct pattern and is not reported, nor is asserting on the mock object itself (`mock_fetch.assert_called_once()`), which is a legitimate wiring check.

  Note there is deliberately **no rule for "too many mocks"**. The right number depends entirely on how many collaborators the code has, and mocking every collaborator is a deliberate style. A count threshold there would be an opinion, not a defect.
- `smells.swallowed_assertion` - `except AssertionError/Exception/BaseException` means the test cannot fail

### Warnings (!)

Tests that leak state, cannot fail, or are needlessly fragile:

- `assertions.insufficient` - fewer assertions than `min_assertions` (only fires if you raise it above 1)

- `smells.early_return` - an *unconditional* `return`, leaving the assertions below it dead. A `return` that is the sole body of an `if` is a deliberate toggle and is not reported.

- `smells.try_except_in_test` - `try/except` *with handlers*, which can mask a failure. `try/finally` is not reported: it has no handlers and cannot mask anything.

- `smells.duplicate_assert` - the same assertion twice, usually a copy-paste bug

- `smells.vacuous_loop` - every assertion sits inside a `for` loop, so the test passes having verified nothing when the iterable is empty. Loops over a non-empty literal or `range(n)` are exempt, as is any test with an assertion outside the loop

- `smells.ignored_test` - skipped by decorator, or by an *unguarded* `pytest.skip(...)`, `pytest.xfail(...)`, `self.skipTest(...)` or `raise SkipTest(...)`. A skip guarded by an `if` (the platform-gate pattern) is not reported.

- `isolation.global_modification` - `global` mutation visible to later tests

- `isolation.class_attr_modification` - mutating shared class or module state

- `isolation.env_mutation` - writing `os.environ` without `monkeypatch`

- `isolation.process_mutation` - `os.chdir`, `sys.path`, `sys.argv`

- `isolation.bare_patch` - `patch()` with neither a context manager nor a decorator, so nothing guarantees cleanup

- `patterns.sleep_in_test` - `time.sleep()` makes tests slow and flaky

- `patterns.slow_call` - real network I/O (`requests`, `httpx`, `urllib`). Suspected *database* calls are reported at INFO instead, since they are matched by variable name.

- `patterns.subprocess_no_check` - `subprocess.run()` without `check=True` swallows failures

- `performance.very_slow` - runtime above `very_slow_threshold_ms`

- `leaks.env`, `leaks.cwd`, `leaks.sys_path` - **measured at runtime**: state the test changed and never restored. Compared *after teardown*, so `monkeypatch` and other restoring fixtures are not reported. This catches leaks caused inside a helper or a library call, which nothing in the test's own source reveals

### Info (i)

**Hidden by default** -- run with `--review-min-severity=info` (or set `min_severity = "info"` in `pyproject.toml`):

- `assertions.low_ratio` - lots of setup, almost nothing verified

- `patterns.hardcoded_path` - absolute path passed to a path-consuming call (`open`, `Path`, `os.*`, `shutil.*`, `glob.*`, `tempfile.*`)

- `patterns.os_system` - `os.system()` in a test

- `patterns.slow_call` - suspected database I/O (`cursor.execute()`, `session.query()`)

- `performance.slow` - runtime above `slow_threshold_ms`

## Relationship to ruff

pytest-review is meant to sit alongside ruff, not overlap it. If ruff can catch something, ruff should catch it -- it is faster and already in your toolchain.

Enable ruff's pytest rules:

```toml
[tool.ruff.lint]
select = ["E", "F", "B", "SIM", "PT"]
```

That covers what pytest-review deliberately does **not**:

| Concern | Covered by |
|---|---|
| Bare `except:` | ruff `E722` |
| `is` with a literal | ruff `F632` |
| Mutable default arguments | ruff `B006` |
| `print()` left in a test | ruff `T201` |
| `open()` without a context manager | ruff `SIM115` |
| `pytest.raises()` without `match=` | ruff `PT011` |
| Cyclomatic complexity | ruff `C901` |
| Fixture and parametrize style | ruff `PT001`-`PT030` |

Test naming conventions, magic numbers, assertion counts, and "eager" tests were removed outright: they are style opinions, they fired constantly on healthy code, and none of them indicated a defect.

## Performance

### Incremental Caching

Static analysis results are cached per file, keyed on the file's path (relative to the pytest root), a SHA-256 hash of its contents, and a hash of the active analyzer configuration. On subsequent runs, unchanged files are skipped entirely. The key also covers the plugin version, the resolved analyzer settings (so changing a rule's default threshold invalidates), and a hash of each analyzer module's source (so editing a rule invalidates the findings it emitted). The cache is stored in pytest's `.pytest_cache/` directory and is invalidated automatically when any of those change. Including the path in the key keeps files with byte-identical contents in separate cache entries.

Disable caching with `--review-no-cache`. Clear the cache with pytest's built-in `--cache-clear`.

### Parallel Analysis

For large test suites, static analysis can run in parallel across files using a `ProcessPoolExecutor`. By default (`--review-workers=0`), parallelism is auto-enabled when the suite has 200+ tests across 8+ files. Use `--review-workers=N` to set a specific worker count, or `--review-workers=1` to force sequential execution.

## Custom Analyzers

Third-party packages can register custom analyzers via the `pytest_review` entry point group. No changes to pytest-review are required.

### Creating an Analyzer

Subclass `StaticAnalyzer` (for AST-based analysis) or `DynamicAnalyzer` (for runtime analysis):

```python
# my_package/analyzer.py
from pytest_review.analyzers.base import (
    AnalyzerResult, Issue, Severity, StaticAnalyzer, TestItemInfo,
)

class MyAnalyzer(StaticAnalyzer):
    name = "my-analyzer"
    description = "Checks for my custom pattern"
    category = "clarity"  # scoring category (see below)

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        # Walk test.node (an ast.FunctionDef) and add issues
        result.add_issue(
            Issue(
                rule="my-analyzer.example",
                message="Example issue found",
                severity=Severity.WARNING,
                file_path=test.file_path,
                line=test.line,
                test_name=test.name,
                suggestion="How to fix it",
            )
        )
```

### Registering via Entry Points

In your package's `pyproject.toml`, declare the entry point:

```toml
[project.entry-points.pytest_review]
my-analyzer = "my_package.analyzer:MyAnalyzer"
```

Once the package is installed, pytest-review discovers the analyzer automatically when `--review` is used.

### Configuration

Users configure custom analyzers the same way as built-in ones:

```toml
[tool.pytest-review.analyzers.my-analyzer]
enabled = true
custom_option = 42
```

Options are accessible in the analyzer via `self.get_option("custom_option", default=0)`.

### Scoring Integration

Set the `category` class attribute to one of the 5 scoring categories so issues contribute to the quality score:

| Category | Weight |
|----------|--------|
| `assertions` | 30% |
| `clarity` | 25% |
| `isolation` | 20% |
| `simplicity` | 15% |
| `performance` | 10% |

Analyzers without a `category` are still reported but do not affect the score.

### Filtering

Custom analyzers work with `--review-only` and `--review-exclude` using their `name` attribute:

```bash
pytest --review --review-only=my-analyzer
pytest --review --review-exclude=my-analyzer
```

## Acknowledgments

- The smells analyzer is inspired by the [pytest-smell](https://github.com/maxpacs98/disertation) project from the dissertation "Detecting Test Smells in Python" by Maxim Pacsial.

- Test smell concepts are based on research by Van Deursen et al. ("Refactoring Test Code", 2001) and Meszaros ("xUnit Test Patterns", 2007).

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) for details.
