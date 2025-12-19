"""Analyzer for test complexity."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from pytest_review.analyzers.base import (
    AnalyzerResult,
    Issue,
    Severity,
    StaticAnalyzer,
    TestItemInfo,
)

if TYPE_CHECKING:
    from pytest_review.config import ReviewConfig


class ComplexityVisitor(ast.NodeVisitor):
    """AST visitor that measures code complexity."""

    def __init__(self) -> None:
        self.statement_count = 0
        self.max_depth = 0
        self.cyclomatic_complexity = 1  # Base complexity
        self._current_depth = 0

    def _count_statement(self) -> None:
        """Increment statement counter."""
        self.statement_count += 1

    def _enter_scope(self) -> None:
        """Enter a nested scope."""
        self._current_depth += 1
        self.max_depth = max(self.max_depth, self._current_depth)

    def _exit_scope(self) -> None:
        """Exit a nested scope."""
        self._current_depth -= 1

    # Statement counting
    def visit_Assign(self, node: ast.Assign) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Pass(self, node: ast.Pass) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Break(self, node: ast.Break) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Continue(self, node: ast.Continue) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self._count_statement()
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._count_statement()
        self.generic_visit(node)

    # Cyclomatic complexity - count decision points
    def visit_If(self, node: ast.If) -> None:
        self._count_statement()
        self.cyclomatic_complexity += 1
        # Count elif branches
        for child in node.orelse:
            if isinstance(child, ast.If):
                self.cyclomatic_complexity += 1
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_For(self, node: ast.For) -> None:
        self._count_statement()
        self.cyclomatic_complexity += 1
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_While(self, node: ast.While) -> None:
        self._count_statement()
        self.cyclomatic_complexity += 1
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.cyclomatic_complexity += 1
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_With(self, node: ast.With) -> None:
        self._count_statement()
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_Try(self, node: ast.Try) -> None:
        self._count_statement()
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # Each 'and'/'or' adds a decision point
        self.cyclomatic_complexity += len(node.values) - 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        # Ternary expression
        self.cyclomatic_complexity += 1
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._count_statement()
        for generator in node.generators:
            self.cyclomatic_complexity += 1
            self.cyclomatic_complexity += len(generator.ifs)
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._count_statement()
        for generator in node.generators:
            self.cyclomatic_complexity += 1
            self.cyclomatic_complexity += len(generator.ifs)
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._count_statement()
        for generator in node.generators:
            self.cyclomatic_complexity += 1
            self.cyclomatic_complexity += len(generator.ifs)
        self.generic_visit(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        for generator in node.generators:
            self.cyclomatic_complexity += 1
            self.cyclomatic_complexity += len(generator.ifs)
        self.generic_visit(node)


class ComplexityAnalyzer(StaticAnalyzer):
    """Analyzes test complexity."""

    name = "complexity"
    description = "Checks for overly complex tests"

    def __init__(self, config: ReviewConfig) -> None:
        super().__init__(config)
        self._max_statements = int(self.get_option("max_statements", 20) or 20)
        self._max_depth = int(self.get_option("max_depth", 3) or 3)
        self._max_complexity = int(self.get_option("max_complexity", 5) or 5)

    def _analyze_ast(self, test: TestItemInfo, result: AnalyzerResult) -> None:
        visitor = ComplexityVisitor()
        visitor.visit(test.node)

        # Check statement count
        if visitor.statement_count > self._max_statements:
            result.add_issue(
                Issue(
                    rule="complexity.too_many_statements",
                    message=f"Test has {visitor.statement_count} statements "
                    f"(maximum {self._max_statements})",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=test.name,
                    suggestion="Break down into smaller, focused tests or extract helper functions",
                )
            )

        # Check nesting depth
        if visitor.max_depth > self._max_depth:
            result.add_issue(
                Issue(
                    rule="complexity.deep_nesting",
                    message=f"Test has nesting depth of {visitor.max_depth} "
                    f"(maximum {self._max_depth})",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=test.name,
                    suggestion="Reduce nesting by extracting conditions or using early returns",
                )
            )

        # Check cyclomatic complexity
        if visitor.cyclomatic_complexity > self._max_complexity:
            result.add_issue(
                Issue(
                    rule="complexity.high_cyclomatic",
                    message=f"Test has cyclomatic complexity of {visitor.cyclomatic_complexity} "
                    f"(maximum {self._max_complexity})",
                    severity=Severity.WARNING,
                    file_path=test.file_path,
                    line=test.line,
                    test_name=test.name,
                    suggestion="Simplify test logic or split into multiple tests",
                )
            )

        # Store metadata
        result.metadata["statement_count"] = visitor.statement_count
        result.metadata["max_depth"] = visitor.max_depth
        result.metadata["cyclomatic_complexity"] = visitor.cyclomatic_complexity
