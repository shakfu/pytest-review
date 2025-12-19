"""Tests for configuration handling."""

from __future__ import annotations

import tempfile
from pathlib import Path

from pytest_review.config import AnalyzerConfig, ReviewConfig


class TestAnalyzerConfig:
    def test_default_values(self) -> None:
        config = AnalyzerConfig()
        assert config.enabled is True
        assert config.options == {}

    def test_custom_values(self) -> None:
        config = AnalyzerConfig(enabled=False, options={"threshold": 10})
        assert config.enabled is False
        assert config.options["threshold"] == 10


class TestReviewConfig:
    def test_default_values(self) -> None:
        config = ReviewConfig()
        assert config.enabled is True
        assert config.strict is False
        assert config.min_score == 0
        assert config.analyzers == {}
        assert config.ignore_paths == []
        assert config.ignore_rules == []

    def test_from_dict(self, sample_pyproject_config: dict) -> None:
        config = ReviewConfig.from_dict(sample_pyproject_config)

        assert config.enabled is True
        assert config.strict is False
        assert config.min_score == 70
        assert "assertions" in config.analyzers
        assert "naming" in config.analyzers
        assert "complexity" in config.analyzers
        assert config.ignore_paths == ["tests/legacy/*"]
        assert config.ignore_rules == ["naming.docstring"]

    def test_get_analyzer_config_existing(self, sample_pyproject_config: dict) -> None:
        config = ReviewConfig.from_dict(sample_pyproject_config)
        analyzer_config = config.get_analyzer_config("assertions")

        assert analyzer_config.enabled is True
        assert analyzer_config.options.get("min_assertions") == 1

    def test_get_analyzer_config_missing(self) -> None:
        config = ReviewConfig()
        analyzer_config = config.get_analyzer_config("nonexistent")

        assert analyzer_config.enabled is True  # default
        assert analyzer_config.options == {}

    def test_is_analyzer_enabled(self, sample_pyproject_config: dict) -> None:
        config = ReviewConfig.from_dict(sample_pyproject_config)

        assert config.is_analyzer_enabled("assertions") is True
        assert config.is_analyzer_enabled("complexity") is False
        assert config.is_analyzer_enabled("nonexistent") is True  # default

    def test_get_analyzer_option(self, sample_pyproject_config: dict) -> None:
        config = ReviewConfig.from_dict(sample_pyproject_config)

        assert config.get_analyzer_option("assertions", "min_assertions") == 1
        assert config.get_analyzer_option("assertions", "nonexistent", 42) == 42
        assert config.get_analyzer_option("naming", "min_length") == 10

    def test_from_pyproject_missing_file(self, tmp_path: Path) -> None:
        config = ReviewConfig.from_pyproject(tmp_path / "nonexistent.toml")
        assert config.enabled is True  # defaults

    def test_from_pyproject_valid_file(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[tool.pytest-review]
enabled = true
strict = true
min_score = 80

[tool.pytest-review.analyzers]
assertions = { enabled = true, min_assertions = 2 }
""")
        config = ReviewConfig.from_pyproject(pyproject)

        assert config.enabled is True
        assert config.strict is True
        assert config.min_score == 80
        assert config.get_analyzer_option("assertions", "min_assertions") == 2
