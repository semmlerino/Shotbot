"""Unit tests for controllers/threede_controller.py.

Tests for ThreeDEController which manages 3DE scene discovery,
signal routing, and worker thread management.

Following UNIFIED_TESTING_V2.md best practices:
- Test behavior using protocol-based test doubles
- Cover signal routing, discovery callbacks, scene selection
- Test thread safety and worker management
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from controllers.threede_controller import ThreeDEController
from progress_manager import ProgressManager
from tests.fixtures.test_doubles import SignalDouble
from threede_scene_model import ThreeDEScene


if TYPE_CHECKING:
    from shot_model import Shot


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# ============================================================================
# Test Doubles
# ============================================================================


class ThreeDEGridViewDouble:
    """Test double for ThreeDEGridView."""

    __test__ = False

    def __init__(self) -> None:
        self.scene_selected = SignalDouble()
        self.scene_double_clicked = SignalDouble()
        self.recover_crashes_requested = SignalDouble()
        self.show_filter_requested = SignalDouble()
        self.artist_filter_requested = SignalDouble()
        self.text_filter_requested = SignalDouble()
        self._show_filter_populated = False
        self._artist_filter_populated = False
        self._selected_scene: ThreeDEScene | None = None

    def populate_show_filter(self, model: Any) -> None:
        """Populate show filter from model."""
        self._show_filter_populated = True

    def populate_artist_filter(self, model: Any) -> None:
        """Populate artist filter from model."""
        self._artist_filter_populated = True

    @property
    def selected_scene(self) -> ThreeDEScene | None:
        """Get currently selected scene."""
        return self._selected_scene


class ThreeDESceneModelDouble:
    """Test double for ThreeDESceneModel."""

    __test__ = False

    def __init__(self, cache_manager: Any = None) -> None:
        self._scenes: list[ThreeDEScene] = []
        self._show_filter: str | None = None
        self._artist_filter: str | None = None
        self._text_filter: str | None = None
        self.cache_manager = cache_manager or SceneDiskCacheDouble()

    @property
    def scenes(self) -> list[ThreeDEScene]:
        return self._scenes

    @scenes.setter
    def scenes(self, value: list[ThreeDEScene]) -> None:
        self._scenes = value

    def set_scenes(self, scenes: list[ThreeDEScene]) -> None:
        self._scenes = scenes

    def deduplicate_scenes_by_shot(
        self, scenes: list[ThreeDEScene]
    ) -> list[ThreeDEScene]:
        """Simple deduplication for testing."""
        seen: dict[str, ThreeDEScene] = {}
        for scene in scenes:
            key = f"{scene.show}_{scene.sequence}_{scene.shot}"
            if key not in seen or scene.modified_time > seen[key].modified_time:
                seen[key] = scene
        return list(seen.values())

    def set_text_filter(self, text: str | None) -> None:
        """Set text filter."""
        self._text_filter = text

    def set_show_filter(self, show: str | None) -> None:
        """Set show filter."""
        self._show_filter = show

    def get_show_filter(self) -> str | None:
        """Get show filter."""
        return self._show_filter

    def set_artist_filter(self, artist: str | None) -> None:
        """Set artist filter."""
        self._artist_filter = artist

    def get_artist_filter(self) -> str | None:
        """Get artist filter."""
        return self._artist_filter

    def get_unique_shows(self) -> list[str]:
        """Get unique shows."""
        return sorted({scene.show for scene in self._scenes})

    def get_unique_artists(self) -> list[str]:
        """Get unique artists."""
        return sorted({scene.user for scene in self._scenes})

    def get_filtered_scenes(self) -> list[ThreeDEScene]:
        """Get filtered scenes."""
        scenes = self._scenes
        if self._show_filter:
            scenes = [s for s in scenes if s.show == self._show_filter]
        if self._artist_filter:
            scenes = [s for s in scenes if s.user == self._artist_filter]
        if self._text_filter:
            scenes = [
                s for s in scenes if self._text_filter.lower() in s.full_name.lower()
            ]
        return scenes

    def to_dict(self) -> list[dict[str, Any]]:
        """Convert scenes to dict list for caching."""
        return [s.to_dict() for s in self._scenes]


class ThreeDEItemModelDouble:
    """Test double for ThreeDEItemModel."""

    __test__ = False

    def __init__(self) -> None:
        self._loading_state = False
        self._source_model: ThreeDESceneModelDouble | None = None
        self._filter_show: str = ""
        self._filter_text: str = ""
        self._scenes: list[ThreeDEScene] = []
        self._items: list[ThreeDEScene] = []

    def set_loading_state(self, loading: bool) -> None:
        self._loading_state = loading

    def setSourceModel(self, model: ThreeDESceneModelDouble) -> None:
        self._source_model = model

    def setFilterFixedString(self, text: str) -> None:
        self._filter_text = text

    def invalidateFilter(self) -> None:
        pass

    def set_show_filter(self, model: Any, show: str | None) -> None:
        self._filter_show = show or ""
        if hasattr(model, "set_show_filter"):
            model.set_show_filter(show)
        if hasattr(model, "get_filtered_scenes"):
            self.set_scenes(model.get_filtered_scenes())

    def set_scenes(self, scenes: list[ThreeDEScene]) -> None:
        """Set scenes in the model."""
        self._scenes = scenes
        self._items = list(scenes)

    def set_items(self, items: list[ThreeDEScene]) -> None:
        """Set items (filtered scenes) in the model."""
        self._items = items
        self._scenes = list(items)

    def rowCount(self) -> int:
        """Return current visible row count."""
        return len(self._items)


class ShotModelDouble:
    """Test double for ShotModel."""

    __test__ = False

    def __init__(self) -> None:
        self._shots: list[Shot] = []

    @property
    def shots(self) -> list[Shot]:
        return self._shots


class RightPanelDouble:
    """Test double for RightPanelWidget."""

    __test__ = False

    def __init__(self) -> None:
        self._current_shot: Shot | None = None

    def set_shot(self, shot: Shot) -> None:
        self._current_shot = shot


class SceneDiskCacheDouble:
    """Test double for SceneDiskCache."""

    __test__ = False

    def __init__(self) -> None:
        self._persistent_scenes: list[dict[str, Any]] = []
        self._cached_scenes: list[dict[str, Any]] = []

    def get_persistent_threede_scenes(self) -> list[dict[str, Any]]:
        return self._persistent_scenes

    def cache_threede_scenes(
        self, scenes: list[dict[str, Any]], immediate: bool = False
    ) -> None:
        self._cached_scenes = scenes


class CommandLauncherDouble:
    """Test double for CommandLauncher."""

    __test__ = False

    def __init__(self) -> None:
        self._launched_apps: list[tuple[str, Any]] = []
        self._launched_with_scene: list[tuple[str, Any]] = []

    def launch_app(self, app_name: str, context: Any = None) -> None:
        self._launched_apps.append((app_name, context))

    def launch_app_with_scene(self, app_name: str, scene: Any) -> bool:
        """Launch app with scene context."""
        self._launched_with_scene.append((app_name, scene))
        return True


class StatusBarDouble:
    """Test double for QStatusBar."""

    __test__ = False

    def __init__(self) -> None:
        self._messages: list[str] = []

    def showMessage(self, message: str, timeout: int = 0) -> None:
        self._messages.append(message)


class ThreeDETargetDouble:
    """Test double implementing ThreeDETarget protocol.

    Provides all required attributes and methods for testing ThreeDEController.
    """

    __test__ = False

    def __init__(self) -> None:
        # Lifecycle signal (replaces closing property)
        self.closing_started = SignalDouble()

        # Managers (create first since models may reference them)
        self.scene_disk_cache = SceneDiskCacheDouble()
        self.command_launcher = CommandLauncherDouble()

        # UI Components
        self.threede_shot_grid = ThreeDEGridViewDouble()
        self.right_panel = RightPanelDouble()
        self.status_bar = StatusBarDouble()

        # Models - pass shared scene_disk_cache to scene model
        self.shot_model = ShotModelDouble()
        self.threede_scene_model = ThreeDESceneModelDouble(
            cache_manager=self.scene_disk_cache
        )
        self.threede_item_model = ThreeDEItemModelDouble()

        # Window state tracking
        self._window_title: str = ""
        self._status_messages: list[str] = []

    def setWindowTitle(self, title: str) -> None:
        self._window_title = title

    def update_status(self, message: str) -> None:
        self._status_messages.append(message)

    def get_active_shots(self) -> list[Shot]:
        return self.shot_model.shots

    def launch_app(self, app_name: str, context: Any = None) -> None:
        self.command_launcher.launch_app(app_name, context)


# ============================================================================
# Factory Functions
# ============================================================================


def make_scene(
    show: str = "testshow",
    sequence: str = "sq010",
    shot: str = "sh0010",
    user: str = "testuser",
    plate: str = "plate_main",
    modified_time: float | None = None,
    scene_path: str | None = None,
) -> ThreeDEScene:
    """Factory function to create ThreeDEScene instances for testing."""
    if modified_time is None:
        modified_time = time.time()
    if scene_path is None:
        scene_path = f"/shows/{show}/shots/{sequence}/{shot}/3de/{user}_{plate}.3de"

    return ThreeDEScene(
        show=show,
        sequence=sequence,
        shot=shot,
        workspace_path=f"/shows/{show}/shots/{sequence}/{shot}",
        user=user,
        plate=plate,
        scene_path=Path(scene_path),
        modified_time=modified_time,
    )


def make_scene_dict(
    show: str = "testshow",
    sequence: str = "sq010",
    shot: str = "sh0010",
    user: str = "testuser",
    plate: str = "plate_main",
    modified_time: float | None = None,
    scene_path: str | None = None,
) -> dict[str, Any]:
    """Factory function to create scene dictionaries for cache testing."""
    if modified_time is None:
        modified_time = time.time()
    if scene_path is None:
        scene_path = f"/shows/{show}/shots/{sequence}/{shot}/3de/{user}_{plate}.3de"

    return {
        "show": show,
        "sequence": sequence,
        "shot": shot,
        "workspace_path": f"/shows/{show}/shots/{sequence}/{shot}",
        "user": user,
        "plate": plate,
        "scene_path": scene_path,
        "modified_time": modified_time,
    }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def window_double() -> ThreeDETargetDouble:
    """Create a ThreeDETarget test double."""
    return ThreeDETargetDouble()


@pytest.fixture
def controller(window_double: ThreeDETargetDouble) -> ThreeDEController:
    """Create a ThreeDEController with test double."""
    return ThreeDEController(window_double)  # type: ignore[arg-type]


@pytest.fixture
def reset_progress_manager() -> None:
    """Reset ProgressManager state before each test."""
    ProgressManager.reset()
    yield
    ProgressManager.reset()


# ============================================================================
# Test Initialization
# ============================================================================


class TestThreeDEControllerInitialization:
    """Test ThreeDEController initialization."""

    def test_initialization_sets_all_attributes(
        self, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that init sets all expected constructor state."""
        controller = ThreeDEController(window_double)  # type: ignore[arg-type]
        assert controller.window is window_double
        assert controller._worker_mutex is not None
        assert controller._threede_worker is None
        assert controller._current_progress_operation is None


