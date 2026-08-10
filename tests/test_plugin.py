"""Tests for the pytest plugin integration."""

from __future__ import annotations

import pytest


class TestPluginOptions:
    """Test command line option parsing."""

    def test_review_option_default_disabled(self, pytester: pytest.Pytester) -> None:
        """Plugin is disabled by default."""
        pytester.makepyfile("""
            def test_example():
                assert True
        """)
        result = pytester.runpytest()
        result.assert_outcomes(passed=1)
        # Review header should not appear
        assert "pytest-review" not in result.stdout.str()

    def test_review_option_enables_plugin(self, pytester: pytest.Pytester) -> None:
        """--review flag enables the plugin."""
        pytester.makepyfile("""
            def test_example():
                assert True
        """)
        result = pytester.runpytest("--review")
        result.assert_outcomes(passed=1)
        # Review header should appear
        assert "pytest-review" in result.stdout.str()
        assert "Test Quality Report" in result.stdout.str()

    def test_review_shows_summary(self, pytester: pytest.Pytester) -> None:
        """Review shows summary with test count."""
        pytester.makepyfile("""
            def test_one():
                assert True

            def test_two():
                assert True
        """)
        result = pytester.runpytest("--review")
        result.assert_outcomes(passed=2)
        assert "Tests analyzed: 2" in result.stdout.str()

    def test_review_skip_marker(self, pytester: pytest.Pytester) -> None:
        """Tests marked with review_skip are excluded."""
        pytester.makepyfile("""
            import pytest

            def test_included():
                assert True

            @pytest.mark.review_skip
            def test_excluded():
                assert True
        """)
        result = pytester.runpytest("--review")
        result.assert_outcomes(passed=2)
        # Only one test should be analyzed
        assert "Tests analyzed: 1" in result.stdout.str()


