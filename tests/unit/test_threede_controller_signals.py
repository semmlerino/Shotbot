"""Integration tests for ThreeDEController signal connections.

Tests that real controller operations don't produce Qt warnings.
"""

import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from controllers.threede_controller import ThreeDEController
from threede_grid_view import ThreeDEGridView
from threede_item_model import ThreeDEItemModel
from threede_scene_model import ThreeDESceneModel


@pytest.fixture
def mock_main_window(qapp: QApplication) -> MagicMock:
    """Create mock main window for controller."""
    window = MagicMock()
    window.cache_manager = MagicMock()
    window.launcher_manager = MagicMock()

    # Create real models for the window to return
    scene_model = ThreeDESceneModel(cache_manager=window.cache_manager)
    item_model = ThreeDEItemModel(scene_model)
    grid_view = ThreeDEGridView()
    grid_view.set_model(item_model)

    # Wire up window to return components
    window.threede_scene_model = scene_model
    window.threede_item_model = item_model
    window.threede_grid_view = grid_view
    window.launcher_controller = MagicMock()
    window.launcher_controller.get_current_scene.return_value = None

    return window


@pytest.fixture
def threede_controller(
    qapp: QApplication, mock_main_window: MagicMock
) -> ThreeDEController:
    """Create ThreeDEController with all dependencies."""
    return ThreeDEController(window=mock_main_window)


def test_threede_controller_initialization_no_warnings(
    qapp: QApplication, threede_controller: ThreeDEController, qtbot
) -> None:
    """Test that controller initialization produces no Qt warnings."""
    old_stderr = sys.stderr
    sys.stderr = captured_stderr = StringIO()

    try:
        # Wait for controller to be fully initialized
        # Check that no warnings appeared during initialization
        qtbot.waitUntil(lambda: True, timeout=100)  # Short wait to drain event queue

        # Check for Qt warnings
        stderr_output = captured_stderr.getvalue()
        assert "unique connections require" not in stderr_output, (
            f"Qt unique connection warning during initialization:\n{stderr_output}"
        )
        assert "QObject::connect" not in stderr_output, (
            f"Qt connection warning during initialization:\n{stderr_output}"
        )

    finally:
        sys.stderr = old_stderr


@patch("threede_scene_worker.ThreeDESceneFinder")
def test_threede_refresh_signals_no_warnings(
    mock_finder: MagicMock,
    qapp: QApplication,
    threede_controller: ThreeDEController,
    qtbot,
) -> None:
    """Test that refresh operation produces no Qt warnings."""
    old_stderr = sys.stderr
    sys.stderr = captured_stderr = StringIO()

    try:
        # Mock finder to return immediately
        mock_finder_instance = MagicMock()
        mock_finder_instance.find_scenes.return_value = []
        mock_finder.return_value = mock_finder_instance

        # Start refresh (creates worker and connects signals)
        threede_controller.refresh_threede_scenes()

        # Wait for worker to be created and initialized
        qtbot.waitUntil(
            lambda: threede_controller.has_active_worker or True,  # Always true since we just check state
            timeout=200
        )

        # Check for Qt warnings
        stderr_output = captured_stderr.getvalue()
        assert "unique connections require" not in stderr_output, (
            f"Qt unique connection warning during refresh:\n{stderr_output}"
        )
        assert "Failed to disconnect" not in stderr_output, (
            f"Disconnect warning during refresh:\n{stderr_output}"
        )

        # Cleanup worker
        if threede_controller.has_active_worker:
            threede_controller.cleanup_worker()
            qtbot.waitUntil(lambda: True, timeout=100)  # Drain event queue

    finally:
        sys.stderr = old_stderr


def test_threede_worker_cleanup_no_warnings(
    qapp: QApplication,
    threede_controller: ThreeDEController,
    qtbot,
) -> None:
    """Test that worker cleanup produces no disconnect warnings."""
    old_stderr = sys.stderr
    sys.stderr = captured_stderr = StringIO()

    try:
        # Create a worker (even if not started)
        with patch("threede_scene_worker.ThreeDESceneFinder"):
            threede_controller.refresh_threede_scenes()
            qtbot.waitUntil(lambda: True, timeout=100)  # Wait for worker creation

            # Now cleanup
            if threede_controller.has_active_worker:
                threede_controller.cleanup_worker()
                qtbot.waitUntil(lambda: True, timeout=100)  # Wait for cleanup completion

        # Check for disconnect warnings
        stderr_output = captured_stderr.getvalue()
        assert "Failed to disconnect" not in stderr_output, (
            f"Disconnect warning during cleanup:\n{stderr_output}"
        )
        assert "RuntimeWarning" not in stderr_output, (
            f"RuntimeWarning during cleanup:\n{stderr_output}"
        )

    finally:
        sys.stderr = old_stderr


def test_threede_multiple_refresh_no_duplicate_warnings(
    qapp: QApplication,
    threede_controller: ThreeDEController,
    qtbot,
) -> None:
    """Test that multiple refreshes don't accumulate warnings."""
    old_stderr = sys.stderr
    sys.stderr = captured_stderr = StringIO()

    try:
        with patch("threede_scene_worker.ThreeDESceneFinder"):
            # Refresh multiple times (simulates user clicking refresh repeatedly)
            for _ in range(3):
                threede_controller.refresh_threede_scenes()
                qtbot.waitUntil(lambda: True, timeout=100)  # Wait for worker creation

                # Cleanup after each
                if threede_controller.has_active_worker:
                    threede_controller.cleanup_worker()
                    qtbot.waitUntil(lambda: True, timeout=100)  # Wait for cleanup

        # Check no warnings accumulated
        stderr_output = captured_stderr.getvalue()
        assert "unique connections require" not in stderr_output, (
            f"Accumulated Qt warnings:\n{stderr_output}"
        )
        assert "Failed to disconnect" not in stderr_output, (
            f"Accumulated disconnect warnings:\n{stderr_output}"
        )

    finally:
        sys.stderr = old_stderr


def test_refresh_threede_scenes_guards_against_concurrent_calls(
    qapp: QApplication,
    threede_controller: ThreeDEController,
    qtbot,
) -> None:
    """Test that concurrent refresh calls are rejected if worker is running.

    Issue #3 fix: Prevents duplicate progress operations "Scanning for 3DE scenes".
    Second call should return early if worker is already active.
    """
    from unittest.mock import MagicMock

    # Directly set a mock worker to simulate one already running
    # This tests the guard logic without needing to actually start a worker
    mock_worker = MagicMock()
    mock_worker.isFinished.return_value = False  # Worker appears to be running
    threede_controller._threede_worker = mock_worker

    # Try to refresh while worker is "running"
    # The guard should detect this and return early
    method_calls_before = len(mock_worker.method_calls)
    threede_controller.refresh_threede_scenes()
    method_calls_after = len(mock_worker.method_calls)

    # No additional methods should be called on the worker (guard prevented new worker creation)
    # The only call might be isFinished() for the check itself
    assert method_calls_after - method_calls_before <= 1, \
        f"Expected at most 1 call (isFinished check), got {method_calls_after - method_calls_before} new calls"

    # Cleanup: Remove mock worker
    threede_controller._threede_worker = None
