# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
