"""Tests for RightPanelWidget composition root."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from scene_file import FileType, SceneFile
from tests.test_helpers import process_qt_events
from ui.right_panel import RightPanelWidget


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


@pytest.fixture
def mock_shot() -> MagicMock:
    """Create a mock shot for testing."""
    shot = MagicMock()
    shot.full_name = "sq010_sh0010"
    shot.show = "myshow"
    shot.sequence = "sq010"
    shot.shot = "sh0010"
    shot.workspace_path = "/shows/myshow/shots/sq010/sh0010"
    return shot


@pytest.fixture
def sample_files() -> dict[FileType, list[SceneFile]]:
    """Create sample scene files for testing."""
    now = datetime.now()  # noqa: DTZ005 - Match production code's naive datetime
    return {
        FileType.THREEDE: [
            SceneFile(
                path=Path("/path/to/scene_v005.3de"),
                file_type=FileType.THREEDE,
                modified_time=now,
                user="artist1",
                version=5,
            ),
        ],
        FileType.NUKE: [
            SceneFile(
                path=Path("/path/to/comp_v012.nk"),
                file_type=FileType.NUKE,
                modified_time=now,
                user="compositor",
                version=12,
            ),
        ],
        FileType.MAYA: [],
    }


class TestRightPanelWidgetInit:
    """Tests for RightPanelWidget initialization."""

    def test_creates_dcc_accordion(self, qtbot: QtBot) -> None:
        """DCC accordion is created."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        assert panel._dcc_accordion is not None

    def test_parent_parameter(self, qtbot: QtBot) -> None:
        """Accepts parent parameter."""
        from PySide6.QtWidgets import QWidget

        parent = QWidget()
        panel = RightPanelWidget(parent=parent)
        qtbot.addWidget(parent)

        assert panel.parent() is parent


