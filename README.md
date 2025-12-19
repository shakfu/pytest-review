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
  [X] tests/test_example.py:15 [test_empty] Test has no assertions
      Suggestion: Add at least one assertion to verify expected behavior
  [!] tests/test_example.py:20 [test_complex] Test has cyclomatic complexity of 12
      Suggestion: Simplify test logic or split into multiple tests
----------------------------------- Summary ------------------------------------
  Tests analyzed: 25
  Errors: 2
  Warnings: 5
  Info: 3
  Quality: NEEDS IMPROVEMENT

  Overall Score: 72.0/100 (C)
================================================================================
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `--review` | Enable test quality review |
| `--review-format` | Output format: `terminal` (default), `json`, `html` |
| `--review-output` | Write report to file |
| `--review-strict` | Fail if quality errors are found |
| `--review-min-score` | Minimum required score (0-100) |
| `--review-only` | Comma-separated list of analyzers to run |

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
```

## Configuration

Configure pytest-review in your `pyproject.toml`:

```toml
[tool.pytest-review]
enabled = true
strict = false
min_score = 0

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

### Warnings (!)

Issues that may indicate problems:

- `naming.non_descriptive` - Generic names like `test_foo`
- `complexity.too_many_statements` - Test too long
- `complexity.too_deep` - Excessive nesting
- `complexity.too_complex` - High cyclomatic complexity
- `patterns.bare_except` - Catches all exceptions
- `patterns.sleep_in_test` - Uses `time.sleep()`
- `isolation.global_modification` - Modifies global state
- `smells.assertion_roulette` - Multiple assertions without messages
- `smells.duplicate_assert` - Duplicate assertion statements
- `smells.ignored_test` - Test is skipped with decorator

### Info (i)

Suggestions for improvement:

- `naming.too_short` - Name could be more descriptive
- `patterns.print_statement` - Debug print left in test
- `performance.slow_test` - Test runs slowly
- `smells.magic_number` - Literal number in assertion
- `smells.eager_test` - Test verifies multiple methods

## Acknowledgments

- The smells analyzer is inspired by the [pytest-smell](https://github.com/maxpacs98/disertation) project from the dissertation "Detecting Test Smells in Python" by Maxim Pacsial. 
- Test smell concepts are based on research by Van Deursen et al. ("Refactoring Test Code", 2001) and Meszaros ("xUnit Test Patterns", 2007).

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) for details.
