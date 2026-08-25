"""Golden regression suite: idiomatic, high-quality tests must stay warning-free.

Each entry below is a realistic, *correct* test idiom that the plugin has
previously false-positived:

- ``@mock.patch`` / ``@patch`` decorators   -> isolation.bare_patch
  (patching a dependency and asserting on the *code under test* -- asserting on the
  patched target itself is a tautology and is reported, see assertions.mock_tautology)
- ``excinfo.match(...)`` / ``str(excinfo.value)`` -> assertions.raises_without_match
- ``if/elif`` platform gate                 -> smells.conditional_test
- conditional ``pytest.skip`` / SkipTest   -> smells.conditional_test + ignored_test
- ``try/finally`` cleanup                  -> smells.try_except_in_test
- 2 bare asserts (the pytest norm)          -> smells.assertion_roulette
- None-guard + value assert                 -> assertions.low_value
- parametrize data params counted as fixtures (INFO, kept visible by design)
- guard early-return toggle                 -> smells.early_return

The rule is: no issue at WARNING or above for these idioms. All previously
false-positived rules are fixed; if this test fails, someone reintroduced a
false positive.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from pytest_review.analyzers.assertions import AssertionsAnalyzer
from pytest_review.analyzers.base import Severity, TestItemInfo
from pytest_review.analyzers.isolation import IsolationStaticAnalyzer
from pytest_review.analyzers.patterns import PatternsAnalyzer
from pytest_review.analyzers.smells import SmellsAnalyzer
from pytest_review.config import ReviewConfig

IDIOMATIC_TESTS: dict[str, str] = {
    "test_returns_cached_result": """
        from unittest import mock

        @mock.patch("pkg.svc.fetch")
        def test_returns_cached_result(mock_fetch):
            mock_fetch.return_value = {"key": 1}
            assert pkg.svc.describe() == "key=1"
    """,
    "test_patch_decorator_bare_name": """
        from unittest.mock import patch

        @patch("pkg.svc.fetch")
        def test_patch_decorator_bare_name(mock_fetch):
            mock_fetch.return_value = {"key": 2}
            assert pkg.svc.describe() == "key=2"
    """,
    "test_rejects_empty_name": """
        import pytest

        def test_rejects_empty_name():
            with pytest.raises(ValueError) as excinfo:
                validate("")
            excinfo.match("must not be empty")
    """,
    "test_reports_the_reason": """
        import pytest

        def test_reports_the_reason():
            with pytest.raises(ValueError) as excinfo:
                validate("")
            assert "must not be empty" in str(excinfo.value)
    """,
    "test_parses_response": """
        def test_parses_response():
            result = parse()
            assert result is not None
            assert result["status"] == 200
    """,
    "test_conditional_skip": """
        import sys

        import pytest

        def test_conditional_skip():
            if sys.platform == "win32":
                pytest.skip("unix-only")
            assert compute() == 42
    """,
    "test_multi_platform_gate": """
        import sys

        import pytest

        def test_multi_platform_gate():
            if sys.platform == "win32":
                pytest.skip("unix-only")
            elif sys.platform == "darwin":
                pytest.skip("linux-only")
            assert compute() == 42
    """,
    "test_guarded_raise_skip": """
        import sys
        from unittest import SkipTest

        def test_guarded_raise_skip():
            if sys.platform == "win32":
                raise SkipTest("unix-only")
            assert compute() == 42
    """,
    "test_writes_and_cleans_up": """
        def test_writes_and_cleans_up(tmp_path):
            f = tmp_path / "x.txt"
            try:
                f.write_text("data")
                assert f.read_text() == "data"
            finally:
                f.unlink(missing_ok=True)
    """,
    "test_sums_six_operands": """
        import pytest

        @pytest.mark.parametrize(
            "a,b,c,d,e,f,expected",
            [
                (1, 2, 3, 4, 5, 6, 21),
                (1, 1, 1, 1, 1, 1, 6),
                (2, 2, 2, 2, 2, 2, 12),
            ],
        )
        def test_sums_six_operands(a, b, c, d, e, f, expected):
            assert a + b + c + d + e + f == expected
    """,
    "test_user_can_login_with_valid_credentials": """
        def test_user_can_login_with_valid_credentials():
            user = build_user()
            assert user.is_authenticated is True
    """,
    "test_returns_three_users": """
        def test_returns_three_users():
            assert len(list_users()) == 3
    """,
    "test_uses_inner_helper": """
        def test_uses_inner_helper():
            def heavy_helper(x):
                total = 0
                for i in range(x):
                    total += i
                return total

            assert heavy_helper(10) == 45
    """,
    "test_guarded_early_return": """
        import os

        def test_guarded_early_return():
            if not os.environ.get("CI"):
                return
            assert compute() == 42
    """,
    "test_renders_home_url": """
        # expected output string, not a filesystem path
        def test_renders_home_url():
            html = render_url("/home/user/profile")
            assert html == '<a href="/home/user/profile">x</a>'
    """,
}


def _make_test_info(source: str, name: str) -> TestItemInfo:
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return TestItemInfo(
                name=name,
                file_path=Path("/test.py"),
                line=node.lineno,
                node=node,
                source=textwrap.dedent(source),
            )
    raise AssertionError(f"could not find function {name} in source")


def test_idiomatic_tests_have_no_warning_plus() -> None:
    config = ReviewConfig()
    analyzers = [
        AssertionsAnalyzer(config),
        PatternsAnalyzer(config),
        IsolationStaticAnalyzer(config),
        SmellsAnalyzer(config),
    ]

    violations: list[str] = []
    for name, source in IDIOMATIC_TESTS.items():
        info = _make_test_info(source, name)
        for analyzer in analyzers:
            result = analyzer.analyze(info)
            for issue in result.issues:
                if issue.severity in (Severity.WARNING, Severity.ERROR):
                    violations.append(
                        f"{name}: {issue.rule} ({issue.severity.value}) {issue.message}"
                    )

    assert not violations, (
        "idiomatic tests produced WARNING+ findings (false positives):\n"
        + "\n".join(sorted(violations))
    )


# Stubs backing the idiomatic snippets above, so the whole golden set can be
# executed as a real pytest module. Executing it is what keeps the entries
# *honest*: a snippet can be syntactically valid, be accepted by every analyzer,
# and still be code that cannot run -- which is how an invalid
# ``pytest.raises(X).match(...)`` chain once entered this file as a documented
# idiom. Parsing alone cannot catch that; running it can.
_STUB_PREAMBLE = """
import os
import sys
from unittest import mock, SkipTest
from unittest.mock import patch

