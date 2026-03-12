"""Analyzer for test performance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_review.analyzers.base import (
    AnalyzerResult,
    DynamicAnalyzer,
    Issue,
    Severity,
)

if TYPE_CHECKING:
    from pytest_review.config import ReviewConfig


class PerformanceAnalyzer(DynamicAnalyzer):
    """Analyzes test execution performance."""

    name = "performance"
    description = "Detects slow tests and performance issues"

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)
        typed = config.get_performance_config()
        self._slow_threshold_ms = typed.slow_threshold_ms
        self._very_slow_threshold_ms = typed.very_slow_threshold_ms
        self._test_durations: dict[str, float] = {}
        self._test_results: dict[str, AnalyzerResult] = {}

    def on_test_start(self, test_name: str) -> None:
        """Called when a test starts executing."""
        # Duration tracking is handled by the collector
        pass

    def on_test_end(self, test_name: str, passed: bool, duration: float) -> None:
        """Called when a test finishes executing."""
        duration_ms = duration * 1000
        self._test_durations[test_name] = duration_ms

        result = AnalyzerResult(analyzer_name=self.name)
        result.metadata["duration_ms"] = duration_ms

        if duration_ms >= self._very_slow_threshold_ms:
            result.add_issue(
                Issue(
                    rule="performance.very_slow",
                    message=f"Test is very slow: {duration_ms:.0f}ms "
                    f"(threshold: {self._very_slow_threshold_ms:.0f}ms)",
                    severity=Severity.WARNING,
                    test_name=test_name,
                    suggestion="Consider optimizing or mocking slow operations",
                )
            )
        elif duration_ms >= self._slow_threshold_ms:
            result.add_issue(
                Issue(
                    rule="performance.slow",
                    message=f"Test is slow: {duration_ms:.0f}ms "
                    f"(threshold: {self._slow_threshold_ms:.0f}ms)",
                    severity=Severity.INFO,
                    test_name=test_name,
                    suggestion="Consider if this test can be optimized",
                )
            )

        if result.issues:
            self._test_results[test_name] = result

    def get_results(self) -> list[AnalyzerResult]:
        """Get accumulated results after test run."""
        return list(self._test_results.values())

    def get_statistics(self) -> dict[str, float]:
        """Get performance statistics including median and P95."""
        if not self._test_durations:
            return {}

        durations = sorted(self._test_durations.values())
        n = len(durations)
        return {
            "count": float(n),
            "total_ms": sum(durations),
            "avg_ms": sum(durations) / n,
            "median_ms": (
                durations[n // 2] if n % 2 else (durations[n // 2 - 1] + durations[n // 2]) / 2
            ),
            "p95_ms": durations[int(n * 0.95)] if n >= 2 else durations[-1],
            "min_ms": durations[0],
            "max_ms": durations[-1],
            "slow_count": sum(1 for d in durations if d >= self._slow_threshold_ms),
            "very_slow_count": sum(1 for d in durations if d >= self._very_slow_threshold_ms),
        }
