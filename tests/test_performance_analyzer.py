"""Tests for the performance analyzer."""

from __future__ import annotations

import pytest

from pytest_review.analyzers.base import Severity
from pytest_review.analyzers.performance import PerformanceAnalyzer
from pytest_review.config import ReviewConfig


class TestPerformanceAnalyzer:
    def test_no_issues_for_fast_test(self) -> None:
        config = ReviewConfig()
        analyzer = PerformanceAnalyzer(config)

        analyzer.on_test_start("test_fast")
        analyzer.on_test_end("test_fast", passed=True, duration=0.001)  # 1ms

        results = analyzer.get_results()
        assert len(results) == 0

    def test_detects_slow_test(self) -> None:
        config = ReviewConfig.from_dict(
            {"analyzers": {"performance": {"enabled": True, "slow_threshold_ms": 100}}}
        )
        analyzer = PerformanceAnalyzer(config)

        analyzer.on_test_start("test_slow")
        analyzer.on_test_end("test_slow", passed=True, duration=0.2)  # 200ms

        results = analyzer.get_results()
        assert len(results) == 1
        assert results[0].issues[0].rule == "performance.slow"
        assert results[0].issues[0].severity == Severity.INFO

    def test_detects_very_slow_test(self) -> None:
        config = ReviewConfig.from_dict(
            {
                "analyzers": {
                    "performance": {
                        "enabled": True,
                        "slow_threshold_ms": 100,
                        "very_slow_threshold_ms": 500,
                    }
                }
            }
        )
        analyzer = PerformanceAnalyzer(config)

        analyzer.on_test_start("test_very_slow")
        analyzer.on_test_end("test_very_slow", passed=True, duration=1.0)  # 1000ms

        results = analyzer.get_results()
        assert len(results) == 1
        assert results[0].issues[0].rule == "performance.very_slow"
        assert results[0].issues[0].severity == Severity.WARNING

    def test_tracks_multiple_tests(self) -> None:
        config = ReviewConfig.from_dict(
            {"analyzers": {"performance": {"enabled": True, "slow_threshold_ms": 100}}}
        )
        analyzer = PerformanceAnalyzer(config)

        # Fast test
        analyzer.on_test_start("test_fast")
        analyzer.on_test_end("test_fast", passed=True, duration=0.01)

        # Slow test
        analyzer.on_test_start("test_slow")
        analyzer.on_test_end("test_slow", passed=True, duration=0.2)

        results = analyzer.get_results()
        assert len(results) == 1  # Only the slow test

    def test_stores_duration_in_metadata(self) -> None:
        config = ReviewConfig.from_dict(
            {"analyzers": {"performance": {"enabled": True, "slow_threshold_ms": 10}}}
        )
        analyzer = PerformanceAnalyzer(config)

        analyzer.on_test_start("test_example")
        analyzer.on_test_end("test_example", passed=True, duration=0.05)  # 50ms

        results = analyzer.get_results()
        assert len(results) == 1
        assert "duration_ms" in results[0].metadata
        assert 49 < results[0].metadata["duration_ms"] < 51

    def test_statistics(self) -> None:
        config = ReviewConfig()
        analyzer = PerformanceAnalyzer(config)

        analyzer.on_test_start("test_1")
        analyzer.on_test_end("test_1", passed=True, duration=0.1)  # 100ms

        analyzer.on_test_start("test_2")
        analyzer.on_test_end("test_2", passed=True, duration=0.2)  # 200ms

        analyzer.on_test_start("test_3")
        analyzer.on_test_end("test_3", passed=True, duration=0.3)  # 300ms

        stats = analyzer.get_statistics()
        assert stats["count"] == 3
        assert stats["min_ms"] == pytest.approx(100, rel=0.1)
        assert stats["max_ms"] == pytest.approx(300, rel=0.1)
        assert stats["avg_ms"] == pytest.approx(200, rel=0.1)
        assert stats["median_ms"] == pytest.approx(200, rel=0.1)
        assert stats["p95_ms"] == pytest.approx(300, rel=0.1)
        assert stats["total_ms"] == pytest.approx(600, rel=0.1)

    def test_statistics_even_count_median(self) -> None:
        config = ReviewConfig()
        analyzer = PerformanceAnalyzer(config)

        for i, dur in enumerate([0.1, 0.2, 0.3, 0.4]):
            analyzer.on_test_start(f"test_{i}")
            analyzer.on_test_end(f"test_{i}", passed=True, duration=dur)

        stats = analyzer.get_statistics()
        # Median of [100, 200, 300, 400] = (200+300)/2 = 250
        assert stats["median_ms"] == pytest.approx(250, rel=0.1)

    def test_statistics_empty(self) -> None:
        config = ReviewConfig()
        analyzer = PerformanceAnalyzer(config)
        assert analyzer.get_statistics() == {}


class TestPerformanceAnalyzerIntegration:
    """Integration tests using pytester."""

    def test_detects_slow_test_in_real_run(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            import time

            def test_intentionally_slow_for_performance_check():
                time.sleep(0.15)  # 150ms
                assert True
        """)
        result = pytester.runpytest(
            "--review",
            "--review-only=performance",
        )
        result.assert_outcomes(passed=1)
        # With default 500ms threshold, 150ms should be fine
        assert "performance.slow" not in result.stdout.str()

    def test_aggregate_stats_shown_in_terminal(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_fast_operation_for_stats_check():
                assert 1 + 1 == 2
        """)
        result = pytester.runpytest("--review", "--review-only=performance")
        result.assert_outcomes(passed=1)
        output = result.stdout.str()
        assert "Performance" in output
        assert "Mean:" in output
        assert "Median:" in output
        assert "P95:" in output

    def test_detects_slow_test_with_low_threshold(self, pytester: pytest.Pytester) -> None:
        # Create a pyproject.toml with low threshold
        pytester.makefile(
            ".toml",
            pyproject="""
[tool.pytest-review.analyzers]
performance = { enabled = true, slow_threshold_ms = 50 }
""",
        )
        pytester.makepyfile("""
            import time

            def test_slightly_slow_operation_detected():
                time.sleep(0.1)  # 100ms, above 50ms threshold
                assert True
        """)
        result = pytester.runpytest(
            "--review",
            "--review-only=performance",
        )
        result.assert_outcomes(passed=1)
        assert "slow" in result.stdout.str().lower()
