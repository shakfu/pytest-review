"""Pytest configuration for tests."""

from __future__ import annotations

import pytest

# Enable pytester fixture for plugin testing
pytest_plugins = ["pytester"]


@pytest.fixture
def sample_pyproject_config() -> dict:
    """Sample configuration dictionary."""
    return {
        "enabled": True,
        "strict": False,
        "min_score": 70,
        "analyzers": {
            "assertions": {"enabled": True, "min_assertions": 1},
            "naming": {"enabled": True, "min_length": 10},
            "complexity": {"enabled": False},
        },
        "ignore": {
            "paths": ["tests/legacy/*"],
            "rules": ["naming.docstring"],
        },
    }
