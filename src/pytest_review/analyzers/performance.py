"""Analyzer for test performance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_review.analyzers.base import (
    AnalyzerResult,
    DynamicAnalyzer,
    Issue,
    Severity,
    TestItemInfo,
)

if TYPE_CHECKING:
    from pytest_review.config import ReviewConfig


class PerformanceAnalyzer(DynamicAnalyzer):
    """Analyzes test execution performance."""

    name = "performance"
    description = "Detects slow tests and performance issues"

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)
        self._slow_threshold_ms = float(self.get_option("slow_threshold_ms", 500) or 500)
        self._very_slow_threshold_ms = float(
            self.get_option("very_slow_threshold_ms", 2000) or 2000
        )
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
        """Get performance statistics."""
        if not self._test_durations:
            return {}

        durations = list(self._test_durations.values())
        return {
            "total_ms": sum(durations),
            "avg_ms": sum(durations) / len(durations),
            "min_ms": min(durations),
            "max_ms": max(durations),
            "slow_count": sum(
                1 for d in durations if d >= self._slow_threshold_ms
            ),
            "very_slow_count": sum(
                1 for d in durations if d >= self._very_slow_threshold_ms
            ),
        }
