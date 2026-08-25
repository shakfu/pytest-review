"""Tests for the assertions analyzer."""

from __future__ import annotations

import ast
from pathlib import Path

from pytest_review.analyzers.assertions import AssertionsAnalyzer
from pytest_review.analyzers.base import Severity, TestItemInfo
from pytest_review.config import ReviewConfig


def make_test_info(source: str, name: str = "test_example") -> TestItemInfo:
    """Helper to create TestItemInfo from source code."""
    tree = ast.parse(source)
    func_node = tree.body[0]
    assert isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef))
    return TestItemInfo(
        name=name,
        file_path=Path("test_file.py"),
        line=1,
        node=func_node,
        source=source,
    )


class TestAssertionsAnalyzer:
    def test_detects_empty_test(self) -> None:
        source = """
def test_empty():
    pass
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_empty")

        result = analyzer.analyze(test_info)

        assert result.issue_count == 1
        assert result.issues[0].rule == "assertions.missing"
        assert result.issues[0].severity == Severity.ERROR

    def test_detects_assert_true(self) -> None:
        source = """
def test_trivial():
    assert True
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_trivial")

        result = analyzer.analyze(test_info)

        # Should have trivial assertion issue
        trivial_issues = [i for i in result.issues if i.rule == "assertions.trivial"]
        assert len(trivial_issues) == 1
        assert "assert True" in trivial_issues[0].message

    def test_detects_assert_false(self) -> None:
        source = """
def test_always_fails():
    assert False
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_always_fails")

        result = analyzer.analyze(test_info)

        trivial_issues = [i for i in result.issues if i.rule == "assertions.trivial"]
        assert len(trivial_issues) == 1
        assert "assert False" in trivial_issues[0].message

    def test_detects_tautology(self) -> None:
        source = """
def test_tautology():
    x = 5
    assert x == x
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_tautology")

        result = analyzer.analyze(test_info)

        trivial_issues = [i for i in result.issues if i.rule == "assertions.trivial"]
        assert len(trivial_issues) == 1
        assert "comparing value to itself" in trivial_issues[0].message

    def test_accepts_valid_assertion(self) -> None:
        source = """
def test_valid():
    result = 1 + 1
    assert result == 2
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_valid")

        result = analyzer.analyze(test_info)

        assert result.issue_count == 0

    def test_counts_pytest_raises(self) -> None:
        source = """
def test_raises():
    import pytest
    with pytest.raises(ValueError):
        raise ValueError("test")
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_raises")

        result = analyzer.analyze(test_info)

        # pytest.raises counts as an assertion
        assert result.metadata["assertion_count"] == 1
        missing_issues = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing_issues) == 0

    def test_respects_min_assertions_config(self) -> None:
        source = """
def test_one_assertion():
    assert True is True
"""
        config = ReviewConfig.from_dict(
            {"analyzers": {"assertions": {"enabled": True, "min_assertions": 2}}}
        )
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_one_assertion")

        result = analyzer.analyze(test_info)

        insufficient_issues = [i for i in result.issues if i.rule == "assertions.insufficient"]
        assert len(insufficient_issues) == 1

    def _raises_issues(self, source: str, name: str) -> list[str]:
        analyzer = AssertionsAnalyzer(ReviewConfig())
        result = analyzer.analyze(make_test_info(source.strip(), name))
        return [i.rule for i in result.issues if i.rule == "assertions.raises_without_match"]

    def test_no_raises_issue_with_excinfo_match(self) -> None:
        """``excinfo.match(...)`` after ``as excinfo`` verifies the message."""
        source = """
def test_raises_excinfo_match():
    import pytest
    with pytest.raises(ValueError) as excinfo:
        do_something()
    excinfo.match("invalid")
"""
        assert self._raises_issues(source, "test_raises_excinfo_match") == []

    def test_no_raises_issue_with_str_excinfo_value(self) -> None:
        """``assert ... in str(excinfo.value)`` verifies the message."""
        source = """
def test_raises_str_value():
    import pytest
    with pytest.raises(ValueError) as excinfo:
        do_something()
    assert "invalid" in str(excinfo.value)
"""
        assert self._raises_issues(source, "test_raises_str_value") == []

    def test_detects_mock_assert_called_once(self) -> None:
        source = """
def test_mock_assert():
    mock_obj = create_mock()
    do_work(mock_obj)
    mock_obj.assert_called_once()
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_mock_assert")

        result = analyzer.analyze(test_info)

        missing = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing) == 0
        assert result.metadata["assertion_count"] == 1

    def test_detects_mock_assert_called_with(self) -> None:
        source = """
