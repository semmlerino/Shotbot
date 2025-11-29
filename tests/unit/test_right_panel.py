"""Tests for RightPanelWidget composition root."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt

from right_panel import RightPanelWidget
from scene_file import FileType, SceneFile
from tests.test_helpers import process_qt_events


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

    def test_creates_all_child_widgets(self, qtbot: QtBot) -> None:
        """All child widgets are created."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        assert panel._shot_header is not None
        assert panel._quick_launch is not None
        assert panel._dcc_accordion is not None
        assert panel._files_section is not None

    def test_parent_parameter(self, qtbot: QtBot) -> None:
        """Accepts parent parameter."""
        from PySide6.QtWidgets import QWidget

        parent = QWidget()
        panel = RightPanelWidget(parent=parent)
        qtbot.addWidget(parent)

        assert panel.parent() is parent


class TestRightPanelWidgetShot:
    """Tests for shot handling."""

    def test_set_shot_updates_all_widgets(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Setting shot updates all child widgets."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)
        panel.show()
        process_qt_events()

        panel.set_shot(mock_shot)
        process_qt_events()

        # Shot header should show shot name
        assert "sq010_sh0010" in panel._shot_header._shot_name_label.text()

        # Quick launch should be enabled
        for btn in panel._quick_launch._buttons.values():
            assert btn.isEnabled()

    def test_clear_shot_updates_all_widgets(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Clearing shot updates all child widgets."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        panel.set_shot(mock_shot)
        panel.set_shot(None)

        # Quick launch should be disabled
        for btn in panel._quick_launch._buttons.values():
            assert not btn.isEnabled()


class TestRightPanelWidgetFiles:
    """Tests for file handling."""

    def test_set_files(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Setting files updates files section."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        panel.set_files(sample_files)

        assert panel._files_section.get_total_file_count() == 2

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


class TestRightPanelWidgetLaunchSignals:
    """Tests for launch signal handling."""

    def test_quick_launch_emits_launch_requested(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Quick launch button emits launch_requested signal."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)
        panel.set_shot(mock_shot)
        panel.show()
        process_qt_events()

        with qtbot.waitSignal(panel.launch_requested, timeout=1000) as blocker:
            qtbot.mouseClick(
                panel._quick_launch._buttons["3de"],
                Qt.MouseButton.LeftButton,
            )
            process_qt_events()

        app_name, options = blocker.args
        assert app_name == "3de"
        assert isinstance(options, dict)

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


class TestRightPanelWidgetFilesExpansion:
    """Tests for files section expansion control."""

    def test_files_collapsed_by_default(self, qtbot: QtBot) -> None:
        """Files section is collapsed by default."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        assert not panel._files_section.is_expanded()

    def test_set_files_expanded(self, qtbot: QtBot) -> None:
        """Can expand the files section."""
        panel = RightPanelWidget()
        qtbot.addWidget(panel)

        panel.set_files_expanded(True)

        assert panel._files_section.is_expanded()


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