class TestRightPanelWidgetShot:
    """Tests for shot handling."""

    def test_set_shot_enables_dcc_sections(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Setting shot enables DCC sections."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)
        panel.show()
        process_qt_events()

        panel.set_shot(mock_shot)
        process_qt_events()

        # DCC sections should be enabled
        for section in panel._dcc_accordion._sections.values():
            assert section._launch_btn.isEnabled()

    def test_clear_shot_disables_dcc_sections(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Clearing shot disables DCC sections."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        panel.set_shot(mock_shot)
        panel.set_shot(None)

        # DCC sections should be disabled
        for section in panel._dcc_accordion._sections.values():
            assert not section._launch_btn.isEnabled()

    def test_set_shot_clears_file_selections(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Setting a new shot clears file selections."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        # Set initial shot
        panel.set_shot(mock_shot)

        # Create a different shot
        new_shot = MagicMock()
        new_shot.full_name = "sq020_sh0020"

        # Set new shot
        panel.set_shot(new_shot)

        # File selections should be cleared
        for app_name in ["3de", "nuke", "maya"]:
            assert panel._selected_files[app_name] is None


class TestRightPanelWidgetFiles:
    """Tests for file handling."""

    def test_set_files_routes_to_dcc_sections(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Setting files routes them to appropriate DCC sections."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        panel.set_files(sample_files)
        process_qt_events()

        # 3DE section should have 1 file
        threede_section = panel._dcc_accordion._sections["3de"]
        assert threede_section.get_selected_file() is not None

        # Nuke section should have 1 file
        nuke_section = panel._dcc_accordion._sections["nuke"]
        assert nuke_section.get_selected_file() is not None

    def test_set_files_updates_version_info(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Setting files updates version info in accordions."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)
        panel.show()
        process_qt_events()

        panel.set_files(sample_files)
        process_qt_events()

        # 3DE section should show v005
        threede_section = panel._dcc_accordion._sections["3de"]
        assert "v005" in threede_section._version_label.text()

    def test_set_files_tracks_selected_files(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Setting files updates selected files tracking."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        panel.set_files(sample_files)

        # Should track latest files
        assert panel._selected_files["3de"] is not None
        assert panel._selected_files["nuke"] is not None
        assert panel._selected_files["maya"] is None  # Empty list


class TestRightPanelWidgetLaunchSignals:
    """Tests for launch signal handling."""

    def test_accordion_launch_emits_launch_requested(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Accordion launch button emits launch_requested signal."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)
        panel.set_shot(mock_shot)
        panel.show()
        process_qt_events()

        # Expand and click the 3de section
        section = panel._dcc_accordion._sections["3de"]
        section.set_expanded(True)
        process_qt_events()

        with qtbot.waitSignal(panel.launch_requested, timeout=1000) as blocker:
            qtbot.mouseClick(section._launch_btn, Qt.MouseButton.LeftButton)
            process_qt_events()

        assert blocker.args[0] == "3de"

    def test_launch_includes_selected_file(
        self,
        qtbot: QtBot,
        mock_shot: MagicMock,
        sample_files: dict[FileType, list[SceneFile]],
    ) -> None:
        """Launch signal includes selected file in options."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)
        panel.set_shot(mock_shot)
        panel.set_files(sample_files)
        panel.show()
        process_qt_events()

        # Expand and click the 3de section
        section = panel._dcc_accordion._sections["3de"]
        section.set_expanded(True)
        process_qt_events()

        with qtbot.waitSignal(panel.launch_requested, timeout=1000) as blocker:
            qtbot.mouseClick(section._launch_btn, Qt.MouseButton.LeftButton)
            process_qt_events()

        app_name, options = blocker.args
        assert app_name == "3de"
        assert "selected_file" in options


class TestRightPanelWidgetPlates:
    """Tests for plate handling."""

    def test_set_available_plates(self, qtbot: QtBot) -> None:
        """Setting plates updates all DCC sections."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        panel.set_available_plates(["FG01", "BG01"])

        # Check a DCC section has the plates
        section = panel._dcc_accordion._sections["3de"]
        assert section._plate_selector.count() == 2


class TestRightPanelWidgetDCCExpansion:
    """Tests for DCC section expansion control."""

    def test_expand_dcc_section(self, qtbot: QtBot) -> None:
        """Can expand a specific DCC section."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        panel.expand_dcc_section("nuke")

        assert panel._dcc_accordion._sections["nuke"].is_expanded()

    def test_collapse_dcc_section(self, qtbot: QtBot) -> None:
        """Can collapse a specific DCC section."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        panel.expand_dcc_section("nuke")
        panel.collapse_dcc_section("nuke")

        assert not panel._dcc_accordion._sections["nuke"].is_expanded()


class TestRightPanelWidgetShortcuts:
    """Tests for keyboard shortcut handling."""

    def test_handle_shortcut_with_shot(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Shortcut emits launch signal when shot is set."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)
        panel.set_shot(mock_shot)

        with qtbot.waitSignal(panel.launch_requested, timeout=1000) as blocker:
            result = panel.handle_shortcut("N")
            process_qt_events()

        assert result is True
        assert blocker.args[0] == "nuke"

    def test_handle_shortcut_without_shot(self, qtbot: QtBot) -> None:
        """Shortcut returns False when no shot is set."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        result = panel.handle_shortcut("N")

        assert result is False

    def test_handle_unknown_shortcut(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Unknown shortcut returns False."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)
        panel.set_shot(mock_shot)

        result = panel.handle_shortcut("X")

        assert result is False


class TestRightPanelWidgetOptions:
    """Tests for options retrieval."""

    def test_get_dcc_options(self, qtbot: QtBot) -> None:
        """Can get options for a specific DCC."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        options = panel.get_dcc_options("nuke")

        assert options is not None
        assert "open_latest_scene" in options

    def test_get_dcc_options_unknown(self, qtbot: QtBot) -> None:
        """Returns None for unknown DCC."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        options = panel.get_dcc_options("unknown")

        assert options is None


class TestRightPanelWidgetFileSelection:
    """Tests for file selection functionality."""

    def test_get_selected_file(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Can get selected file for a specific DCC."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        panel.set_files(sample_files)

        # 3DE should have a selected file
        selected = panel.get_selected_file("3de")
        assert selected is not None
        assert selected.version == 5

    def test_get_selected_file_no_files(self, qtbot: QtBot) -> None:
        """Returns None when no files set."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        selected = panel.get_selected_file("3de")
        assert selected is None

    def test_file_selection_from_dcc_section(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """File selection from DCC section updates panel state."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        panel.set_files(sample_files)

        # The file selection should be tracked
        assert panel._selected_files["3de"] is not None
        assert panel._selected_files["3de"].version == 5