def test_mock_call_with():
    mock_obj = create_mock()
    do_work(mock_obj, 42)
    mock_obj.assert_called_with(42)
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_mock_call_with")

        result = analyzer.analyze(test_info)

        missing = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing) == 0
        assert result.metadata["assertion_count"] == 1

    def test_detects_mock_assert_any_call(self) -> None:
        source = """
def test_mock_any_call():
    mock_obj = create_mock()
    do_work(mock_obj)
    mock_obj.assert_any_call(1, 2)
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_mock_any_call")

        result = analyzer.analyze(test_info)

        missing = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing) == 0
        assert result.metadata["assertion_count"] == 1

    def test_detects_mock_assert_not_called(self) -> None:
        source = """
def test_mock_not_called():
    mock_obj = create_mock()
    skip_work(mock_obj)
    mock_obj.assert_not_called()
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_mock_not_called")

        result = analyzer.analyze(test_info)

        missing = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing) == 0
        assert result.metadata["assertion_count"] == 1

    def test_detects_mock_assert_has_calls(self) -> None:
        source = """
def test_mock_has_calls():
    mock_obj = create_mock()
    do_work(mock_obj)
    mock_obj.assert_has_calls([call(1), call(2)])
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_mock_has_calls")

        result = analyzer.analyze(test_info)

        missing = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing) == 0
        assert result.metadata["assertion_count"] == 1

    def test_detects_user_defined_assert_helper(self) -> None:
        source = """
def test_helper():
    result = run_query()
    assert_rss_bounded(result, max_mb=100)
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_helper")

        result = analyzer.analyze(test_info)

        missing = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing) == 0
        assert result.metadata["assertion_count"] == 1

    def test_detects_unittest_style_assert_equal(self) -> None:
        source = """
def test_unittest():
    self.assertEqual(compute(), 42)
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_unittest")

        result = analyzer.analyze(test_info)

        missing = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing) == 0
        assert result.metadata["assertion_count"] == 1

    def test_detects_unittest_style_assert_true(self) -> None:
        source = """
def test_unittest_true():
    self.assertTrue(compute())
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_unittest_true")

        result = analyzer.analyze(test_info)

        missing = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing) == 0
        assert result.metadata["assertion_count"] == 1

    def test_detects_bare_raises_context_manager(self) -> None:
        source = """
def test_bare_raises():
    from pytest import raises
    with raises(ValueError):
        do_something()
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_bare_raises")

        result = analyzer.analyze(test_info)

        missing = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing) == 0
        assert result.metadata["assertion_count"] == 1

    def test_non_assertion_helper_not_counted(self) -> None:
        source = """
def test_non_helper():
    result = compute_value()
    process(result)
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_non_helper")

        result = analyzer.analyze(test_info)

        # No assert-prefixed calls -- should be flagged as missing.
        missing = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing) == 1

    def test_similar_but_non_assert_name_not_counted(self) -> None:
        # ``asserted`` starts with ``assert`` but is not an assertion helper.
        source = """
def test_not_assert():
    asserted(42)
    assertion(x)
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_not_assert")

        result = analyzer.analyze(test_info)

        missing = [i for i in result.issues if i.rule == "assertions.missing"]
        assert len(missing) == 1

    def _rules(self, source: str, name: str) -> list[str]:
        analyzer = AssertionsAnalyzer(ReviewConfig())
        return [i.rule for i in analyzer.analyze(make_test_info(source.strip(), name)).issues]

    def test_detects_generator_expression_in_assert(self) -> None:
        """``assert (x for x in xs)`` asserts on the generator object, not the values."""
        source = """
