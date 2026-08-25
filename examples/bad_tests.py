"""Comprehensive examples of bad tests to demonstrate all pytest-review detections.

This file intentionally contains tests with quality issues to verify that
all analyzers are working correctly. Run with:

    make example           # Run review on examples
    make example-verify    # Verify all expected rules are detected

Expected detections by analyzer (20 rules):

ASSERTIONS (2 rules):
- assertions.missing: test_empty_no_assertions
- assertions.trivial: test_assert_true, test_assert_false, test_tautology_same_variable

NAMING (3 rules):
- naming.non_descriptive: test_foo, test_bar, test_example, test_x, test_it
- naming.too_short: test_x, test_it, test_foo, test_bar, test_example
- naming.not_snake_case: test_notSnakeCase

COMPLEXITY (3 rules):
- complexity.too_many_statements: test_too_many_statements
- complexity.deep_nesting: test_deeply_nested, test_high_cyclomatic_complexity
- complexity.high_cyclomatic: test_high_cyclomatic_complexity, test_deeply_nested

PATTERNS (5 rules):
- patterns.bare_except: test_bare_except_clause
- patterns.sleep_in_test: test_uses_sleep
- patterns.print_statement: test_uses_print
- patterns.os_system: test_uses_os_system
- patterns.is_literal: test_uses_is_with_literal

ISOLATION (2 rules):
- isolation.global_modification: test_modifies_global_state
- isolation.class_attr_modification: TestClassState.test_modifies_class_attr

SMELLS (5 rules):
- smells.assertion_roulette: test_assertion_roulette
- smells.duplicate_assert: test_duplicate_assertions
- smells.ignored_test: test_skipped_test
- smells.magic_number: test_magic_numbers
- smells.eager_test: test_eager_multiple_functions
"""

from __future__ import annotations

from unittest import mock

import pytest
import os
import time

import pytest

# =============================================================================
# ASSERTIONS ANALYZER
# =============================================================================

# Global state for isolation tests
_global_counter = 0


def test_empty_no_assertions():
    """assertions.missing - Test has no assertions."""
    x = 1 + 1
    y = x * 2


def test_assert_true():
    """assertions.trivial - Trivial assert True."""
    assert True


def test_tautology_same_variable():
    """assertions.tautology - Comparing variable to itself."""
    result = calculate_something()
    assert result == result


def calculate_something():
    """Helper function."""
    return 42


# =============================================================================
# NAMING ANALYZER
# =============================================================================


def test_foo():
    """naming.non_descriptive - Generic name 'foo'."""
    assert 1 == 1, "placeholder"


def test_bar():
    """naming.non_descriptive - Generic name 'bar'."""
    assert 2 == 2, "placeholder"


def test_example():
    """naming.non_descriptive - Generic name 'example'."""
    assert 3 == 3, "placeholder"


def test_x():
    """naming.too_short - Single character name."""
    assert 1 == 1, "placeholder"


def test_it():
    """naming.too_short - Too short name."""
    assert 1 == 1, "placeholder"


def test_notSnakeCase():
    """naming.not_snake_case - camelCase instead of snake_case."""
    assert 1 == 1, "placeholder"


# =============================================================================
# COMPLEXITY ANALYZER
# =============================================================================


def test_too_many_statements():
    """complexity.too_many_statements - More than 20 statements."""
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    f = 6
    g = 7
    h = 8
    i = 9
    j = 10
    k = 11
    m = 12
    n = 13
    o = 14
    p = 15
    q = 16
    r = 17
    s = 18
    t = 19
    u = 20
    v = 21
    assert a + b + c + d + e + f + g + h + i + j + k + m + n + o + p + q + r + s + t + u + v > 0, "sum check"


def test_deeply_nested():
    """complexity.too_deep - Nesting depth exceeds 3."""
    result = 0
    for i in range(2):
        for j in range(2):
            for k in range(2):
                for m in range(2):
                    if i > 0:
                        if j > 0:
                            result += 1
    assert result > 0, "nesting result"


def test_high_cyclomatic_complexity():
    """complexity.too_complex - Cyclomatic complexity exceeds 5."""
    x = 1
    if x == 1:
        y = 1
    elif x == 2:
        y = 2
    elif x == 3:
        y = 3
    elif x == 4:
        y = 4
    elif x == 5:
        y = 5
    elif x == 6:
        y = 6
    else:
        y = 0
    assert y == 1, "complexity result"


# =============================================================================
# PATTERNS ANALYZER
# =============================================================================


def test_bare_except_clause():
    """patterns.bare_except - Catches all exceptions."""
    try:
        result = 1 / 0
    except:
        result = 0
    assert result == 0, "caught exception"


def test_uses_sleep():
    """patterns.sleep_in_test - Uses time.sleep()."""
    time.sleep(0.001)
    assert True, "slept"


def test_uses_print():
    """patterns.print_statement - Debug print left in test."""
    print("debugging output")
    assert 1 == 1, "printed"


