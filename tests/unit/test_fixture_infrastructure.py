"""Essential tests for the test fixture infrastructure.

This module tests the core assumptions of the testing infrastructure:
- SingletonRegistry cleanup order is sorted (deterministic cleanup)
- All singletons have valid reset() methods (test isolation)
- No duplicate cleanup orders (predictable behavior)
- All singleton imports are valid (registry consistency)
"""

from __future__ import annotations

import pytest

from tests.fixtures.singleton_registry import SingletonRegistry


@pytest.mark.unit
class TestSingletonRegistry:
    """Tests for SingletonRegistry configuration."""

    def test_cleanup_order_is_sorted(self) -> None:
        """Verify cleanup order is monotonically increasing.

        The registry should maintain entries sorted by cleanup_order
        to ensure deterministic cleanup sequence.
        """
        entries = SingletonRegistry.get_entries()
        orders = [e.cleanup_order for e in entries]

        assert orders == sorted(orders), (
            f"Cleanup order is not sorted: {orders}. "
            "This could cause unpredictable cleanup behavior."
        )

    def test_no_duplicate_cleanup_orders(self) -> None:
        """Verify no two singletons share the same cleanup order.

        Duplicate cleanup orders can cause unpredictable cleanup sequence
        since Python's sort is stable but order is undefined for equal keys.
        """
        entries = SingletonRegistry.get_entries()
        orders = [e.cleanup_order for e in entries]

        assert len(orders) == len(set(orders)), (
            "Duplicate cleanup orders found. "
            "Each singleton should have a unique cleanup_order."
        )

    def test_all_entries_have_valid_import_paths(self) -> None:
        """Verify all registered singletons can be imported.

        This catches cases where a singleton module is renamed/moved
        but the registry wasn't updated.
        """
        entries = SingletonRegistry.get_entries()
        failed_imports: list[str] = []

        for entry in entries:
            singleton_cls = SingletonRegistry._get_class(entry.import_path)
            if singleton_cls is None:
                failed_imports.append(entry.import_path)

        assert not failed_imports, (
            f"Failed to import singletons: {failed_imports}. "
            "Check if modules were renamed/moved."
        )

    def test_all_entries_have_reset_method(self) -> None:
        """Verify all registered singletons have reset() classmethod.

        This is a sanity check - pytest_configure also verifies this,
        but having it as a test makes failures clearer.
        """
        missing = SingletonRegistry.verify_all_have_reset()

        assert not missing, (
            f"Singletons missing reset(): {missing}. "
            "Every singleton MUST implement reset() for test isolation."
        )