import pytest

import pkg.svc


def validate(name):
    if not name:
        raise ValueError("must not be empty")
    return name


def compute():
    return 42


def build_user():
    return mock.Mock(is_authenticated=True)


def list_users():
    return ["a", "b", "c"]


def render_url(path):
    return '<a href="%s">x</a>' % path


def parse():
    return {"status": 200}
"""


def test_idiomatic_tests_actually_run(pytester: pytest.Pytester) -> None:
    """Every golden entry must be code that really runs and really passes.

    The WARNING+ check below proves the analyzers stay quiet on these snippets.
    It cannot prove the snippets are *correct* -- an entry asserting that a
    nonexistent API is idiomatic would pass it happily. This test closes that
    gap by executing them.
    """
    pkg_dir = pytester.mkpydir("pkg")
    (pkg_dir / "svc.py").write_text(
        "def fetch():\n"
        "    return {'key': 1}\n"
        "\n"
        "\n"
        "def describe():\n"
        "    return 'key=%d' % fetch()['key']\n"
    )

    module = _STUB_PREAMBLE + "\n\n" + "\n\n".join(
        textwrap.dedent(source).strip() for source in IDIOMATIC_TESTS.values()
    )
    pytester.makepyfile(test_golden_idioms=module)

    result = pytester.runpytest("-p", "no:cacheprovider")

    outcomes = result.parseoutcomes()
    assert outcomes.get("failed", 0) == 0
    assert outcomes.get("errors", 0) == 0
    assert outcomes.get("passed", 0) == len(IDIOMATIC_TESTS) + 2  # one entry is x3 parametrized
    assert result.ret == 0, "golden idioms must be runnable, passing tests"