class TestParametrizedTests:
    """Parametrized tests must be reachable by static analysis.

    Pytest names parametrized items ``test_foo[case0]`` while the AST function
    is ``test_foo``; matching on the item name alone silently skipped them.
    """

    def test_parametrized_test_is_analyzed(self, pytester: pytest.Pytester) -> None:
        """A bad assertion in a parametrized test is reported."""
        pytester.makepyfile("""
            import pytest

            @pytest.mark.parametrize("value", [1, 2, 3])
            def test_x(value):
                assert True
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        result.assert_outcomes(passed=3)
        output = result.stdout.str()
        assert "Trivial assertion" in output
        assert "Non-descriptive test name: 'test_x'" in output

    def test_parametrized_cases_counted_once(self, pytester: pytest.Pytester) -> None:
        """All cases share one source function, so it is analyzed once."""
        pytester.makepyfile("""
            import pytest

            @pytest.mark.parametrize("value", [1, 2, 3])
            def test_x(value):
                assert True
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        result.assert_outcomes(passed=3)
        output = result.stdout.str()
        assert "Tests analyzed: 1" in output
        # The same issue must not be repeated once per parameter set
        assert output.count("Trivial assertion") == 1

    def test_parametrized_method_in_class_is_analyzed(
        self, pytester: pytest.Pytester
    ) -> None:
        """Class-based parametrized tests resolve to the right ClassDef."""
        pytester.makepyfile("""
            import pytest

            class TestAlpha:
                @pytest.mark.parametrize("value", [1, 2])
                def test_y(self, value):
                    assert True

            class TestBeta:
                def test_y(self):
                    result = 1 + 1
                    assert result == 2
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        result.assert_outcomes(passed=3)
        output = result.stdout.str()
        assert "Tests analyzed: 2" in output
        assert "Trivial assertion" in output

    def test_non_parametrized_still_analyzed(self, pytester: pytest.Pytester) -> None:
        """The name-resolution change must not regress plain tests."""
        pytester.makepyfile("""
            def test_x():
                assert True
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        assert "Tests analyzed: 1" in result.stdout.str()
        assert "Trivial assertion" in result.stdout.str()


class TestConfigEnforcement:
    """``strict`` and ``min_score`` from pyproject.toml must be enforced."""

    _BAD_TEST = """
        def test_x():
            pass
    """

    def test_config_strict_fails_run(self, pytester: pytest.Pytester) -> None:
        """strict = true in pyproject.toml fails the run without any CLI flag."""
        pytester.makepyfile(self._BAD_TEST)
        pytester.makepyprojecttoml("""
            [tool.pytest-review]
            strict = true
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        result.assert_outcomes(passed=1)
        assert result.ret == pytest.ExitCode.TESTS_FAILED
        assert "FAILED: Quality errors found" in result.stdout.str()

    def test_config_strict_false_does_not_fail(self, pytester: pytest.Pytester) -> None:
        """strict = false leaves the exit status untouched."""
        pytester.makepyfile(self._BAD_TEST)
        pytester.makepyprojecttoml("""
            [tool.pytest-review]
            strict = false
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        assert result.ret == pytest.ExitCode.OK
        assert "FAILED: Quality errors found" not in result.stdout.str()

    def test_config_min_score_fails_run(self, pytester: pytest.Pytester) -> None:
        """min_score in pyproject.toml is enforced without any CLI flag."""
        pytester.makepyfile(self._BAD_TEST)
        pytester.makepyprojecttoml("""
            [tool.pytest-review]
            min_score = 95
        """)
        result = pytester.runpytest("--review", "--review-no-cache")
        result.assert_outcomes(passed=1)
        assert result.ret == pytest.ExitCode.TESTS_FAILED
        assert "below minimum 95" in result.stdout.str()

    def test_cli_min_score_overrides_config(self, pytester: pytest.Pytester) -> None:
        """An explicit --review-min-score wins over the config value."""
        pytester.makepyfile(self._BAD_TEST)
        pytester.makepyprojecttoml("""
            [tool.pytest-review]
            min_score = 95
        """)
        result = pytester.runpytest("--review", "--review-no-cache", "--review-min-score=1")
        assert result.ret == pytest.ExitCode.OK
        assert "below minimum" not in result.stdout.str()

    def test_cli_strict_works_without_config(self, pytester: pytest.Pytester) -> None:
        """--review-strict still fails the run on its own."""
        pytester.makepyfile(self._BAD_TEST)
        result = pytester.runpytest("--review", "--review-no-cache", "--review-strict")
        assert result.ret == pytest.ExitCode.TESTS_FAILED
        assert "FAILED: Quality errors found" in result.stdout.str()


class TestPluginOutput:
    """Test plugin output formatting."""

    def test_shows_quality_excellent_when_no_issues(self, pytester: pytest.Pytester) -> None:
        """Shows excellent quality when no issues found."""
        # Use a well-formed test that passes all analyzers
        pytester.makepyfile("""
            def test_validates_user_authentication_with_valid_credentials():
                user_id = 123
                expected_id = 123
                assert user_id == expected_id
        """)
        result = pytester.runpytest("--review")
        assert "No quality issues found" in result.stdout.str()
        assert "Quality: EXCELLENT" in result.stdout.str()

    def test_shows_overall_score(self, pytester: pytest.Pytester) -> None:
        """Shows overall score in output."""
        pytester.makepyfile("""
            def test_calculation_returns_expected_result():
                result = 1 + 1
                assert result == 2
        """)
        result = pytester.runpytest("--review")
        assert "Overall Score:" in result.stdout.str()
        assert "/100" in result.stdout.str()

    def test_detects_quality_issues(self, pytester: pytest.Pytester) -> None:
        """Shows issues when tests have quality problems."""
        pytester.makepyfile("""
            def test_1():
                assert True
        """)
        result = pytester.runpytest("--review")
        # Should detect issues with this test
        assert "Quality: NEEDS IMPROVEMENT" in result.stdout.str()
        output = result.stdout.str()
        assert "assertions.trivial" in output or "Trivial assertion" in output


class TestPluginMinSeverity:
    """Test --review-min-severity filtering behavior."""

    def test_default_hides_info_issues(self, pytester: pytest.Pytester) -> None:
        """By default (min_severity=warning), INFO issues are hidden."""
        # ``is not None`` triggers assertions.low_value, which is INFO.
        pytester.makepyfile("""
            def test_returns_something_meaningful_here():
                value = compute()
                assert value is not None

            def compute():
                return 42
        """)
        result = pytester.runpytest("--review")
        output = result.stdout.str()
        # INFO rule should NOT appear
        assert "assertions.low_value" not in output
        assert "Low-value assertion" not in output

    def test_explicit_info_shows_info_issues(self, pytester: pytest.Pytester) -> None:
        """--review-min-severity=info restores INFO visibility."""
        pytester.makepyfile("""
            def test_returns_something_meaningful_here():
                value = compute()
                assert value is not None

            def compute():
                return 42
        """)
        result = pytester.runpytest("--review", "--review-min-severity=info")
        output = result.stdout.str()
        assert "assertions.low_value" in output or "Low-value assertion" in output

    def test_error_only_hides_warnings(self, pytester: pytest.Pytester) -> None:
        """--review-min-severity=error hides WARNING-level issues."""
        # ``assertions.insufficient`` is a WARNING; configure min_assertions=2
        # so a single-assert test triggers it.
        pytester.makepyfile("""
            def test_has_only_one_assertion_here():
                x = compute()
                assert x == 42

            def compute():
                return 42
        """)
        pytester.makepyprojecttoml("""
            [tool.pytest-review.analyzers.assertions]
            enabled = true
            min_assertions = 2
        """)
        result = pytester.runpytest("--review", "--review-min-severity=error")
        output = result.stdout.str()
        assert "has only 1 assertion" not in output
        # Sanity: without the filter the warning would appear
        result2 = pytester.runpytest("--review", "--review-min-severity=warning")
        assert "has only 1 assertion" in result2.stdout.str()

    def test_filtering_does_not_affect_score(self, pytester: pytest.Pytester) -> None:
        """Hidden issues still count toward the score."""
        pytester.makepyfile("""
            def test_returns_something_meaningful_here():
                value = compute()
                assert value is not None

            def compute():
                return 42
        """)
        shown = pytester.runpytest("--review", "--review-min-severity=info").stdout.str()
        hidden = pytester.runpytest("--review", "--review-min-severity=error").stdout.str()

        def extract_score(out: str) -> str:
            for line in out.splitlines():
                if "Overall Score:" in line:
                    return line.strip()
            raise AssertionError("Overall Score line missing from output")

        assert extract_score(shown) == extract_score(hidden)

    def test_config_file_sets_min_severity(self, pytester: pytest.Pytester) -> None:
        """[tool.pytest-review] min_severity in pyproject.toml is honored."""
        pytester.makepyfile("""
            def test_returns_something_meaningful_here():
                value = compute()
                assert value is not None

            def compute():
                return 42
        """)
        pytester.makepyprojecttoml("""
            [tool.pytest-review]
            min_severity = "info"
        """)
        result = pytester.runpytest("--review")
        output = result.stdout.str()
        assert "assertions.low_value" in output or "Low-value assertion" in output

    def test_cli_overrides_config(self, pytester: pytest.Pytester) -> None:
        """--review-min-severity on the CLI overrides pyproject.toml."""
        pytester.makepyfile("""
            def test_returns_something_meaningful_here():
                value = compute()
                assert value is not None

            def compute():
                return 42
        """)
        pytester.makepyprojecttoml("""
            [tool.pytest-review]
            min_severity = "info"
        """)
        result = pytester.runpytest("--review", "--review-min-severity=error")
        output = result.stdout.str()
        assert "assertions.low_value" not in output
