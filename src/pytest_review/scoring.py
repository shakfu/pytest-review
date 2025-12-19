"""Quality scoring system for pytest-review."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pytest_review.analyzers.base import AnalyzerResult, Severity


@dataclass
class CategoryScore:
    """Score for a single category."""

    name: str
    weight: float
    raw_score: float = 100.0
    weighted_score: float = 0.0
    issue_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreBreakdown:
    """Complete score breakdown."""

    total_score: float = 100.0
    grade: str = "A"
    categories: list[CategoryScore] = field(default_factory=list)
    penalties: list[tuple[str, float]] = field(default_factory=list)
    total_tests: int = 0
    total_issues: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_score": self.total_score,
            "grade": self.grade,
            "total_tests": self.total_tests,
            "total_issues": self.total_issues,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "categories": [
                {
                    "name": c.name,
                    "weight": c.weight,
                    "raw_score": c.raw_score,
                    "weighted_score": c.weighted_score,
                    "issue_count": c.issue_count,
                }
                for c in self.categories
            ],
            "penalties": [{"reason": p[0], "amount": p[1]} for p in self.penalties],
        }


class ScoringEngine:
    """Calculates quality scores from analysis results."""

    # Category weights (must sum to 1.0)
    CATEGORY_WEIGHTS = {
        "assertions": 0.30,  # 30% - Most important
        "clarity": 0.25,  # 25% - Naming, documentation
        "isolation": 0.20,  # 20% - State management
        "simplicity": 0.15,  # 15% - Complexity
        "performance": 0.10,  # 10% - Execution time
    }

    # Analyzer to category mapping
    ANALYZER_CATEGORIES = {
        "assertions": "assertions",
        "naming": "clarity",
        "isolation": "isolation",
        "isolation_runtime": "isolation",
        "complexity": "simplicity",
        "patterns": "simplicity",
        "performance": "performance",
        "smells": "clarity",
    }

    # Severity penalties per issue
    SEVERITY_PENALTIES = {
        Severity.ERROR: 15.0,
        Severity.WARNING: 5.0,
        Severity.INFO: 1.0,
    }

    # Critical issue penalties (applied globally)
    CRITICAL_PENALTIES = {
        "assertions.missing": 20.0,  # Empty test
        "assertions.trivial": 10.0,  # assert True
    }

    def __init__(self) -> None:
        self._results: list[AnalyzerResult] = []
        self._total_tests: int = 0

    def calculate_score(
        self,
        results: list[AnalyzerResult],
        total_tests: int,
    ) -> ScoreBreakdown:
        """Calculate the overall quality score."""
        self._results = results
        self._total_tests = total_tests

        breakdown = ScoreBreakdown(total_tests=total_tests)

        if total_tests == 0:
            breakdown.grade = "A"
            return breakdown

        # Count issues by severity
        for result in results:
            for issue in result.issues:
                breakdown.total_issues += 1
                if issue.severity == Severity.ERROR:
                    breakdown.error_count += 1
                elif issue.severity == Severity.WARNING:
                    breakdown.warning_count += 1
                else:
                    breakdown.info_count += 1

        # Calculate category scores
        category_issues = self._group_by_category()
        for category_name, weight in self.CATEGORY_WEIGHTS.items():
            issues = category_issues.get(category_name, [])
            category_score = self._calculate_category_score(
                category_name, weight, issues, total_tests
            )
            breakdown.categories.append(category_score)

        # Apply critical penalties
        for result in results:
            for issue in result.issues:
                if issue.rule in self.CRITICAL_PENALTIES:
                    penalty = self.CRITICAL_PENALTIES[issue.rule]
                    breakdown.penalties.append((issue.rule, penalty))

        # Calculate total score
        weighted_sum = sum(c.weighted_score for c in breakdown.categories)
        total_penalty = sum(p[1] for p in breakdown.penalties)

        breakdown.total_score = max(0.0, min(100.0, weighted_sum - total_penalty))
        breakdown.grade = self._score_to_grade(breakdown.total_score)

        return breakdown

    def _group_by_category(self) -> dict[str, list[tuple[AnalyzerResult, Any]]]:
        """Group results by category."""
        categories: dict[str, list[tuple[AnalyzerResult, Any]]] = {
            name: [] for name in self.CATEGORY_WEIGHTS
        }

        for result in self._results:
            category = self.ANALYZER_CATEGORIES.get(result.analyzer_name)
            if category:
                for issue in result.issues:
                    categories[category].append((result, issue))

        return categories

    def _calculate_category_score(
        self,
        category_name: str,
        weight: float,
        issues: list[tuple[AnalyzerResult, Any]],
        total_tests: int,
    ) -> CategoryScore:
        """Calculate score for a single category."""
        category = CategoryScore(name=category_name, weight=weight)
        category.issue_count = len(issues)

        if not issues:
            category.raw_score = 100.0
        else:
            # Calculate penalty based on issues
            total_penalty = 0.0
            for _, issue in issues:
                penalty = self.SEVERITY_PENALTIES.get(issue.severity, 0)
                total_penalty += penalty

            # Normalize penalty by number of tests
            normalized_penalty = total_penalty / total_tests if total_tests > 0 else 0
            category.raw_score = max(0.0, 100.0 - normalized_penalty)

        category.weighted_score = category.raw_score * weight
        return category

    @staticmethod
    def _score_to_grade(score: float) -> str:
        """Convert numeric score to letter grade."""
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"

    def get_simple_score(
        self,
        results: list[AnalyzerResult],
        total_tests: int,
    ) -> float:
        """Get a simple numeric score (for backwards compatibility)."""
        breakdown = self.calculate_score(results, total_tests)
        return breakdown.total_score
