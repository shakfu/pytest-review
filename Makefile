.PHONY: install dev test lint typecheck qa clean all review review-html review-json \
       example example-html example-json example-only example-strict example-min-score \
       example-verify build publish publish-test check

all: install test

install:
	@uv sync --reinstall-package pytest_review

dev:
	@uv pip install -e .

test:
	@uv run pytest

test-cov:
	@uv run pytest --cov=pytest_review --cov-report=term-missing

review:
	@uv run pytest --review

review-html:
	@uv run pytest --review --review-format=html --review-output=pytest-review-report.html
	@echo "HTML report generated: pytest-review-report.html"

review-json:
	@uv run pytest --review --review-format=json --review-output=pytest-review-report.json
	@echo "JSON report generated: pytest-review-report.json"

# Example targets using bad_tests.py
example:
	@uv run pytest examples/bad_tests.py --review

example-html:
	@uv run pytest examples/bad_tests.py --review --review-format=html --review-output=examples/report.html
	@echo "HTML report generated: examples/report.html"

example-json:
	@uv run pytest examples/bad_tests.py --review --review-format=json --review-output=examples/report.json
	@echo "JSON report generated: examples/report.json"

example-only:
	@uv run pytest examples/bad_tests.py --review --review-only=assertions,naming

example-strict:
	@uv run pytest examples/bad_tests.py --review --review-strict || true

example-min-score:
	@uv run pytest examples/bad_tests.py --review --review-min-score=70

# Verify all analyzers detect expected issues
example-verify:
	@echo "Verifying all analyzers detect expected issues..."
	@uv run pytest examples/bad_tests.py --review --review-min-severity=info --review-format=json --review-output=/tmp/review.json -q
	@uv run python -c "\
import json; \
data = json.load(open('/tmp/review.json')); \
rules = {i['rule'] for i in data['issues']}; \
expected = { \
    'assertions.mock_tautology', \
    'smells.vacuous_loop', \
    'assertions.uncalled_assertion', \
    'assertions.always_true', \
    'assertions.low_ratio', \
    'assertions.missing', \
    'assertions.trivial', \
    'isolation.bare_patch', \
    'isolation.class_attr_modification', \
    'isolation.env_mutation', \
    'isolation.global_modification', \
    'isolation.process_mutation', \
    'patterns.hardcoded_path', \
    'patterns.os_system', \
    'patterns.sleep_in_test', \
    'patterns.slow_call', \
    'patterns.subprocess_no_check', \
    'smells.duplicate_assert', \
    'smells.early_return', \
    'smells.ignored_test', \
    'smells.swallowed_assertion', \
    'smells.try_except_in_test', \
}; \
missing = expected - rules; \
extra = rules - expected - {'naming.unclear_abbreviation'}; \
print(f'Found {len(rules)} unique rules'); \
print(f'Expected {len(expected)} rules'); \
[print(f'  MISSING: {r}') for r in sorted(missing)]; \
[print(f'  (extra): {r}') for r in sorted(extra)]; \
exit(1 if missing else 0) \
"
	@echo "All expected rules detected!"

lint:
	@uv run ruff check --fix src/ tests/

format:
	@uv run ruff format src/ tests/

typecheck:
	@uv run mypy src/

qa: test typecheck lint format

clean:
	@rm -rf build/
	@rm -rf dist/
	@rm -rf *.egg-info/
	@rm -rf src/*.egg-info/
	@rm -rf .pytest_cache/
	@rm -rf .mypy_cache/
	@rm -rf .ruff_cache/
	@rm -rf htmlcov/
	@rm -rf .coverage
	@rm -f pytest-review-report.html
	@rm -f pytest-review-report.json
	@rm -f examples/report.html
	@rm -f examples/report.json
	@rm -f examples/bad_tests_report.html
	@find . -type d -name __pycache__ -exec rm -rf {} +

# Build and publish
build: clean
	@uv build
	@echo "Build complete. Distribution files in dist/"

check: build
	@uv run twine check dist/*

publish-test: check
	@uv run twine upload --repository testpypi dist/*
	@echo "Published to TestPyPI"

publish: check
	@uv run twine upload dist/*
	@echo "Published to PyPI"