def test_uses_os_system():
    """patterns.os_system - Uses os.system() which is a security risk."""
    # Don't actually run, just reference to trigger detection
    cmd = "echo test"
    if False:
        os.system(cmd)
    assert cmd == "echo test", "os.system reference"


# =============================================================================
# ISOLATION ANALYZER
# =============================================================================


def test_modifies_global_state():
    """isolation.global_modification - Modifies global variable."""
    global _global_counter
    _global_counter += 1
    assert _global_counter > 0, "global modified"


class TestClassState:
    """Class with shared state issues."""

    shared_list: list[int] = []

    def test_modifies_class_attr(self):
        """isolation.class_attribute_modification - Modifies class attribute."""
        TestClassState.shared_list.append(1)
        assert len(TestClassState.shared_list) > 0, "class state modified"


# =============================================================================
# SMELLS ANALYZER
# =============================================================================


def test_duplicate_assertions():
    """smells.duplicate_assert - Same assertion repeated."""
    x = 1
    assert x == 1, "first check"
    assert x == 1, "duplicate check"


@pytest.mark.skip(reason="Demonstrating ignored test smell")
def test_skipped_test():
    """smells.ignored_test - Test is skipped."""
    assert True, "this won't run"


def foo_func():
    """Helper."""
    return 1


def bar_func():
    """Helper."""
    return 2


def baz_func():
    """Helper."""
    return 3


def qux_func():
    """Helper."""
    return 4


# =============================================================================
# HEALTHY TESTS (for comparison)
# =============================================================================


def test_healthy_descriptive_name_with_assertion():
    """A properly written test with good practices."""
    expected = 4
    result = 2 + 2
    assert result == expected, f"Expected {expected}, got {result}"


class TestHealthyClass:
    """A well-structured test class."""

    def test_uses_instance_state_not_class_state(self):
        """Uses instance attributes, not class attributes."""
        self.data = [1, 2, 3]
        assert len(self.data) == 3, "instance state is fine"


# ---------------------------------------------------------------------------
# Defect-finder rules not covered above.
#
# The rule set is deliberately narrow: anything ruff already catches (bare
# except, `is` with a literal, mutable defaults, print statements) was dropped,
# as were style-only smells. What remains is meant to be an actual defect.
# ---------------------------------------------------------------------------


def test_bare_patch_without_cleanup():
    """isolation.bare_patch - patch() with no context manager or decorator."""
    from unittest import mock

    mock.patch("os.getcwd")
    assert True


def test_mutates_environment():
    """isolation.env_mutation - leaks into other tests."""
    import os

    os.environ["MY_APP_TOKEN"] = "secret"
    assert os.environ["MY_APP_TOKEN"] == "secret"


def test_mutates_process_state():
    """isolation.process_mutation - os.chdir leaks into every later test.

    Guarded so this example suite stays hermetic. The analyzers read the AST,
    so the finding is reported whether or not the branch executes.
    """
    import os

    if os.environ.get("PYTEST_REVIEW_DEMO_UNSAFE"):
        os.chdir("/tmp")
    assert True


def test_swallows_assertion_failure():
    """smells.swallowed_assertion - the test can never fail."""
    try:
        assert 1 == 2
    except Exception:
        pass


def test_returns_early_skipping_assertions():
    """smells.early_return - everything below the return is dead."""
    value = compute_value()
    return
    assert value == 99


def test_reads_hardcoded_path():
    """patterns.hardcoded_path - not portable across machines."""
    import os

    assert os.path.exists("/home/ci/fixtures/data.json") is False


def test_calls_network():
    """patterns.slow_call - a real network call makes the test slow and flaky.

    Deliberately never executed: `requests` is not imported and the branch is
    unreachable, so the example suite performs no network I/O. Detection is
    static, so the finding is reported anyway.
    """
    import os

    if os.environ.get("PYTEST_REVIEW_DEMO_UNSAFE"):
        requests.get("https://example.com")  # noqa: F821
    assert True


def test_subprocess_without_check():
    """patterns.subprocess_no_check - a non-zero exit passes silently."""
    import subprocess

    subprocess.run(["true"])
    assert True


def compute_value():
    return 99


def test_asserts_on_a_generator(items):
    """assertions.always_true - the generator object is truthy; nothing is compared."""
    assert (x > 0 for x in items)


def test_asserts_uncalled_mock_method(mock_service):
    """assertions.uncalled_assertion - referenced, never called, so always true."""
    assert mock_service.assert_called_once


def test_only_asserts_inside_a_loop(items):
    """smells.vacuous_loop - passes without verifying anything if items is empty."""
    for item in items:
        assert item > 0


@pytest.fixture
def items():
    return [1, 2, 3]


@pytest.fixture
def mock_service():
    from unittest import mock

    m = mock.Mock()
    m()
    return m


@mock.patch("os.getcwd")
def test_asserts_on_the_thing_it_patched(mock_getcwd):
    """assertions.mock_tautology - verifies unittest.mock, not any real code.

    The test patches os.getcwd, then asserts that os.getcwd returns what it was
    just told to return. No application code is involved at any point.
    """
    import os

    mock_getcwd.return_value = "/fake"
    assert os.getcwd() == "/fake"
