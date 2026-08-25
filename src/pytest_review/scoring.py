"""Quality scoring system for pytest-review."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pytest_review.analyzers.base import AnalyzerResult, Issue, Severity


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

    # Analyzer to category mapping (built-in analyzers)
    ANALYZER_CATEGORIES: dict[str, str] = {
        "assertions": "assertions",
        "isolation": "isolation",
        "leaks": "isolation",
        "patterns": "simplicity",
        "performance": "performance",
        "smells": "clarity",
    }

    # Severity penalties, expressed on a *per-test* scale: these are the points
    # a single defective test forfeits within its category, not absolute points
    # off the final score. An ERROR costs a test all of its credit, so a
    # category in which every test errors scores 0 regardless of suite size.
    SEVERITY_PENALTIES = {
        Severity.ERROR: 100.0,
        Severity.WARNING: 35.0,
        Severity.INFO: 7.0,
    }

    # A single test cannot forfeit more than its own share of a category, so
    # per-test penalties saturate here. Without this cap, one test carrying
    # several issues would consume the budget of tests that are perfectly fine.
    MAX_PENALTY_PER_TEST = 100.0

    # Critical issue penalties, applied globally on top of category scores and
    # scaled by the fraction of the suite affected (see ``_critical_penalties``).
    #
    # ``assertions.missing`` is *derived*, not chosen: when the assertions
    # category zeroes out, the other categories still hold the rest of the
    # weight, so charging exactly that remainder makes a suite whose every test
    # verifies nothing score 0. Expressed against CATEGORY_WEIGHTS so it stays
    # derived if those weights are ever retuned.
    #
    # ``assertions.trivial`` is deliberately *not* given the same treatment: it
    # fires on a test containing ``assert True`` alongside real, substantive
    # assertions, so it flags a test carrying dead weight rather than a test
    # that verifies nothing. Charging it the full remainder would punish tests
    # that do their job.
    CRITICAL_PENALTIES = {
        "assertions.missing": 100.0 * (1.0 - CATEGORY_WEIGHTS["assertions"]),
        "assertions.trivial": 25.0,
    }

    def __init__(self, extra_categories: dict[str, str] | None = None) -> None:
        self._categories = dict(self.ANALYZER_CATEGORIES)
        if extra_categories:
            self._categories.update(extra_categories)

    def calculate_score(
        self,
        results: list[AnalyzerResult],
        total_tests: int,
    ) -> ScoreBreakdown:
        """Calculate the overall quality score."""
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
        category_issues = self._group_by_category(results)
        for category_name, weight in self.CATEGORY_WEIGHTS.items():
            issues = category_issues.get(category_name, [])
            category_score = self._calculate_category_score(
                category_name, weight, issues, total_tests
            )
            breakdown.categories.append(category_score)

        # Apply critical penalties
        breakdown.penalties.extend(self._critical_penalties(results, total_tests))

        # Calculate total score
        weighted_sum = sum(c.weighted_score for c in breakdown.categories)
        total_penalty = sum(p[1] for p in breakdown.penalties)

        breakdown.total_score = max(0.0, min(100.0, weighted_sum - total_penalty))
        breakdown.grade = self._score_to_grade(breakdown.total_score)

        return breakdown

    def _group_by_category(
        self,
        results: list[AnalyzerResult],
    ) -> dict[str, list[tuple[AnalyzerResult, Issue]]]:
        """Group results by category."""
        categories: dict[str, list[tuple[AnalyzerResult, Issue]]] = {
            name: [] for name in ScoringEngine.CATEGORY_WEIGHTS
        }

        for result in results:
            category = self._categories.get(result.analyzer_name)
            if category and category in categories:
                for issue in result.issues:
                    categories[category].append((result, issue))

        return categories

    def _calculate_category_score(
        self,
        category_name: str,
        weight: float,
        issues: list[tuple[AnalyzerResult, Issue]],
        total_tests: int,
    ) -> CategoryScore:
        """Calculate score for a single category."""
        category = CategoryScore(name=category_name, weight=weight)
        category.issue_count = len(issues)

        if not issues or total_tests <= 0:
            category.raw_score = 100.0
        else:
            # Sum each test's penalty separately and saturate it, so that one
            # spectacularly bad test cannot outweigh the whole suite, then take
            # the mean across the suite. The result is a defect *density*: it is
            # invariant to suite size, and reaches 0 only when every test in the
            # suite is defective.
            per_test: dict[object, float] = {}
            for _, issue in issues:
                key = self._test_key(issue)
                penalty = self.SEVERITY_PENALTIES.get(issue.severity, 0.0)
                per_test[key] = per_test.get(key, 0.0) + penalty

            total_penalty = sum(min(p, self.MAX_PENALTY_PER_TEST) for p in per_test.values())
            category.raw_score = max(0.0, 100.0 - total_penalty / total_tests)

        category.weighted_score = category.raw_score * weight
        return category

    @staticmethod
    def _test_key(issue: Issue) -> object:
        """Identity of the test an issue belongs to, for per-test aggregation.

        Issues raised by the built-in analyzers always carry a ``test_name``.
        When one is missing the issue cannot be attributed, so it is given a
        bucket of its own rather than being silently merged with unrelated
        issues, which would under-count the defect density.
        """
        if issue.test_name is None:
            return id(issue)
        return (str(issue.file_path), issue.test_name)

    def _critical_penalties(
        self,
        results: list[AnalyzerResult],
        total_tests: int,
    ) -> list[tuple[str, float]]:
        """Global penalties for critical rules, scaled by the share of tests hit.

        One empty test in a 100-test suite is a rounding error; a suite in which
        every test is empty deserves the full penalty. Counting *tests affected*
        rather than issues keeps a single test that trips the same rule twice
        from being charged twice.
        """
        affected: dict[str, set[object]] = {}
        for result in results:
            for issue in result.issues:
                if issue.rule in self.CRITICAL_PENALTIES:
                    affected.setdefault(issue.rule, set()).add(self._test_key(issue))

        penalties: list[tuple[str, float]] = []
        for rule, tests in affected.items():
            share = min(1.0, len(tests) / total_tests) if total_tests > 0 else 0.0
            penalties.append((rule, self.CRITICAL_PENALTIES[rule] * share))
        return penalties

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
