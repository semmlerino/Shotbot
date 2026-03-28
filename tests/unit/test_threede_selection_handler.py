"""Unit tests for controllers/threede_selection_handler.py.

Tests for ThreeDESelectionHandler which manages scene selection, double-click
launch, tab activation, crash recovery dispatch, and proxy filter delegation.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from controllers.threede_selection_handler import ThreeDESelectionHandler
from tests.fixtures.model_fixtures import SignalDouble
from type_definitions import ThreeDEScene


if __name__ == "__main__":
    pass


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
        self._selected_scene: ThreeDEScene | None = None

    @property
    def selected_scene(self) -> ThreeDEScene | None:
        return self._selected_scene


class ThreeDEProxyDouble:
    """Test double for ThreeDEProxyModel."""

    __test__ = False

    def __init__(self) -> None:
        self._show_filter: str | None = None
        self._artist_filter: str | None = None

    def set_show_filter(self, show: str | None) -> None:
        self._show_filter = show

    def set_artist_filter(self, artist: str | None) -> None:
        self._artist_filter = artist


class RightPanelDouble:
    """Test double for RightPanelWidget."""

    __test__ = False

    def __init__(self) -> None:
        self._current_shot: Any = None

    def set_shot(self, shot: Any) -> None:
        self._current_shot = shot


class WindowDouble:
    """Test double implementing ThreeDESelectionTarget protocol."""

    __test__ = False

    def __init__(self) -> None:
        self.threede_shot_grid = ThreeDEGridViewDouble()
        self.right_panel = RightPanelDouble()
        self.threede_proxy = ThreeDEProxyDouble()
        self._window_title: str = ""
        self._status_messages: list[str] = []

    def setWindowTitle(self, title: str) -> None:
        self._window_title = title

    def update_status(self, message: str) -> None:
        self._status_messages.append(message)


class CommandLauncherDouble:
    """Test double for CommandLauncher."""

    __test__ = False

    def __init__(self) -> None:
        self._launched: list[Any] = []
        self.current_shot: Any = None

    def launch(self, request: Any) -> bool:
        self._launched.append(request)
        return True

    def set_current_shot(self, shot: Any) -> None:
        self.current_shot = shot


# ============================================================================
# Factory helpers
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


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def window() -> WindowDouble:
    return WindowDouble()


@pytest.fixture
def command_launcher() -> CommandLauncherDouble:
    return CommandLauncherDouble()


@pytest.fixture
def refresh_callback() -> MagicMock:
    return MagicMock()


@pytest.fixture
def handler(
    window: WindowDouble,
    command_launcher: CommandLauncherDouble,
    refresh_callback: MagicMock,
) -> ThreeDESelectionHandler:
    return ThreeDESelectionHandler(
        window,  # type: ignore[arg-type]
        command_launcher=command_launcher,  # type: ignore[arg-type]
        refresh_callback=refresh_callback,
    )


# ============================================================================
# Test Signal Setup
# ============================================================================


class TestSignalSetup:
    """Test that setup_signals wires the expected grid signals."""

    @pytest.mark.parametrize(
        ("signal_name", "handler_attr"),
        [
            ("scene_selected", "on_scene_selected"),
            ("scene_double_clicked", "on_scene_double_clicked"),
            ("recover_crashes_requested", "on_recover_crashes_clicked"),
            ("show_filter_requested", "on_show_filter_requested"),
            ("artist_filter_requested", "on_artist_filter_requested"),
        ],
    )
    def test_signal_connected(
        self,
        handler: ThreeDESelectionHandler,
        window: WindowDouble,
        signal_name: str,
        handler_attr: str,
    ) -> None:
        """Test that setup_signals wires every grid signal to its slot."""
        handler.setup_signals(window.threede_shot_grid)  # type: ignore[arg-type]

        grid = window.threede_shot_grid
        signal = getattr(grid, signal_name)
        slot = getattr(handler, handler_attr)
        assert slot in signal.callbacks


# ============================================================================
# Test Scene Selection
# ============================================================================


class TestSceneSelection:
    """Test scene selection handling."""

    def test_on_scene_selected_updates_right_panel(
        self, handler: ThreeDESelectionHandler, window: WindowDouble
    ) -> None:
        """Test that scene selection updates right panel."""
        scene = make_scene(show="myshow", sequence="sq020", shot="sh0030")

        handler.on_scene_selected(scene)

        panel_shot = window.right_panel._current_shot
        assert panel_shot is not None
        assert panel_shot.show == "myshow"
        assert panel_shot.sequence == "sq020"
        assert panel_shot.shot == "sh0030"

    def test_on_scene_selected_updates_window_title(
        self, handler: ThreeDESelectionHandler, window: WindowDouble
    ) -> None:
        """Test that scene selection updates window title."""
        scene = make_scene(user="john", plate="fg_plate")

        handler.on_scene_selected(scene)

        assert "john" in window._window_title
        assert "fg_plate" in window._window_title

    def test_on_scene_selected_updates_status(
        self, handler: ThreeDESelectionHandler, window: WindowDouble
    ) -> None:
        """Test that scene selection updates status bar."""
        scene = make_scene(show="testshow", sequence="sq010", shot="sh0010")

        handler.on_scene_selected(scene)

        assert len(window._status_messages) > 0
        assert "sq010_sh0010" in window._status_messages[-1]

    def test_on_scene_double_clicked_launches_3de(
        self,
        handler: ThreeDESelectionHandler,
        command_launcher: CommandLauncherDouble,
    ) -> None:
        """Test that double-clicking a scene launches 3DE."""
        scene = make_scene()

        handler.on_scene_double_clicked(scene)

        assert len(command_launcher._launched) == 1

    def test_on_tab_activated_with_selected_scene_calls_on_scene_selected(
        self, handler: ThreeDESelectionHandler, window: WindowDouble, mocker
    ) -> None:
        """Test that tab activation with a selected scene calls on_scene_selected."""
        scene = make_scene()
        window.threede_shot_grid._selected_scene = scene

        mocker.patch("ui.tab_constants.TAB_OTHER_3DE", 2)
        handler.on_tab_activated(2)

        assert window.right_panel._current_shot is not None

    def test_on_tab_activated_without_scene_clears_right_panel(
        self,
        handler: ThreeDESelectionHandler,
        window: WindowDouble,
        command_launcher: CommandLauncherDouble,
        mocker,
    ) -> None:
        """Test that tab activation with no selected scene clears the right panel."""
        window.threede_shot_grid._selected_scene = None

        mocker.patch("ui.tab_constants.TAB_OTHER_3DE", 2)
        handler.on_tab_activated(2)

        assert window.right_panel._current_shot is None
        assert command_launcher.current_shot is None

    def test_on_tab_activated_ignores_other_tabs(
        self, handler: ThreeDESelectionHandler, window: WindowDouble, mocker
    ) -> None:
        """Test that tab activation for non-3DE tabs is ignored."""
        window.threede_shot_grid._selected_scene = make_scene()

        mocker.patch("ui.tab_constants.TAB_OTHER_3DE", 2)
        handler.on_tab_activated(0)  # Tab 0 is not 3DE

        # Right panel should not have been updated
        assert window.right_panel._current_shot is None


# ============================================================================
# Test Crash Recovery
# ============================================================================


class TestCrashRecovery:
    """Test crash recovery dispatch."""

    @pytest.mark.allow_dialogs
    def test_on_recover_crashes_clicked_with_no_scene_shows_warning(
        self, handler: ThreeDESelectionHandler, window: WindowDouble, mocker
    ) -> None:
        """Test that recovery without a selected scene shows a warning."""
        window.threede_shot_grid._selected_scene = None

        mock_nm = mocker.patch(
            "controllers.threede_selection_handler.NotificationManager"
        )
        handler.on_recover_crashes_clicked()
        mock_nm.warning.assert_called_once()

    def test_on_recover_crashes_clicked_with_scene_calls_execute_crash_recovery(
        self,
        handler: ThreeDESelectionHandler,
        window: WindowDouble,
        refresh_callback: MagicMock,
        mocker,
    ) -> None:
        """Test that recovery with a selected scene dispatches execute_crash_recovery."""
        scene = make_scene()
        window.threede_shot_grid._selected_scene = scene

        mock_recovery = mocker.patch(
            "controllers.crash_recovery.execute_crash_recovery"
        )
        handler.on_recover_crashes_clicked()

        mock_recovery.assert_called_once()
        call_kwargs = mock_recovery.call_args.kwargs
        assert call_kwargs["workspace_path"] == scene.workspace_path
        assert call_kwargs["display_name"] == scene.full_name
        assert call_kwargs["post_recovery_callback"] is refresh_callback


# ============================================================================
# Test Filter Handling
# ============================================================================


class TestFilterHandling:
    """Test filter request delegation."""

    def test_show_filter_applies_to_proxy(
        self, handler: ThreeDESelectionHandler, window: WindowDouble
    ) -> None:
        """Test that show filter is applied to proxy model."""
        handler.on_show_filter_requested("SHOW_A")

        assert window.threede_proxy._show_filter == "SHOW_A"

    def test_show_filter_empty_string_sets_none(
        self, handler: ThreeDESelectionHandler, window: WindowDouble
    ) -> None:
        """Test that empty show filter string is normalised to None."""
        handler.on_show_filter_requested("")

        assert window.threede_proxy._show_filter is None

    def test_artist_filter_applies_to_proxy(
        self, handler: ThreeDESelectionHandler, window: WindowDouble
    ) -> None:
        """Test that artist filter is applied to proxy model."""
        handler.on_artist_filter_requested("artist_a")

        assert window.threede_proxy._artist_filter == "artist_a"

    def test_artist_filter_empty_string_sets_none(
        self, handler: ThreeDESelectionHandler, window: WindowDouble
    ) -> None:
        """Test that empty artist filter string is normalised to None."""
        handler.on_artist_filter_requested("")

        assert window.threede_proxy._artist_filter is None
