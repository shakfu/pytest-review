"""Tests for the pytest plugin integration."""

from __future__ import annotations

from pathlib import Path

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
        # reported once per function, not once per parametrized case
        assert output.count("Trivial assertion") == 1

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

    # An empty test forfeits everything: a one-test suite of them scores exactly
    # 0, so no positive threshold can clear it. Where a test needs a score that
    # sits *between* two thresholds, use a merely-poor test instead of a
    # worthless one.
    _MEDIOCRE_TEST = """
        def test_x():
            assert True
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
        """An explicit --review-min-score wins over the config value.

        The module scores between the two thresholds, so the run's outcome
        actually distinguishes them: the config value would fail it and the CLI
        value passes it.
        """
        pytester.makepyfile(self._MEDIOCRE_TEST)
        pytester.makepyprojecttoml("""
            [tool.pytest-review]
            min_score = 95
        """)
        result = pytester.runpytest("--review", "--review-no-cache", "--review-min-score=1")
        assert result.ret == pytest.ExitCode.OK
        assert "below minimum" not in result.stdout.str()

    def test_bundled_bad_example_fails_min_score_gate(
        self, pytester: pytest.Pytester, restore_environ: None
    ) -> None:
        """``examples/bad_tests.py`` must fail the gate ``make example-min-score`` uses.

        That Makefile target exists to demonstrate ``--review-min-score=70``
        rejecting a bad suite. Unit tests on the scoring engine did not catch a
        regression that made the bundled example score 92/A, because nothing
        asserted what a realistically bad module actually scores end to end.
        """
        example = Path(__file__).parent.parent / "examples" / "bad_tests.py"
        if not example.is_file():
            pytest.skip("examples/bad_tests.py not available (installed package)")
        pytester.makepyfile(bad_tests=example.read_text())

        # Passed by path: "bad_tests.py" matches no default ``python_files`` pattern,
        # exactly as ``make example-min-score`` invokes it.
        result = pytester.runpytest(
            "bad_tests.py", "--review", "--review-no-cache", "--review-min-score=70"
        )

        assert result.ret == pytest.ExitCode.TESTS_FAILED
        assert "below minimum 70" in result.stdout.str()

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

    def test_score_is_hidden_unless_a_threshold_is_in_force(
        self, pytester: pytest.Pytester
    ) -> None:
        """The grade is a gate input, not the headline.

        This is a defect finder: the findings are what a developer acts on.
        Leading with a grade invites tuning the number instead of fixing the
        tests, so the score appears only when --review-min-score is set.
        """
        pytester.makepyfile("""
            def test_calculation_returns_expected_result():
                result = 1 + 1
                assert result == 2
        """)

        default = pytester.runpytest("--review").stdout.str()
        assert "Overall Score:" not in default

        gated = pytester.runpytest("--review", "--review-min-score=1").stdout.str()
        assert "Overall Score:" in gated
        assert "/100" in gated

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
        shown = pytester.runpytest(
            "--review", "--review-min-severity=info", "--review-min-score=1"
        ).stdout.str()
        hidden = pytester.runpytest(
            "--review", "--review-min-severity=error", "--review-min-score=1"
        ).stdout.str()

        def extract_score(out: str) -> str:
            for line in out.splitlines():
                if "Overall Score:" in line:
                    return line.strip()
            raise AssertionError("Overall Score line missing from output")

        assert extract_score(shown) == extract_score(hidden)


class TestUnknownAnalyzerWarning:
    """An analyzer name that matches nothing must not fail silently.

    ``--review-only=naming`` against a build with no ``naming`` analyzer selects
    nothing, analyzes nothing, and reports success -- so a CI job pinned to a
    removed analyzer would pass while checking nothing at all.
    """

    def test_warns_on_unknown_review_only(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_adds_two_numbers():
                assert 1 + 1 == 2
        """)
        with pytest.warns(UserWarning, match="unknown analyzer"):
            pytester.runpytest("--review", "--review-no-cache", "--review-only=naming")

    def test_warns_on_unknown_analyzer_in_config(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_adds_two_numbers():
                assert 1 + 1 == 2
        """)
        pytester.makepyprojecttoml("""
            [tool.pytest-review.analyzers]
            naming = { enabled = true }
        """)
        with pytest.warns(UserWarning, match="unknown analyzer"):
            pytester.runpytest("--review", "--review-no-cache")

    def test_no_warning_for_known_analyzers(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            def test_adds_two_numbers():
                assert 1 + 1 == 2
        """)
        import warnings as _warnings

        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            pytester.runpytest("--review", "--review-no-cache", "--review-only=assertions")

        assert not [w for w in caught if "unknown analyzer" in str(w.message)]
