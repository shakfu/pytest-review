# pytest-review

A pytest plugin that reviews the quality of your tests.

[![PyPI version](https://badge.fury.io/py/pytest-review.svg)](https://badge.fury.io/py/pytest-review)
[![Python versions](https://img.shields.io/pypi/pyversions/pytest-review.svg)](https://pypi.org/project/pytest-review/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

pytest-review analyzes your test suite and provides actionable feedback on test quality. It detects common anti-patterns, missing assertions, overly complex tests, and more.

## Features

- **Static Analysis**: AST-based detection of test quality issues
- **Dynamic Analysis**: Runtime performance tracking
- **Multiple Output Formats**: Terminal, JSON, and HTML reports
- **Configurable**: Customize thresholds and enable/disable analyzers
- **Quality Scoring**: Get a letter grade (A-F) for your test suite
- **Incremental Caching**: Skip re-analysis of unchanged files across runs
- **Parallel Analysis**: Distribute static analysis across multiple processes
- **Plugin API**: Register custom analyzers via entry points

### Analyzers

| Analyzer | Description |
|----------|-------------|
| **assertions** | Detects empty tests, trivial assertions (`assert True`), tautologies |
| **naming** | Checks for descriptive test names, proper snake_case |
| **complexity** | Flags tests with too many statements, deep nesting, high cyclomatic complexity |
| **patterns** | Identifies anti-patterns: bare except, `time.sleep`, print statements |
| **isolation** | Detects global state modifications, class attribute mutations |
| **performance** | Tracks slow tests at runtime |
| **smells** | Detects test smells: assertion roulette, duplicate asserts, eager tests, magic numbers |

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
  [X] <assertions> tests/test_example.py:15 [test_empty] Test has no assertions
      Suggestion: Add at least one assertion to verify expected behavior
  [!] <complexity> tests/test_example.py:20 [test_complex] Test has cyclomatic complexity of 12
      Suggestion: Simplify test logic or split into multiple tests
----------------------------------- Summary ------------------------------------
  Tests analyzed: 25
  Errors: 2
  Warnings: 5
  Quality: NEEDS IMPROVEMENT

  Overall Score: 72.0/100 (C)
================================================================================
```

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
pytest --review --review-only=assertions,naming

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
naming = { enabled = true, min_length = 10 }
complexity = { enabled = true, max_statements = 20, max_depth = 3, max_complexity = 5 }
patterns = { enabled = true }
isolation = { enabled = true }
performance = { enabled = true, slow_threshold_ms = 500, very_slow_threshold_ms = 2000 }
smells = { enabled = true, max_assertions_without_message = 1, check_magic_numbers = true }
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

## Scoring System

The quality score is calculated using weighted categories:

| Category | Weight | Analyzers |
|----------|--------|-----------|
| Assertions | 30% | assertions |
| Clarity | 25% | naming, smells |
| Isolation | 20% | isolation |
| Simplicity | 15% | complexity, patterns |
| Performance | 10% | performance |

Severity penalties:
- **Error**: -15 points per issue
- **Warning**: -5 points per issue
- **Info**: -1 point per issue

Critical penalties (applied globally):
- Missing assertions: -20 points
- Trivial assertions: -10 points

### Grade Scale

| Grade | Score Range |
|-------|-------------|
| A | 90-100 |
| B | 80-89 |
| C | 70-79 |
| D | 60-69 |
| F | 0-59 |

## Issue Types

### Errors (X)

Critical issues that indicate likely bugs or useless tests:

- `assertions.missing` - Test has no assertions
- `assertions.trivial` - Trivial assertion like `assert True`
- `assertions.tautology` - Comparing value to itself
- `smells.swallowed_assertion` - `except AssertionError/Exception/BaseException` silently swallows assertion failures

### Warnings (!)

Issues that may indicate problems:

- `naming.non_descriptive` - Generic names like `test_foo`
- `complexity.too_many_statements` - Test too long
- `complexity.too_deep` - Excessive nesting
- `complexity.too_complex` - High cyclomatic complexity
- `patterns.bare_except` - Catches all exceptions
- `patterns.sleep_in_test` - Uses `time.sleep()`
- `isolation.global_modification` - Modifies global state
- `isolation.process_mutation` - Mutates process-wide state (`os.chdir`, `sys.path`, `sys.argv`)
- `smells.assertion_roulette` - Multiple assertions without messages
- `smells.duplicate_assert` - Duplicate assertion statements
- `smells.ignored_test` - Test is skipped via decorator, `pytest.skip(...)`, `pytest.xfail(...)`, `self.skipTest(...)`, or `raise SkipTest(...)`
- `smells.early_return` - `return` in a test body, bypassing subsequent assertions

### Info (i)

Suggestions for improvement. **Hidden by default** -- run with `--review-min-severity=info` (or set `min_severity = "info"` in `pyproject.toml`) to see them:

- `naming.too_short` - Name could be more descriptive
- `patterns.print_statement` - Debug print left in test
- `performance.slow_test` - Test runs slowly
- `smells.magic_number` - Literal number in assertion
- `smells.eager_test` - Test verifies multiple methods
- `assertions.low_value` - Weak assertion (`isinstance`, `is not None`)
- `assertions.yoda_condition` - Reversed comparison (`assert 42 == x`)
- `assertions.raises_without_match` - `pytest.raises()` without `match=`

## Performance

### Incremental Caching

Static analysis results are cached per file, keyed on the file's path (relative to the pytest root), a SHA-256 hash of its contents, and a hash of the active analyzer configuration. On subsequent runs, unchanged files are skipped entirely. The cache is stored in pytest's `.pytest_cache/` directory and is invalidated automatically when file contents or config change. Including the path in the key keeps files with byte-identical contents in separate cache entries.

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
