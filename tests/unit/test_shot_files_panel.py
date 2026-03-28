"""Unit tests for shot_files_panel.py - File discovery widget tests.

Tests for ShotFilesPanel, FileTypeSection, and FileListItem components.

Following UNIFIED_TESTING_V2.md best practices:
- Test behavior using protocol-based test doubles
- Use real Qt components with minimal mocking
- Set up signal waiters BEFORE triggering actions
- Use qtbot for proper Qt event handling
- Clean up widgets properly

Test Coverage:
- FileListItem: display, signals, context menu
- FileTypeSection: expand/collapse, set files, clear
- ShotFilesPanel: initialization, set shot, signal routing
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from dcc.scene_file import FileType, SceneFile
from shots.shot_files_panel import FileListItem, FileTypeSection, ShotFilesPanel
from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


pytestmark = [pytest.mark.unit, pytest.mark.qt]


# ============================================================================
# Test Doubles
# ============================================================================


class ShotDouble:
    """Test double for Shot type."""

    def __init__(
        self,
        show: str = "testshow",
        sequence: str = "sq010",
        shot: str = "sh0010",
        workspace_path: str = "/shows/testshow/shots/sq010/sq010_sh0010",
    ) -> None:
        self.show = show
        self.sequence = sequence
        self.shot = shot
        self.workspace_path = workspace_path
        self.full_name = f"{show}/{sequence}/{shot}"


def create_scene_file(
    file_type: FileType = FileType.THREEDE,
    name: str = "test_scene.3de",
    user: str = "artist",
    hours_ago: int = 2,
) -> SceneFile:
    """Create a SceneFile for testing.

    Args:
        file_type: Type of scene file
        name: Filename
        user: Username
        hours_ago: Hours since modification

    Returns:
        SceneFile instance

    """
    from datetime import timedelta

    path = Path(f"/shows/test/shots/sq010/sq010_sh0010/{name}")
    modified_time = datetime.now() - timedelta(hours=hours_ago)  # noqa: DTZ005

    return SceneFile(
        path=path,
        file_type=file_type,
        modified_time=modified_time,
        user=user,
    )


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def scene_file() -> SceneFile:
    """Create a test SceneFile."""
    return create_scene_file()


@pytest.fixture
def file_list_item(qtbot: QtBot, scene_file: SceneFile) -> FileListItem:
    """Create FileListItem for testing."""
    item = FileListItem(scene_file)
    qtbot.addWidget(item)
    return item


@pytest.fixture
def file_type_section(qtbot: QtBot) -> FileTypeSection:
    """Create FileTypeSection for testing."""
    section = FileTypeSection(FileType.THREEDE)
    qtbot.addWidget(section)
    return section


@pytest.fixture
def shot_files_panel(qtbot: QtBot) -> ShotFilesPanel:
    """Create ShotFilesPanel for testing."""
    panel = ShotFilesPanel()
    qtbot.addWidget(panel)
    return panel


@pytest.fixture(autouse=True)
def cleanup_qt_state(qtbot: QtBot):
    """Ensure Qt state is cleaned up after each test."""
    yield
    process_qt_events()


# ============================================================================
# Test FileListItem
# ============================================================================


class TestFileListItem:
    """Test FileListItem widget."""

    def test_init_displays_filename(
        self, qtbot: QtBot, file_list_item: FileListItem, scene_file: SceneFile
    ) -> None:
        """Test that init displays the filename."""
        # The widget should have a tooltip with the full path
        assert (
            scene_file.name in file_list_item.toolTip()
            or str(scene_file.path) in file_list_item.toolTip()
        )

    def test_init_sets_tooltip_to_path(
        self, qtbot: QtBot, file_list_item: FileListItem, scene_file: SceneFile
    ) -> None:
        """Test that tooltip shows the full path."""
        assert str(scene_file.path) == file_list_item.toolTip()

    def test_context_menu_policy_set(
        self, qtbot: QtBot, file_list_item: FileListItem
    ) -> None:
        """Test that custom context menu policy is set."""
        assert (
            file_list_item.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
        )

    @pytest.mark.allow_dialogs
    def test_open_requested_signal_defined(
        self, qtbot: QtBot, file_list_item: FileListItem
    ) -> None:
        """Test that open_requested signal is defined."""
        assert hasattr(file_list_item, "open_requested")
        signal_spy = QSignalSpy(file_list_item.open_requested)
        assert signal_spy is not None


class TestFileListItemContextMenu:
    """Test FileListItem context menu functionality."""

    @pytest.mark.allow_dialogs
    def test_copy_path_copies_to_clipboard(
        self, qtbot: QtBot, scene_file: SceneFile
    ) -> None:
        """Test that copy path action copies path to clipboard."""
        item = FileListItem(scene_file)
        qtbot.addWidget(item)

        # Call the copy method directly (avoid triggering context menu)
        item._copy_path()
        process_qt_events()

        # Check clipboard
        clipboard = QApplication.clipboard()
        if clipboard:
            assert clipboard.text() == str(scene_file.path)

    @pytest.mark.allow_dialogs
    def test_open_folder_calls_desktop_services(
        self, qtbot: QtBot, scene_file: SceneFile, mocker
    ) -> None:
        """Test that open folder calls QDesktopServices."""
        from PySide6.QtGui import QDesktopServices

        item = FileListItem(scene_file)
        qtbot.addWidget(item)

        # Mock QDesktopServices to avoid actually opening folder
        mock_open = mocker.patch.object(QDesktopServices, "openUrl")
        item._open_folder()
        process_qt_events()

        mock_open.assert_called_once()
        # Verify it was called with a URI for the parent folder
        call_arg = str(mock_open.call_args[0][0])
        assert (
            "file://" in call_arg.lower() or str(scene_file.path.parent) in call_arg
        )


# ============================================================================
# Test FileTypeSection
# ============================================================================


class TestFileTypeSection:
    """Test FileTypeSection widget."""

    def test_init_creates_chip_button(
        self, qtbot: QtBot, file_type_section: FileTypeSection
    ) -> None:
        """Test that init creates chip button."""
        assert hasattr(file_type_section, "_chip_button")
        assert file_type_section._chip_button is not None

    def test_init_collapsed_by_default(
        self, qtbot: QtBot, file_type_section: FileTypeSection
    ) -> None:
        """Test that section is collapsed by default."""
        assert file_type_section._is_expanded is False
        # Content widget should be programmatically hidden when collapsed
        assert file_type_section._content_widget.isHidden() is True

    def test_chip_button_checkable(
        self, qtbot: QtBot, file_type_section: FileTypeSection
    ) -> None:
        """Test that chip button is checkable."""
        assert file_type_section._chip_button.isCheckable() is True

    @pytest.mark.parametrize(
        ("file_type", "expected_name"),
        [
            (FileType.THREEDE, "3DEqualizer"),
            (FileType.MAYA, "Maya"),
            (FileType.NUKE, "Nuke"),
        ],
    )
    def test_header_text_for_file_types(
        self, qtbot: QtBot, file_type: FileType, expected_name: str
    ) -> None:
        """Test header text formatting for different file types."""
        section = FileTypeSection(file_type)
        qtbot.addWidget(section)

        header_text = section._get_header_text(5)
        assert expected_name in header_text
        assert "(5)" in header_text

    def test_toggle_expands_content(
        self, qtbot: QtBot, file_type_section: FileTypeSection
    ) -> None:
        """Test that toggle expands content widget."""
        assert file_type_section._is_expanded is False

        file_type_section._toggle_expanded()
        process_qt_events()

        assert file_type_section._is_expanded is True
        # Check that visibility is set (actual visibility depends on parent being shown)
        # The content widget should not be hidden programmatically
        assert file_type_section._content_widget.isHidden() is False

    def test_toggle_collapses_content(
        self, qtbot: QtBot, file_type_section: FileTypeSection
    ) -> None:
        """Test that toggle collapses expanded content."""
        # First expand
        file_type_section._toggle_expanded()
        process_qt_events()
        assert file_type_section._is_expanded is True

        # Then collapse
        file_type_section._toggle_expanded()
        process_qt_events()

        assert file_type_section._is_expanded is False
        # The content widget should be hidden programmatically
        assert file_type_section._content_widget.isHidden() is True


class TestFileTypeSectionFiles:
    """Test FileTypeSection file management."""

    def test_set_files_updates_chip_text(
        self, qtbot: QtBot, file_type_section: FileTypeSection
    ) -> None:
        """Test that set_files updates chip button text."""
        files = [
            create_scene_file(name="scene1.3de"),
            create_scene_file(name="scene2.3de"),
        ]

        file_type_section.set_files(files)
        process_qt_events()

        assert "(2)" in file_type_section._chip_button.text()

    def test_set_files_shows_section_when_has_files(
        self, qtbot: QtBot, file_type_section: FileTypeSection
    ) -> None:
        """Test that section is not hidden when it has files."""
        files = [create_scene_file()]

        file_type_section.set_files(files)
        process_qt_events()

        # Section should NOT be hidden when it has files
        assert file_type_section.isHidden() is False

    def test_set_files_hides_section_when_empty(
        self, qtbot: QtBot, file_type_section: FileTypeSection
    ) -> None:
        """Test that section is hidden when empty."""
        # First add files
        file_type_section.set_files([create_scene_file()])
        process_qt_events()
        assert file_type_section.isHidden() is False

        # Then clear
        file_type_section.set_files([])
        process_qt_events()

        # Section should be hidden when empty
        assert file_type_section.isHidden() is True

    def test_clear_removes_all_files(
        self, qtbot: QtBot, file_type_section: FileTypeSection
    ) -> None:
        """Test that clear removes all files."""
        file_type_section.set_files(
            [create_scene_file(), create_scene_file(name="other.3de")]
        )
        process_qt_events()

        file_type_section.clear()
        process_qt_events()

        assert "(0)" in file_type_section._chip_button.text()
        # Section should be hidden when cleared
        assert file_type_section.isHidden() is True


# ============================================================================
# Test ShotFilesPanel
# ============================================================================


class TestShotFilesPanel:
    """Test ShotFilesPanel widget."""

    def test_init_creates_sections_for_all_file_types(
        self, qtbot: QtBot, shot_files_panel: ShotFilesPanel
    ) -> None:
        """Test that init creates sections for all file types."""
        assert hasattr(shot_files_panel, "_sections")
        assert FileType.THREEDE in shot_files_panel._sections
        assert FileType.MAYA in shot_files_panel._sections
        assert FileType.NUKE in shot_files_panel._sections

    def test_init_creates_scroll_area(
        self, qtbot: QtBot, shot_files_panel: ShotFilesPanel
    ) -> None:
        """Test that init creates scroll area for expansion."""
        assert hasattr(shot_files_panel, "_scroll_area")
        assert shot_files_panel._scroll_area is not None

    def test_init_creates_finder(
        self, qtbot: QtBot, shot_files_panel: ShotFilesPanel
    ) -> None:
        """Test that init creates ShotFileFinder."""
        assert hasattr(shot_files_panel, "_finder")
        assert shot_files_panel._finder is not None


class TestShotFilesPanelSetShot:
    """Test ShotFilesPanel.set_shot functionality."""

    def test_set_shot_none_clears_all(
        self, qtbot: QtBot, shot_files_panel: ShotFilesPanel, mocker
    ) -> None:
        """Test that set_shot(None) clears all sections."""
        # Mock finder to return files
        mock_find = mocker.patch.object(shot_files_panel._finder, "find_all_files")
        mock_find.return_value = {
            FileType.THREEDE: [create_scene_file()],
            FileType.MAYA: [create_scene_file(FileType.MAYA, "scene.ma")],
            FileType.NUKE: [],
        }
        shot_files_panel.set_shot(ShotDouble())  # type: ignore[arg-type]
        process_qt_events()

        # Now clear
        shot_files_panel.set_shot(None)
        process_qt_events()

        # All sections should be hidden (empty)
        for section in shot_files_panel._sections.values():
            assert section.isHidden() is True

    def test_set_shot_calls_finder(
        self, qtbot: QtBot, shot_files_panel: ShotFilesPanel, mocker
    ) -> None:
        """Test that set_shot calls the finder with the shot."""
        shot = ShotDouble()

        mock_find = mocker.patch.object(shot_files_panel._finder, "find_all_files")
        mock_find.return_value = {}
        shot_files_panel.set_shot(shot)  # type: ignore[arg-type]
        process_qt_events()

        mock_find.assert_called_once_with(shot)

    def test_set_shot_updates_sections_with_files(
        self, qtbot: QtBot, shot_files_panel: ShotFilesPanel, mocker
    ) -> None:
        """Test that set_shot populates sections with found files."""
        threede_files = [create_scene_file(FileType.THREEDE, "scene1.3de")]
        maya_files = [
            create_scene_file(FileType.MAYA, "scene1.ma"),
            create_scene_file(FileType.MAYA, "scene2.ma"),
        ]

        mock_find = mocker.patch.object(shot_files_panel._finder, "find_all_files")
        mock_find.return_value = {
            FileType.THREEDE: threede_files,
            FileType.MAYA: maya_files,
            FileType.NUKE: [],
        }
        shot_files_panel.set_shot(ShotDouble())  # type: ignore[arg-type]
        process_qt_events()

        # Check sections are updated (use isHidden which works without parent being shown)
        # Sections with files should NOT be hidden
        assert shot_files_panel._sections[FileType.THREEDE].isHidden() is False
        assert shot_files_panel._sections[FileType.MAYA].isHidden() is False
        # Section without files should be hidden
        assert shot_files_panel._sections[FileType.NUKE].isHidden() is True

        # Check counts in chip buttons
        assert "(1)" in shot_files_panel._sections[FileType.THREEDE]._chip_button.text()
        assert "(2)" in shot_files_panel._sections[FileType.MAYA]._chip_button.text()

    def test_set_shot_handles_finder_exception(
        self, qtbot: QtBot, shot_files_panel: ShotFilesPanel, mocker
    ) -> None:
        """Test that set_shot handles finder exceptions gracefully."""
        mock_find = mocker.patch.object(shot_files_panel._finder, "find_all_files")
        mock_find.side_effect = Exception("Test error")
        # Should not raise
        shot_files_panel.set_shot(ShotDouble())  # type: ignore[arg-type]
        process_qt_events()

        # All sections should be hidden (cleared on error)
        for section in shot_files_panel._sections.values():
            assert section.isHidden() is True

    def test_set_shot_stores_current_shot(
        self, qtbot: QtBot, shot_files_panel: ShotFilesPanel, mocker
    ) -> None:
        """Test that set_shot stores the current shot reference."""
        shot = ShotDouble()

        mock_find = mocker.patch.object(shot_files_panel._finder, "find_all_files")
        mock_find.return_value = {}
        shot_files_panel.set_shot(shot)  # type: ignore[arg-type]

        assert shot_files_panel._current_shot is shot


class TestShotFilesPanelSignalRouting:
    """Test signal routing through ShotFilesPanel."""


# ============================================================================
# Test SceneFile Relative Age
# ============================================================================


class TestSceneFileRelativeAge:
    """Test SceneFile relative_age property."""

    def test_just_now(self) -> None:
        """Test that recent files show 'just now'."""
        from datetime import timedelta

        sf = SceneFile(
            path=Path("/test/scene.3de"),
            file_type=FileType.THREEDE,
            modified_time=datetime.now() - timedelta(seconds=30),  # noqa: DTZ005
            user="test",
        )
        assert sf.relative_age == "just now"

    def test_minutes_ago(self) -> None:
        """Test that files modified minutes ago show correct text."""
        from datetime import timedelta

        sf = SceneFile(
            path=Path("/test/scene.3de"),
            file_type=FileType.THREEDE,
            modified_time=datetime.now() - timedelta(minutes=5),  # noqa: DTZ005
            user="test",
        )
        assert "5 minutes ago" in sf.relative_age

    def test_hours_ago(self) -> None:
        """Test that files modified hours ago show correct text."""
        from datetime import timedelta

        sf = SceneFile(
            path=Path("/test/scene.3de"),
            file_type=FileType.THREEDE,
            modified_time=datetime.now() - timedelta(hours=3),  # noqa: DTZ005
            user="test",
        )
        assert "3 hours ago" in sf.relative_age

    def test_yesterday(self) -> None:
        """Test that files modified yesterday show 'yesterday'."""
        from datetime import timedelta

        sf = SceneFile(
            path=Path("/test/scene.3de"),
            file_type=FileType.THREEDE,
            modified_time=datetime.now() - timedelta(days=1),  # noqa: DTZ005
            user="test",
        )
        assert "day ago" in sf.relative_age  # arrow: "a day ago"

    def test_days_ago(self) -> None:
        """Test that files modified days ago show correct text."""
        from datetime import timedelta

        sf = SceneFile(
            path=Path("/test/scene.3de"),
            file_type=FileType.THREEDE,
            modified_time=datetime.now() - timedelta(days=3),  # noqa: DTZ005
            user="test",
        )
        assert "3 days ago" in sf.relative_age

    def test_weeks_ago(self) -> None:
        """Test that files modified weeks ago show correct text."""
        from datetime import timedelta

        sf = SceneFile(
            path=Path("/test/scene.3de"),
            file_type=FileType.THREEDE,
            modified_time=datetime.now() - timedelta(days=14),  # noqa: DTZ005
            user="test",
        )
        assert "2 weeks ago" in sf.relative_age

    def test_singular_forms(self) -> None:
        """Test that singular forms are used correctly."""
        from datetime import timedelta

        sf = SceneFile(
            path=Path("/test/scene.3de"),
            file_type=FileType.THREEDE,
            modified_time=datetime.now() - timedelta(minutes=1),  # noqa: DTZ005
            user="test",
        )
        assert "minute ago" in sf.relative_age  # arrow: "a minute ago"
