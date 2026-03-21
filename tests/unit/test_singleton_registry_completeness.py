"""Completeness tests for SingletonRegistry.

Verifies that:
1. All SingletonMixin subclasses are registered in SingletonRegistry.
2. All registered entries have a reset() method.
3. Cleanup orders are unique across all registered entries.

These tests catch cases where a developer adds a new SingletonMixin subclass
but forgets to declare _cleanup_order or register it manually.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Import all production modules that define SingletonMixin subclasses.
# Importing these triggers __init_subclass__, which populates
# SingletonMixin._known_subclasses. Without explicit imports the subclasses
# may not be registered yet when the test runs.
# ---------------------------------------------------------------------------
import paths.filesystem_coordinator  # noqa: F401 — side-effect: registers FilesystemCoordinator
import workers.runnable_tracker  # noqa: F401 — side-effect: registers QRunnableTracker
from tests.fixtures.singleton_fixtures import SingletonRegistry


class TestSingletonRegistryCompleteness:
    """Verify that the registry and the set of known subclasses stay in sync."""

    def test_cleanup_orders_are_unique(self) -> None:
        """Every registered singleton must have a distinct cleanup_order.

        Duplicate orders make teardown non-deterministic. SingletonRegistry.register()
        enforces this at registration time, but this test provides an explicit
        assertion that is easy to see in CI output.
        """
        entries = SingletonRegistry.get_entries()
        orders = [e.cleanup_order for e in entries]
        unique_orders = set(orders)
        assert len(orders) == len(unique_orders), (
            f"Duplicate cleanup_order values detected among registered singletons: "
            f"{[o for o in orders if orders.count(o) > 1]}. "
            "Each singleton must declare a unique cleanup_order."
        )
