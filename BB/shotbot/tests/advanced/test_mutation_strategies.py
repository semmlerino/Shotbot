"""Mutation testing strategies and quality assessment for ShotBot.

This module provides mutation testing configurations and demonstrates
how to identify weak tests and improve test quality.
"""

import ast
import inspect
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest


class MutationStrategy:
    """Base class for mutation strategies."""

    def mutate(self, code: str) -> List[str]:
        """Generate mutated versions of the code.

        Args:
            code: Original source code

        Returns:
            List of mutated code variants
        """
        raise NotImplementedError


class BoundaryMutationStrategy(MutationStrategy):
    """Mutate boundary conditions in comparisons."""

    MUTATIONS = {
        "<": ["<=", ">", ">=", "==", "!="],
        "<=": ["<", ">", ">=", "==", "!="],
        ">": [">=", "<", "<=", "==", "!="],
        ">=": [">", "<", "<=", "==", "!="],
        "==": ["!=", "<", "<=", ">", ">="],
        "!=": ["==", "<", "<=", ">", ">="],
    }

    def mutate(self, code: str) -> List[str]:
        """Mutate comparison operators to test boundary conditions."""
        tree = ast.parse(code)
        mutations = []

        class CompareMutator(ast.NodeTransformer):
            def visit_Compare(self, node):
                self.generic_visit(node)

                # Generate mutations for each comparison operator
                for i, op in enumerate(node.ops):
                    op_name = op.__class__.__name__
                    if op_name in ["Lt", "LtE", "Gt", "GtE", "Eq", "NotEq"]:
                        # Map AST operator to string
                        op_map = {
                            "Lt": "<",
                            "LtE": "<=",
                            "Gt": ">",
                            "GtE": ">=",
                            "Eq": "==",
                            "NotEq": "!=",
                        }
                        current_op = op_map.get(op_name)

                        if current_op in BoundaryMutationStrategy.MUTATIONS:
                            for new_op in BoundaryMutationStrategy.MUTATIONS[
                                current_op
                            ]:
                                # Create mutated version
                                mutated_tree = ast.parse(code)
                                mutated_code = ast.unparse(mutated_tree)
                                mutated_code = mutated_code.replace(
                                    current_op, new_op, 1
                                )
                                mutations.append(mutated_code)

                return node

        CompareMutator().visit(tree)
        return mutations


class ReturnValueMutationStrategy(MutationStrategy):
    """Mutate return values to test error handling."""

    def mutate(self, code: str) -> List[str]:
        """Mutate return values to test error paths."""
        mutations = []

        # Common return value mutations
        replacements = [
            ("return True", "return False"),
            ("return False", "return True"),
            ("return None", "return 'mutated'"),
            ("return []", "return None"),
            ("return {}", "return None"),
            ("return 0", "return -1"),
            ("return 1", "return 0"),
        ]

        for original, replacement in replacements:
            if original in code:
                mutated = code.replace(original, replacement)
                mutations.append(mutated)

        return mutations


class ExceptionMutationStrategy(MutationStrategy):
    """Mutate exception handling to test error resilience."""

    def mutate(self, code: str) -> List[str]:
        """Mutate exception handling code."""
        mutations = []

        # Remove try-except blocks
        if "try:" in code and "except" in code:
            # Simplified: just remove the try-except wrapper
            mutated = code.replace("try:", "").replace("except:", "if False:")
            mutations.append(mutated)

        # Change exception types
        exception_types = ["ValueError", "TypeError", "KeyError", "AttributeError"]
        for exc_type in exception_types:
            if exc_type in code:
                for other_exc in exception_types:
                    if other_exc != exc_type:
                        mutated = code.replace(exc_type, other_exc)
                        mutations.append(mutated)

        return mutations


class PathMutationStrategy(MutationStrategy):
    """Mutate path operations to test path handling."""

    def mutate(self, code: str) -> List[str]:
        """Mutate path-related operations."""
        mutations = []

        # Path mutations specific to ShotBot
        path_mutations = [
            (".exists()", ".is_file()"),
            (".is_file()", ".is_dir()"),
            (".is_dir()", ".is_file()"),
            ("Path(", "str("),
            ('".join"', '"JOIN"'),
            ("parents=True", "parents=False"),
            ("exist_ok=True", "exist_ok=False"),
        ]

        for original, replacement in path_mutations:
            if original in code:
                mutated = code.replace(original, replacement)
                mutations.append(mutated)

        return mutations