def test_all_positive(items):
    assert (x > 0 for x in items)
"""
        assert "assertions.always_true" in self._rules(source, "test_all_positive")

    def test_detects_lambda_in_assert(self) -> None:
        source = """
def test_predicate():
    assert lambda: False
"""
        assert "assertions.always_true" in self._rules(source, "test_predicate")

    def test_list_comprehension_in_assert_is_fine(self) -> None:
        """A comprehension is materialised, so its truthiness is meaningful."""
        source = """
def test_filters(items):
    assert [x for x in items if x > 0] == [1]
"""
        assert "assertions.always_true" not in self._rules(source, "test_filters")

    def test_detects_uncalled_mock_assertion(self) -> None:
        """``assert mock.assert_called_once`` is always true -- it is never called.

        Ruff's PGH005 catches the bare-statement form but not this one, where the
        reference hides inside an ``assert``.
        """
        source = """
def test_calls_service(mock_svc):
    assert mock_svc.assert_called_once
"""
        assert "assertions.uncalled_assertion" in self._rules(source, "test_calls_service")

    def test_detects_uncalled_called_once_property(self) -> None:
        source = """
def test_calls_service(mock_svc):
    assert mock_svc.called_once
"""
        assert "assertions.uncalled_assertion" in self._rules(source, "test_calls_service")

    def test_called_mock_assertion_is_fine(self) -> None:
        source = """
def test_calls_service(mock_svc):
    mock_svc.assert_called_once()
"""
        assert "assertions.uncalled_assertion" not in self._rules(source, "test_calls_service")

    def test_plain_attribute_assert_is_fine(self) -> None:
        """Only assertion-shaped attribute names are suspicious."""
        source = """
def test_flag(result):
    assert result.is_valid
"""
        assert "assertions.uncalled_assertion" not in self._rules(source, "test_flag")

    def test_detects_assertion_on_a_patched_target(self) -> None:
        """Asserting on the thing you patched verifies unittest.mock, not your code."""
        source = """
@mock.patch("pkg.svc.fetch")
def test_fetches(mock_fetch):
    mock_fetch.return_value = 5
    assert pkg.svc.fetch() == 5
"""
        assert "assertions.mock_tautology" in self._rules(source, "test_fetches")

    def test_detects_tautology_through_a_shorter_import_path(self) -> None:
        """``svc.fetch()`` still matches a ``pkg.svc.fetch`` patch target."""
        source = """
@mock.patch("pkg.svc.fetch")
def test_fetches(mock_fetch):
    mock_fetch.return_value = 5
    assert svc.fetch() == 5
"""
        assert "assertions.mock_tautology" in self._rules(source, "test_fetches")

    def test_patching_a_dependency_and_asserting_on_real_code_is_fine(self) -> None:
        """The correct pattern: the patched call is an input, not the subject."""
        source = """
@mock.patch("pkg.svc.fetch")
def test_doubles(mock_fetch):
    mock_fetch.return_value = 5
    assert pkg.svc.double_it() == 10
"""
        assert "assertions.mock_tautology" not in self._rules(source, "test_doubles")

    def test_asserting_on_the_mock_object_is_fine(self) -> None:
        """Checking that a dependency was called is a wiring check, not a tautology."""
        source = """
@mock.patch("pkg.svc.fetch")
def test_calls_dependency(mock_fetch):
    pkg.svc.run()
    mock_fetch.assert_called_once()
"""
        assert "assertions.mock_tautology" not in self._rules(source, "test_calls_dependency")

    def test_stores_metadata(self) -> None:
        source = """
def test_with_assertions():
    x = 1
    assert x == 1
    assert x > 0
    assert True  # trivial
"""
        config = ReviewConfig()
        analyzer = AssertionsAnalyzer(config)
        test_info = make_test_info(source.strip(), "test_with_assertions")

        result = analyzer.analyze(test_info)

        assert result.metadata["assertion_count"] == 3
        assert result.metadata["trivial_count"] == 1
