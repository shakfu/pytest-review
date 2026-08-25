"""Tests for typed analyzer configuration."""

from __future__ import annotations

from pytest_review.config import (
    AssertionsConfig,
    IsolationConfig,
    PatternsConfig,
    PerformanceConfig,
    ReviewConfig,
    SmellsConfig,
)


class TestTypedConfigDefaults:
    def test_assertions_config_defaults(self) -> None:
        config = ReviewConfig()
        typed = config.get_assertions_config()
        assert isinstance(typed, AssertionsConfig)
        assert typed.enabled is True
        assert typed.min_assertions == 1



    def test_patterns_config_defaults(self) -> None:
        config = ReviewConfig()
        typed = config.get_patterns_config()
        assert isinstance(typed, PatternsConfig)
        assert typed.enabled is True

    def test_isolation_config_defaults(self) -> None:
        config = ReviewConfig()
        typed = config.get_isolation_config()
        assert isinstance(typed, IsolationConfig)
        assert typed.enabled is True

    def test_performance_config_defaults(self) -> None:
        config = ReviewConfig()
        typed = config.get_performance_config()
        assert isinstance(typed, PerformanceConfig)
        assert typed.enabled is True
        assert typed.slow_threshold_ms == 500.0
        assert typed.very_slow_threshold_ms == 2000.0

    def test_smells_config_defaults(self) -> None:
        config = ReviewConfig()
        typed = config.get_smells_config()
        assert isinstance(typed, SmellsConfig)
        assert typed.enabled is True
        assert typed.max_assertions_without_message == 4
        assert typed.check_magic_numbers is True
        assert typed.check_eager_test is True


class TestTypedConfigFromDict:
    def test_assertions_config_from_dict(self) -> None:
        config = ReviewConfig.from_dict(
            {"analyzers": {"assertions": {"enabled": True, "min_assertions": 3}}}
        )
        typed = config.get_assertions_config()
        assert typed.min_assertions == 3



    def test_performance_config_from_dict(self) -> None:
        config = ReviewConfig.from_dict(
            {
                "analyzers": {
                    "performance": {
                        "slow_threshold_ms": 250,
                        "very_slow_threshold_ms": 1000,
                    }
                }
            }
        )
        typed = config.get_performance_config()
        assert typed.slow_threshold_ms == 250.0
        assert typed.very_slow_threshold_ms == 1000.0

    def test_smells_config_from_dict(self) -> None:
        config = ReviewConfig.from_dict(
            {
                "analyzers": {
                    "smells": {
                        "max_assertions_without_message": 3,
                        "check_magic_numbers": False,
                        "check_eager_test": False,
                    }
                }
            }
        )
        typed = config.get_smells_config()
        assert typed.max_assertions_without_message == 3
        assert typed.check_magic_numbers is False
        assert typed.check_eager_test is False

    def test_disabled_analyzer_config(self) -> None:
        config = ReviewConfig.from_dict(
            {"analyzers": {"smells": {"enabled": False, "max_assertions_without_message": 9}}}
        )
        typed = config.get_smells_config()
        assert typed.enabled is False
        assert typed.max_assertions_without_message == 9