# ============================================================================
# Test Signal Setup
# ============================================================================


class TestSignalSetup:
    """Test signal connections during initialization."""

    @pytest.mark.parametrize(
        ("signal_name", "handler_attr"),
        [
            ("scene_selected", "on_scene_selected"),
            ("scene_double_clicked", "on_scene_double_clicked"),
            ("recover_crashes_requested", "on_recover_crashes_clicked"),
            ("show_filter_requested", "_on_show_filter_requested"),
            ("artist_filter_requested", "_on_artist_filter_requested"),
            ("text_filter_requested", "_on_text_filter_requested"),
        ],
    )
    def test_signal_connected(
        self,
        controller: ThreeDEController,
        window_double: ThreeDETargetDouble,
        signal_name: str,
        handler_attr: str,
    ) -> None:
        """Test that all grid signals are connected to their handlers."""
        grid = window_double.threede_shot_grid
        signal = getattr(grid, signal_name)
        handler = getattr(controller, handler_attr)
        assert handler in signal.callbacks


# ============================================================================
# Test Scene Selection
# ============================================================================


class TestSceneSelection:
    """Test scene selection handling."""

    def test_on_scene_selected_updates_right_panel(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that scene selection updates right panel."""
        scene = make_scene(show="myshow", sequence="sq020", shot="sh0030")

        controller.on_scene_selected(scene)

        panel_shot = window_double.right_panel._current_shot
        assert panel_shot is not None
        assert panel_shot.show == "myshow"
        assert panel_shot.sequence == "sq020"
        assert panel_shot.shot == "sh0030"

    def test_on_scene_selected_updates_window_title(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that scene selection updates window title."""
        scene = make_scene(user="john", plate="fg_plate")

        controller.on_scene_selected(scene)

        assert "john" in window_double._window_title
        assert "fg_plate" in window_double._window_title

    def test_on_scene_selected_updates_status(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that scene selection updates status bar."""
        scene = make_scene(show="testshow", sequence="sq010", shot="sh0010")

        controller.on_scene_selected(scene)

        assert len(window_double._status_messages) > 0
        assert "sq010_sh0010" in window_double._status_messages[-1]


# ============================================================================
# Test Discovery Callbacks
# ============================================================================


class TestDiscoveryCallbacks:
    """Test discovery event callbacks."""

    def test_on_discovery_started_creates_progress_operation(
        self,
        controller: ThreeDEController,
        window_double: ThreeDETargetDouble,
        reset_progress_manager: None,
    ) -> None:
        """Test that discovery start creates progress operation."""
        controller.on_discovery_started()

        assert controller._current_progress_operation is not None

    def test_on_discovery_progress_updates_operation(
        self,
        controller: ThreeDEController,
        window_double: ThreeDETargetDouble,
        reset_progress_manager: None,
    ) -> None:
        """Test that discovery progress updates progress operation."""
        # Start a progress operation first
        controller.on_discovery_started()

        # Call progress with all required arguments (current, total, percentage, description, eta)
        controller.on_discovery_progress(50, 100, 50.0, "Scanning show X", "1m 30s")

        # Progress operation should have been updated
        operation = ProgressManager.get_current_operation()
        assert operation is not None

    @pytest.mark.parametrize(
        "trigger",
        ["finished", "error"],
    )
    @pytest.mark.allow_dialogs
    def test_cleanup_clears_progress_and_loading_state(
        self,
        controller: ThreeDEController,
        window_double: ThreeDETargetDouble,
        reset_progress_manager: None,
        trigger: str,
    ) -> None:
        """Test that discovery finish and error both clear progress and loading state."""
        window_double.threede_item_model._loading_state = True
        controller.on_discovery_started()
        assert controller._current_progress_operation is not None

        if trigger == "finished":
            controller.on_discovery_finished([make_scene()])
        else:
            controller.on_discovery_error("Network error")

        assert controller._current_progress_operation is None
        assert window_double.threede_item_model._loading_state is False

    def test_on_discovery_finished_skipped_when_closing(
        self,
        controller: ThreeDEController,
        window_double: ThreeDETargetDouble,
        reset_progress_manager: None,
    ) -> None:
        """Test that discovery finish is skipped when window is closing."""
        controller._closing = True
        window_double.threede_item_model._loading_state = True

        # Progress manager should not be touched when closing
        scenes = [make_scene()]
        controller.on_discovery_finished(scenes)

        # Loading state should remain unchanged when closing
        assert window_double.threede_item_model._loading_state is True

    @pytest.mark.allow_dialogs
    def test_on_discovery_error_shows_warning(
        self,
        controller: ThreeDEController,
        window_double: ThreeDETargetDouble,
        reset_progress_manager: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that discovery error logs a warning."""
        # Start a progress operation first
        controller.on_discovery_started()

        with caplog.at_level("WARNING"):
            controller.on_discovery_error("Disk read error")

        # Should log a warning about the error
        assert any("Disk read error" in record.message for record in caplog.records)


# ============================================================================
# Test Scene Change Detection
# ============================================================================


class TestSceneChangeDetection:
    """Test scene change detection logic."""

    def test_has_scene_changes_returns_true_when_new_scenes(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that changes are detected when new scenes are added."""
        # Start with empty model
        window_double.threede_scene_model._scenes = []

        # New scenes discovered
        new_scenes = [make_scene()]

        assert controller.has_scene_changes(new_scenes) is True

    def test_has_scene_changes_returns_true_when_scenes_removed(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that changes are detected when scenes are removed."""
        # Start with existing scene
        window_double.threede_scene_model._scenes = [make_scene()]

        # Empty discovery
        new_scenes: list[ThreeDEScene] = []

        assert controller.has_scene_changes(new_scenes) is True

    def test_has_scene_changes_returns_false_when_identical(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that no changes detected when scenes are identical."""
        scene = make_scene()
        window_double.threede_scene_model._scenes = [scene]

        # Same scene discovered
        new_scenes = [scene]

        assert controller.has_scene_changes(new_scenes) is False

    @pytest.mark.parametrize(
        ("old_kwargs", "new_kwargs"),
        [
            ({"user": "alice"}, {"user": "bob"}),
            ({"scene_path": "/old/path.3de"}, {"scene_path": "/new/path.3de"}),
        ],
        ids=["user_change", "path_change"],
    )
    def test_has_scene_changes_detects_attribute_change(
        self,
        controller: ThreeDEController,
        window_double: ThreeDETargetDouble,
        old_kwargs: dict,
        new_kwargs: dict,
    ) -> None:
        """Test that changes are detected when scene user or path changes."""
        old_scene = make_scene(**old_kwargs)
        window_double.threede_scene_model._scenes = [old_scene]

        new_scene = make_scene(**new_kwargs)
        assert controller.has_scene_changes([new_scene]) is True


# ============================================================================
# Test Scene Updates
# ============================================================================


class TestSceneUpdates:
    """Test scene update logic."""

    def test_update_scenes_with_changes_deduplicates(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that update_scenes_with_changes deduplicates scenes."""
        # Two scenes for same shot - should keep one
        scene1 = make_scene(user="alice", modified_time=1000.0)
        scene2 = make_scene(user="bob", modified_time=2000.0)

        controller.update_scenes_with_changes([scene1, scene2])

        # Should have deduplicated to 1 scene
        assert len(window_double.threede_scene_model._scenes) == 1
        # Should keep the newer one (bob)
        assert window_double.threede_scene_model._scenes[0].user == "bob"

    def test_update_scenes_with_changes_sorts_scenes(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that update_scenes_with_changes sorts scenes."""
        scene_z = make_scene(sequence="sq999", shot="sh0010")
        scene_a = make_scene(sequence="sq001", shot="sh0010")

        controller.update_scenes_with_changes([scene_z, scene_a])

        scenes = window_double.threede_scene_model._scenes
        # Should be sorted by full_name
        assert scenes[0].sequence == "sq001"
        assert scenes[1].sequence == "sq999"

    def test_update_scenes_with_changes_caches_results(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that update_scenes_with_changes caches results."""
        scenes = [make_scene()]

        controller.update_scenes_with_changes(scenes)

        # Cache manager should have cached the scenes
        assert len(window_double.scene_disk_cache._cached_scenes) == 1

    def test_update_scenes_with_changes_updates_status_with_count(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that update_scenes_with_changes shows scene count in status."""
        scenes = [
            make_scene(shot="sh0010"),
            make_scene(shot="sh0020"),
            make_scene(shot="sh0030"),
        ]

        controller.update_scenes_with_changes(scenes)

        assert any("3" in msg for msg in window_double._status_messages)

    def test_update_scenes_with_changes_shows_empty_message(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that update_scenes_with_changes shows empty message when no scenes."""
        controller.update_scenes_with_changes([])

        assert any(
            "No 3DE scenes" in msg for msg in window_double._status_messages
        )


# ============================================================================
# Test Filter Handling
# ============================================================================


class TestFilterHandling:
    """Test filter request handling."""

    def test_show_filter_applies_to_model(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that show filter is applied to item model."""
        controller._on_show_filter_requested("myshow")

        # The filter should be applied (set_show_filter converts "" to None)
        assert window_double.threede_item_model._filter_show == "myshow"

    def test_text_filter_applies_to_scene_model(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that text filter is applied to scene model."""
        controller._on_text_filter_requested("sq010")

        # The filter should be applied to scene model
        assert window_double.threede_scene_model._text_filter == "sq010"

    def test_artist_filter_applies_to_scene_model(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that artist filter is applied to scene model."""
        controller._on_artist_filter_requested("artist_a")

        assert window_double.threede_scene_model._artist_filter == "artist_a"

    def test_empty_show_filter_clears_filter(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that empty show filter clears the filter."""
        # Set a filter first
        window_double.threede_item_model._filter_show = "oldshow"

        controller._on_show_filter_requested("")

        # Empty string is converted to None, which becomes "" in the double
        assert window_double.threede_item_model._filter_show == ""

    def test_update_ui_populates_artist_filter(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that UI refresh populates the artist filter dropdown."""
        window_double.threede_scene_model.set_scenes(
            [
                make_scene(user="artist_a"),
                make_scene(shot="sh0020", user="artist_b"),
            ]
        )

        controller.update_ui()

        assert window_double.threede_shot_grid._artist_filter_populated is True


# ============================================================================
# Test Worker Management
# ============================================================================


class TestWorkerManagement:
    """Test worker thread management."""

    def test_cleanup_worker_handles_no_worker(
        self, controller: ThreeDEController
    ) -> None:
        """Test that cleanup_worker handles no active worker gracefully."""
        # Should not raise
        controller.cleanup_worker()

    @pytest.mark.allow_dialogs
    def test_cleanup_worker_clears_orphaned_progress(
        self,
        controller: ThreeDEController,
        reset_progress_manager: None,
    ) -> None:
        """Test that cleanup_worker clears orphaned progress operations."""
        # Start a progress operation manually (simulating orphaned state)
        controller.on_discovery_started()
        assert controller._current_progress_operation is not None

        # Simulate a worker that exists but is finished
        mock_worker = MagicMock()
        mock_worker.isFinished.return_value = True
        controller._threede_worker = mock_worker

        # Cleanup should clear the progress operation
        controller.cleanup_worker()

        assert controller._current_progress_operation is None


# ============================================================================
# Test Refresh Guards
# ============================================================================


class TestRefreshGuards:
    """Test refresh debouncing and concurrency guards."""

    def test_refresh_skipped_when_closing(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that refresh is skipped when window is closing."""
        controller._closing = True

        # Should return early without creating worker
        with patch.object(controller, "_setup_worker_signals") as mock_setup:
            controller.refresh_threede_scenes()

            mock_setup.assert_not_called()

    def test_refresh_debounced_when_called_too_soon(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that refresh is debounced when called within interval."""
        # Set last scan time to now
        controller._last_scan_time = time.time()

        # Try to refresh immediately
        with patch.object(controller, "_setup_worker_signals") as mock_setup:
            controller.refresh_threede_scenes()

            # Should be debounced - no new worker created
            mock_setup.assert_not_called()

    def test_refresh_proceeds_after_interval(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that refresh proceeds after minimum interval passes."""
        # Set last scan time to long ago
        controller._last_scan_time = time.time() - 60  # 60 seconds ago

        # Mock the worker creation path
        with patch(
            "controllers.threede_controller.ThreeDESceneWorker"
        ) as mock_worker_class:
            mock_worker = MagicMock()
            mock_worker.isFinished.return_value = True
            mock_worker_class.return_value = mock_worker

            controller.refresh_threede_scenes()

            # Worker should have been created
            mock_worker_class.assert_called_once()

    def test_concurrent_refresh_blocked(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that concurrent refresh calls are blocked."""
        # Set up a mock worker that appears to be running
        mock_worker = MagicMock()
        mock_worker.isFinished.return_value = False
        controller._threede_worker = mock_worker

        # Reset last scan time to allow refresh based on timing
        controller._last_scan_time = 0

        # Try to refresh while worker is running
        with patch(
            "controllers.threede_controller.ThreeDESceneWorker"
        ) as mock_worker_class:
            controller.refresh_threede_scenes()

            # Should NOT create a new worker
            mock_worker_class.assert_not_called()


# ============================================================================
# Test Cache Operations
# ============================================================================


class TestCacheOperations:
    """Test cache-related operations."""

    def test_cache_scenes_serializes_scenes_as_dicts(
        self, controller: ThreeDEController, window_double: ThreeDETargetDouble
    ) -> None:
        """Test that cache_scenes serializes all scenes as dicts to cache manager."""
        scenes = [
            make_scene(show="testshow", sequence="sq010", shot="sh0010"),
            make_scene(show="testshow", sequence="sq010", shot="sh0020"),
        ]
        window_double.threede_scene_model._scenes = scenes

        controller.cache_scenes()

        cached = window_double.scene_disk_cache._cached_scenes
        assert len(cached) == 2
        assert cached[0]["show"] == "testshow"
        assert cached[0]["sequence"] == "sq010"


