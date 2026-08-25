"""Pytest configuration for tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

# Enable pytester fixture for plugin testing
pytest_plugins = ["pytester"]


@pytest.fixture  # type: ignore[untyped-decorator]
def sample_pyproject_config() -> dict[str, Any]:
    """Sample configuration dictionary."""
    return {
        "enabled": True,
        "strict": False,
        "min_score": 70,
        "analyzers": {
            "assertions": {"enabled": True, "min_assertions": 1},
            "smells": {"enabled": True, "max_assertions_without_message": 4},
            "patterns": {"enabled": False},
        },
        "ignore": {
            "paths": ["tests/legacy/*"],
            "rules": ["patterns.hardcoded_path"],
        },
    }


@pytest.fixture  # type: ignore[untyped-decorator]
def restore_environ() -> Iterator[None]:
    """Snapshot ``os.environ`` and put it back afterwards.

    For tests that deliberately execute leaky code -- running a leaky module
    through ``pytester``, which executes in-process by default. ``monkeypatch``
    cannot help here: it only undoes changes *it* made, not mutations made by
    the code under test.
    """
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)
