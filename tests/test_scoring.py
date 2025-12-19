"""Tests for the scoring system."""

from __future__ import annotations

import pytest

from pytest_review.analyzers.base import AnalyzerResult, Issue, Severity
from pytest_review.scoring import CategoryScore, ScoreBreakdown, ScoringEngine


class TestScoreBreakdown:
    def test_to_dict_returns_all_fields(self) -> None:
        breakdown = ScoreBreakdown(
            total_score=85.0,
            grade="B",
            total_tests=10,
            total_issues=5,
            error_count=1,
            warning_count=3,
            info_count=1,
        )

        result = breakdown.to_dict()

        assert result["total_score"] == 85.0
        assert result["grade"] == "B"
        assert result["total_tests"] == 10
        assert result["total_issues"] == 5
        assert result["error_count"] == 1
        assert result["warning_count"] == 3
        assert result["info_count"] == 1

    def test_to_dict_includes_categories(self) -> None:
        category = CategoryScore(
            name="assertions",
            weight=0.3,
            raw_score=80.0,
            weighted_score=24.0,
            issue_count=2,
        )
        breakdown = ScoreBreakdown(categories=[category])

        result = breakdown.to_dict()

        assert len(result["categories"]) == 1
        assert result["categories"][0]["name"] == "assertions"
        assert result["categories"][0]["weight"] == 0.3
        assert result["categories"][0]["raw_score"] == 80.0

    def test_to_dict_includes_penalties(self) -> None:
        breakdown = ScoreBreakdown(
            penalties=[("assertions.missing", 20.0), ("assertions.trivial", 10.0)]
        )

        result = breakdown.to_dict()

        assert len(result["penalties"]) == 2
        assert result["penalties"][0]["reason"] == "assertions.missing"
        assert result["penalties"][0]["amount"] == 20.0