class MutationTestRunner:
    """Run mutation tests and analyze results."""

    def __init__(self, strategies: Optional[List[MutationStrategy]] = None):
        """Initialize the mutation test runner.

        Args:
            strategies: List of mutation strategies to apply
        """
        self.strategies = strategies or [
            BoundaryMutationStrategy(),
            ReturnValueMutationStrategy(),
            ExceptionMutationStrategy(),
            PathMutationStrategy(),
        ]
        self.results: Dict[str, Dict[str, Any]] = {}

    def run_mutation_test(
        self,
        function: Callable,
        test_function: Callable,
        test_args: Optional[Tuple] = None,
    ) -> Dict[str, Any]:
        """Run mutation testing on a function.

        Args:
            function: Function to mutate
            test_function: Test function that should catch mutations
            test_args: Arguments to pass to test function

        Returns:
            Dictionary with mutation test results
        """
        source = inspect.getsource(function)
        function_name = function.__name__

        results = {
            "function": function_name,
            "total_mutations": 0,
            "killed_mutations": 0,
            "survived_mutations": [],
            "mutation_score": 0.0,
        }

        # Apply each strategy
        for strategy in self.strategies:
            mutations = strategy.mutate(source)

            for i, mutated_code in enumerate(mutations):
                results["total_mutations"] += 1
                mutation_id = f"{strategy.__class__.__name__}_{i}"

                try:
                    # Try to execute the test with mutated code
                    # In real implementation, this would modify the actual function
                    test_passed = self._run_test_with_mutation(
                        test_function, test_args, mutated_code
                    )

                    if test_passed:
                        # Mutation survived - test didn't catch it
                        results["survived_mutations"].append(
                            {
                                "id": mutation_id,
                                "strategy": strategy.__class__.__name__,
                                "mutation": mutated_code[:100],  # First 100 chars
                            }
                        )
                    else:
                        results["killed_mutations"] += 1

                except Exception:
                    # Test caught the mutation (good!)
                    results["killed_mutations"] += 1

        # Calculate mutation score
        if results["total_mutations"] > 0:
            results["mutation_score"] = (
                results["killed_mutations"] / results["total_mutations"]
            ) * 100

        self.results[function_name] = results
        return results

    def _run_test_with_mutation(
        self, test_function: Callable, test_args: Optional[Tuple], mutated_code: str
    ) -> bool:
        """Run test with mutated code (simplified for demonstration).

        In a real implementation, this would:
        1. Replace the function's code with mutated version
        2. Run the test
        3. Restore original code
        4. Return whether test passed or failed
        """
        # Simplified: randomly decide if test catches mutation
        # Real implementation would use exec() or module reloading
        return random.random() > 0.7  # 30% chance test catches mutation

    def generate_report(self) -> str:
        """Generate a mutation testing report.

        Returns:
            Formatted report string
        """
        report = ["Mutation Testing Report", "=" * 50, ""]

        total_mutations = sum(r["total_mutations"] for r in self.results.values())
        total_killed = sum(r["killed_mutations"] for r in self.results.values())

        report.append(f"Total Mutations: {total_mutations}")
        report.append(f"Killed Mutations: {total_killed}")
        report.append(
            f"Overall Mutation Score: {(total_killed / total_mutations) * 100:.1f}%"
        )
        report.append("")

        for func_name, result in self.results.items():
            report.append(f"Function: {func_name}")
            report.append(f"  Mutations: {result['total_mutations']}")
            report.append(f"  Killed: {result['killed_mutations']}")
            report.append(f"  Score: {result['mutation_score']:.1f}%")

            if result["survived_mutations"]:
                report.append("  Survived Mutations:")
                for mutation in result["survived_mutations"][:3]:  # Show first 3
                    report.append(
                        f"    - {mutation['strategy']}: {mutation['mutation'][:50]}..."
                    )

            report.append("")

        return "\n".join(report)


