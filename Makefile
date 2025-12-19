.PHONY: install dev test lint type-check clean all review review-html review-json

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

lint:
	@uv run ruff check src/ tests/
	@uv run ruff format --check src/ tests/

format:
	@uv run ruff check --fix src/ tests/
	@uv run ruff format src/ tests/

type-check:
	@uv run mypy src/

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
	@find . -type d -name __pycache__ -exec rm -rf {} +
