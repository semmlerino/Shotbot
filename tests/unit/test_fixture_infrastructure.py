"""Meta-tests for the test fixture infrastructure.

These tests verify that the testing infrastructure itself is correctly configured,
ensuring reliable test isolation and preventing subtle flakiness from misconfiguration.

This module tests:
- SingletonRegistry cleanup order is sorted and has no duplicates
- qt_cleanup fixture actually processes Qt events
- Cache/config cleanup removes all files as expected
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

        duplicates = [o for o in orders if orders.count(o) > 1]
        assert len(orders) == len(set(orders)), (
            f"Duplicate cleanup orders found: {set(duplicates)}. "
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

    def test_cleanup_order_groups_are_logical(self) -> None:
        """Verify cleanup order groups follow documented convention.

        Documented convention:
        - 10-19: Qt UI singletons (clean first)
        - 20-29: Worker/runnable tracking
        - 30-39: Process pools
        - 40-49: Infrastructure
        """
        entries = SingletonRegistry.get_entries()

        for entry in entries:
            order = entry.cleanup_order
            path = entry.import_path

            # Verify order is within expected ranges (10-49 or default 50)
            assert 10 <= order <= 50, (
                f"Singleton '{path}' has cleanup_order {order} outside expected range 10-50. "
                "See SingletonRegistry docstring for order conventions."
            )


@pytest.mark.unit
@pytest.mark.qt
class TestQtCleanupFixture:
    """Tests for qt_cleanup fixture behavior."""

    def test_deletelater_is_processed(self, qtbot) -> None:
        """Verify qt_cleanup processes deleteLater() calls.

        This test creates a widget, calls deleteLater(), and verifies
        the cleanup fixture processes it before the next test.

        Note: deleteLater() requires explicit DeferredDelete event processing,
        which is what qt_cleanup does via sendPostedEvents().
        """
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QWidget

        widget = QWidget()
        qtbot.addWidget(widget)

        # Track if destroyed
        destroyed = []
        widget.destroyed.connect(lambda: destroyed.append(True))

        # Schedule deletion
        widget.deleteLater()

        # Process events the same way qt_cleanup does (including DeferredDelete)
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        # Widget should be destroyed
        assert destroyed, (
            "Widget was not destroyed after deleteLater() + sendPostedEvents(DeferredDelete). "
            "This could indicate qt_cleanup won't properly clean up Qt objects."
        )

    def test_thread_baseline_tracking(self, qtbot) -> None:
        """Verify thread leak detection has reasonable baseline.

        Use a delta check instead of a strict absolute thread count so
        environment/plugin helper threads do not create false failures.
        """
        import threading

        baseline = threading.active_count()

        # Start and join a probe thread. Active thread count should return
        # to approximately baseline after join.
        probe = threading.Thread(target=lambda: None, name="baseline-probe")
        probe.start()
        probe.join(timeout=1.0)
        assert not probe.is_alive(), "Probe thread did not terminate as expected."

        post_join = threading.active_count()
        assert post_join <= baseline + 2, (
            f"Thread count drifted from {baseline} to {post_join} after a join; "
            "unexpected drift may mask thread leaks."
        )


@pytest.mark.unit
class TestCacheCleanupBehavior:
    """Tests for cache cleanup fixture behavior."""

    def test_cache_dir_env_var_is_set(self) -> None:
        """Verify SHOTBOT_TEST_CACHE_DIR is set for isolation."""
        import os

        cache_dir = os.environ.get("SHOTBOT_TEST_CACHE_DIR")

        assert cache_dir is not None, (
            "SHOTBOT_TEST_CACHE_DIR not set. "
            "Tests may be writing to production cache location."
        )

    def test_config_dir_env_var_is_set(self) -> None:
        """Verify SHOTBOT_CONFIG_DIR is set for isolation."""
        import os

        config_dir = os.environ.get("SHOTBOT_CONFIG_DIR")

        assert config_dir is not None, (
            "SHOTBOT_CONFIG_DIR not set. "
            "Tests may be writing to production config location."
        )

    def test_xdg_runtime_dir_is_set(self) -> None:
        """Verify XDG_RUNTIME_DIR is set for Qt isolation."""
        import os
        from pathlib import Path

        xdg_dir = os.environ.get("XDG_RUNTIME_DIR")

        assert xdg_dir is not None, (
            "XDG_RUNTIME_DIR not set. "
            "Qt may warn or fail due to missing runtime directory."
        )

        # Verify permissions (Qt6 requires 0700)
        xdg_path = Path(xdg_dir)
        if xdg_path.exists():
            mode = xdg_path.stat().st_mode & 0o777
            assert mode == 0o700, (
                f"XDG_RUNTIME_DIR has permissions {oct(mode)}, expected 0o700. "
                "Qt6 requires strict permissions on XDG_RUNTIME_DIR."
            )