class TestScoringEngine:
    def test_perfect_score_with_no_issues(self) -> None:
        engine = ScoringEngine()
        results: list[AnalyzerResult] = []

        breakdown = engine.calculate_score(results, total_tests=10)

        assert breakdown.total_score == 100.0
        assert breakdown.grade == "A"
        assert breakdown.total_issues == 0

    def test_score_with_zero_tests(self) -> None:
        engine = ScoringEngine()
        results: list[AnalyzerResult] = []

        breakdown = engine.calculate_score(results, total_tests=0)

        assert breakdown.total_score == 100.0
        assert breakdown.grade == "A"

    def test_counts_issues_by_severity(self) -> None:
        engine = ScoringEngine()
        results = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[
                    Issue("r1", "msg1", Severity.ERROR),
                    Issue("r2", "msg2", Severity.ERROR),
                    Issue("r3", "msg3", Severity.WARNING),
                    Issue("r4", "msg4", Severity.INFO),
                ],
            )
        ]

        breakdown = engine.calculate_score(results, total_tests=5)

        assert breakdown.error_count == 2
        assert breakdown.warning_count == 1
        assert breakdown.info_count == 1
        assert breakdown.total_issues == 4

    def test_errors_reduce_score_more_than_warnings(self) -> None:
        engine = ScoringEngine()

        error_results = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[Issue("r1", "error", Severity.ERROR)],
            )
        ]
        warning_results = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[Issue("r1", "warning", Severity.WARNING)],
            )
        ]

        error_breakdown = engine.calculate_score(error_results, total_tests=1)
        warning_breakdown = engine.calculate_score(warning_results, total_tests=1)

        # Error should cause bigger penalty than warning
        assert error_breakdown.total_score < warning_breakdown.total_score

    def test_critical_penalties_applied(self) -> None:
        engine = ScoringEngine()

        # Test without critical penalty
        normal_results = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[Issue("assertions.weak", "weak assertion", Severity.ERROR)],
            )
        ]
        normal_breakdown = engine.calculate_score(normal_results, total_tests=1)

        # Test with critical penalty (missing assertions)
        critical_results = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[Issue("assertions.missing", "no assertions", Severity.ERROR)],
            )
        ]
        critical_breakdown = engine.calculate_score(critical_results, total_tests=1)

        # Critical penalty should cause larger score reduction
        assert critical_breakdown.total_score < normal_breakdown.total_score
        assert len(critical_breakdown.penalties) == 1
        assert critical_breakdown.penalties[0][0] == "assertions.missing"

    def test_score_to_grade_boundaries(self) -> None:
        engine = ScoringEngine()

        assert engine._score_to_grade(100) == "A"
        assert engine._score_to_grade(90) == "A"
        assert engine._score_to_grade(89) == "B"
        assert engine._score_to_grade(80) == "B"
        assert engine._score_to_grade(79) == "C"
        assert engine._score_to_grade(70) == "C"
        assert engine._score_to_grade(69) == "D"
        assert engine._score_to_grade(60) == "D"
        assert engine._score_to_grade(59) == "F"
        assert engine._score_to_grade(0) == "F"

    def test_score_never_goes_below_zero(self) -> None:
        engine = ScoringEngine()

        # Create many severe issues
        results = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[
                    Issue("assertions.missing", "empty test", Severity.ERROR)
                    for _ in range(50)
                ],
            )
        ]

        breakdown = engine.calculate_score(results, total_tests=1)

        assert breakdown.total_score >= 0.0

    def test_score_never_exceeds_100(self) -> None:
        engine = ScoringEngine()
        results: list[AnalyzerResult] = []

        breakdown = engine.calculate_score(results, total_tests=100)

        assert breakdown.total_score <= 100.0

    def test_categories_are_weighted(self) -> None:
        engine = ScoringEngine()

        # Verify category weights sum to 1.0
        total_weight = sum(engine.CATEGORY_WEIGHTS.values())
        assert abs(total_weight - 1.0) < 0.001

        # Verify assertions has highest weight
        assert engine.CATEGORY_WEIGHTS["assertions"] == 0.30
        assert engine.CATEGORY_WEIGHTS["assertions"] > engine.CATEGORY_WEIGHTS["clarity"]

    def test_get_simple_score_returns_float(self) -> None:
        engine = ScoringEngine()
        results: list[AnalyzerResult] = []

        score = engine.get_simple_score(results, total_tests=5)

        assert isinstance(score, float)
        assert score == 100.0

    def test_multiple_analyzers_contribute_to_score(self) -> None:
        engine = ScoringEngine()
        results = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[Issue("assertions.missing", "msg", Severity.ERROR)],
            ),
            AnalyzerResult(
                analyzer_name="naming",
                issues=[Issue("naming.short", "msg", Severity.WARNING)],
            ),
            AnalyzerResult(
                analyzer_name="complexity",
                issues=[Issue("complexity.high", "msg", Severity.INFO)],
            ),
        ]

        breakdown = engine.calculate_score(results, total_tests=3)

        # Score should be reduced from 100
        assert breakdown.total_score < 100.0
        # Should have issues from all analyzers
        assert breakdown.total_issues == 3

    def test_breakdown_includes_all_categories(self) -> None:
        engine = ScoringEngine()
        results: list[AnalyzerResult] = []

        breakdown = engine.calculate_score(results, total_tests=1)

        category_names = {c.name for c in breakdown.categories}
        expected = {"assertions", "clarity", "isolation", "simplicity", "performance"}
        assert category_names == expected

    def test_category_score_calculation(self) -> None:
        engine = ScoringEngine()
        results = [
            AnalyzerResult(
                analyzer_name="assertions",
                issues=[
                    Issue("assertions.weak", "msg1", Severity.WARNING),
                    Issue("assertions.weak", "msg2", Severity.WARNING),
                ],
            )
        ]

        breakdown = engine.calculate_score(results, total_tests=2)

        # Find assertions category
        assertions_cat = next(c for c in breakdown.categories if c.name == "assertions")
        assert assertions_cat.issue_count == 2
        assert assertions_cat.weight == 0.30
        assert assertions_cat.raw_score < 100.0


class TestCategoryScore:
    def test_default_values(self) -> None:
        category = CategoryScore(name="test", weight=0.5)

        assert category.name == "test"
        assert category.weight == 0.5
        assert category.raw_score == 100.0
        assert category.weighted_score == 0.0
        assert category.issue_count == 0
        assert category.details == {}

    def test_weighted_score_calculation(self) -> None:
        category = CategoryScore(
            name="assertions",
            weight=0.30,
            raw_score=80.0,
            weighted_score=24.0,  # 80 * 0.30
        )

        assert category.weighted_score == 24.0