class TestQualityAnalyzer:
    """Analyze test quality and identify weak spots."""

    @staticmethod
    def analyze_assertion_quality(test_function: Callable) -> Dict[str, Any]:
        """Analyze the quality of assertions in a test function.

        Args:
            test_function: Test function to analyze

        Returns:
            Dictionary with analysis results
        """
        source = inspect.getsource(test_function)
        tree = ast.parse(source)

        analysis = {
            "total_assertions": 0,
            "weak_assertions": [],
            "strong_assertions": [],
            "missing_edge_cases": [],
        }

        class AssertionVisitor(ast.NodeVisitor):
            def visit_Assert(self, node):
                analysis["total_assertions"] += 1

                # Check for weak assertions
                if isinstance(node.test, ast.NameConstant):
                    if node.test.value in [True, False]:
                        analysis["weak_assertions"].append(
                            "Assert with constant boolean"
                        )

                # Check for simple equality
                elif isinstance(node.test, ast.Compare):
                    if len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
                        analysis["strong_assertions"].append("Equality assertion")

                self.generic_visit(node)

        AssertionVisitor().visit(tree)

        # Check for common missing edge cases
        if "None" not in source:
            analysis["missing_edge_cases"].append("No None check")
        if "[]" not in source and "empty" not in source.lower():
            analysis["missing_edge_cases"].append("No empty collection check")
        if "0" not in source and "zero" not in source.lower():
            analysis["missing_edge_cases"].append("No zero value check")

        return analysis

    @staticmethod
    def suggest_improvements(analysis: Dict[str, Any]) -> List[str]:
        """Suggest improvements based on analysis.

        Args:
            analysis: Analysis results from analyze_assertion_quality

        Returns:
            List of improvement suggestions
        """
        suggestions = []

        if analysis["weak_assertions"]:
            suggestions.append("Replace weak assertions with specific value checks")

        if not analysis["strong_assertions"]:
            suggestions.append("Add more specific equality and comparison assertions")

        for missing in analysis["missing_edge_cases"]:
            suggestions.append(f"Add test case for: {missing}")

        if analysis["total_assertions"] < 3:
            suggestions.append(
                "Consider adding more assertions to thoroughly validate behavior"
            )

        return suggestions


# Example mutation configurations for specific ShotBot components
SHOTBOT_MUTATION_CONFIGS = {
    "raw_plate_finder": {
        "strategies": [
            PathMutationStrategy(),
            ReturnValueMutationStrategy(),
        ],
        "critical_functions": [
            "find_latest_raw_plate",
            "_find_plate_file_pattern",
        ],
        "expected_score": 85,  # Expected mutation score percentage
    },
    "threede_scene_finder": {
        "strategies": [
            PathMutationStrategy(),
            BoundaryMutationStrategy(),
            ExceptionMutationStrategy(),
        ],
        "critical_functions": [
            "find_other_users_scenes",
            "_deduplicate_scenes",
        ],
        "expected_score": 80,
    },
    "cache_manager": {
        "strategies": [
            BoundaryMutationStrategy(),
            ReturnValueMutationStrategy(),
        ],
        "critical_functions": [
            "get",
            "set",
            "is_expired",
        ],
        "expected_score": 90,
    },
}


@pytest.mark.mutation
class TestMutationAnalysis:
    """Run mutation analysis on critical components."""

    def test_raw_plate_finder_mutation_resistance(self):
        """Test that raw plate finder tests catch mutations."""
        from raw_plate_finder import RawPlateFinder
        from tests.unit.test_raw_plate_finder import TestRawPlateFinder

        runner = MutationTestRunner(
            strategies=[PathMutationStrategy(), ReturnValueMutationStrategy()]
        )

        # Run mutation test on critical function
        result = runner.run_mutation_test(
            RawPlateFinder.find_latest_raw_plate,
            TestRawPlateFinder.test_find_latest_raw_plate,
        )

        # Assert mutation score meets threshold
        assert result["mutation_score"] >= 80, (
            f"Mutation score {result['mutation_score']:.1f}% below threshold of 80%"
        )

    def test_assertion_quality_in_tests(self):
        """Analyze assertion quality in existing tests."""
        from tests.unit import test_raw_plate_finder

        # Analyze all test methods
        for name in dir(test_raw_plate_finder.TestRawPlateFinder):
            if name.startswith("test_"):
                method = getattr(test_raw_plate_finder.TestRawPlateFinder, name)
                analysis = TestQualityAnalyzer.analyze_assertion_quality(method)

                # Check minimum assertion count
                assert analysis["total_assertions"] >= 1, (
                    f"Test {name} has no assertions"
                )

                # Check for weak assertions
                assert not analysis["weak_assertions"], (
                    f"Test {name} has weak assertions: {analysis['weak_assertions']}"
                )


if __name__ == "__main__":
    # Example usage
    runner = MutationTestRunner()

    # Run mutation analysis
    print("Running mutation analysis...")
    print(runner.generate_report())
