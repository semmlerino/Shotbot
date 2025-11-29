"""Configuration and fixtures for integration tests."""

# Standard library imports
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# Third-party imports
import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers",
        "performance: mark test as a performance benchmark",
    )
    config.addinivalue_line("markers", "stress: mark test as a stress test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Modify test collection to handle custom markers."""
    # Add integration marker to all tests in this directory
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def integration_temp_dir() -> Iterator[Path]:
    """Session-scoped temporary directory for integration tests."""
    with tempfile.TemporaryDirectory(prefix="shotbot_integration_") as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def launcher_test_env(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """Fixture providing isolated launcher test environment.

    Provides:
        - config_dir: Path to config directory
        - test_shot: Dict with test shot data
        - qt_objects: List for tracking Qt objects (auto-cleaned)

    Qt cleanup is handled automatically after test completes.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    test_shot = {
        "show": "test_show",
        "sequence": "seq01",
        "shot": "0010",
        "workspace_path": "/shows/test_show/shots/seq01/seq01_0010",
        "name": "seq01_0010",
    }

    qt_objects: list[Any] = []

    yield {
        "config_dir": config_dir,
        "test_shot": test_shot,
        "qt_objects": qt_objects,
        "tmp_path": tmp_path,
    }

    # Cleanup Qt objects (Qt Widget Guidelines)
    from tests.test_helpers import process_qt_events

    for obj in qt_objects:
        try:
            if hasattr(obj, "stop_all_workers"):
                obj.stop_all_workers()
            if hasattr(obj, "deleteLater"):
                obj.deleteLater()
        except Exception:
            pass  # Ignore cleanup errors

    process_qt_events()


@pytest.fixture
def launcher_controller_target(qtbot: Any) -> Any:
    """Create a mock target object for LauncherController testing.

    Uses spec=LauncherTarget to ensure the mock only has attributes defined
    in the Protocol. This catches bugs where code accesses attributes that
    don't exist on the real MainWindow.
    """
    from unittest.mock import Mock

    from PySide6.QtWidgets import QMenu, QStatusBar

    from controllers.launcher_controller import LauncherTarget

    # Use spec= to constrain mock to Protocol attributes only
    target = Mock(spec=LauncherTarget)
    target.command_launcher = Mock()
    target.launcher_manager = None
    target.right_panel = Mock()
    target.right_panel.get_dcc_options = Mock(return_value={
        "open_latest_scene": True,
        "include_raw_plate": False,
    })
    target.log_viewer = Mock()
    target.status_bar = QStatusBar(parent=None)
    target.custom_launcher_menu = QMenu(parent=None)
    target.update_status = Mock()

    return target


@pytest.fixture
def threede_controller_target(qtbot: Any, launcher_controller_target: Any) -> Any:
    """Create a mock target object for ThreeDEController testing.

    Uses spec=ThreeDETarget to ensure the mock only has attributes defined
    in the Protocol. This catches bugs where code accesses attributes that
    don't exist on the real MainWindow.
    """
    from unittest.mock import Mock

    from PySide6.QtWidgets import QStatusBar

    from controllers.launcher_controller import LauncherController
    from controllers.threede_controller import ThreeDETarget

    # Use spec= to constrain mock to Protocol attributes only
    # This prevents over-mocking and catches missing attribute bugs
    target = Mock(spec=ThreeDETarget)

    # Widget references (must match Protocol)
    target.threede_shot_grid = Mock()
    target.right_panel = Mock()
    target.right_panel.get_dcc_options = Mock(return_value={
        "open_latest_scene": True,
        "include_raw_plate": False,
    })
    target.status_bar = QStatusBar(parent=None)

    # Model references (must match Protocol)
    target.shot_model = Mock()
    target.threede_scene_model = Mock()
    target.threede_item_model = Mock()
    target.cache_manager = Mock()
    target.command_launcher = Mock()

    # Create a real LauncherController for this target
    target.launcher_controller = LauncherController(launcher_controller_target)

    # Methods (must match Protocol)
    target.setWindowTitle = Mock()
    target.update_status = Mock()
    target.update_launcher_menu_availability = Mock()
    target.enable_custom_launcher_buttons = Mock()
    target.launch_app = Mock()
    target.closing = False

    return target


# NOTE: Singleton isolation is now handled by the root conftest.py via
# tests/fixtures/singleton_isolation.py (cleanup_state fixture, autouse=True)
# The redundant integration_test_isolation fixture was removed.
