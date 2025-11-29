"""Tests for FilesSection widget."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt

from files_section import FilesSection
from scene_file import FileType, SceneFile
from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


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
            SceneFile(
                path=Path("/path/to/comp_v011.nk"),
                file_type=FileType.NUKE,
                modified_time=now,
                user="compositor",
                version=11,
            ),
        ],
        FileType.MAYA: [],
    }


class TestFilesSectionInit:
    """Tests for FilesSection initialization."""

    def test_default_collapsed(self, qtbot: QtBot) -> None:
        """Section is collapsed by default."""
        section = FilesSection()
        qtbot.addWidget(section)

        assert not section.is_expanded()

    def test_custom_expanded_state(self, qtbot: QtBot) -> None:
        """Can be created expanded."""
        section = FilesSection(expanded=True)
        qtbot.addWidget(section)

        assert section.is_expanded()

    def test_custom_title(self, qtbot: QtBot) -> None:
        """Can set custom title."""
        section = FilesSection(title="Scene Files")
        qtbot.addWidget(section)

        assert "Scene Files" in section._section._header_button.text()

    def test_parent_parameter(self, qtbot: QtBot) -> None:
        """Accepts parent parameter."""
        from PySide6.QtWidgets import QWidget

        parent = QWidget()
        section = FilesSection(parent=parent)
        qtbot.addWidget(parent)

        assert section.parent() is parent


class TestFilesSectionFiles:
    """Tests for file management."""

    def test_set_files(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Can set files."""
        section = FilesSection()
        qtbot.addWidget(section)

        section.set_files(sample_files)

        assert section.get_total_file_count() == 3

    def test_header_shows_count(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Header shows total file count."""
        section = FilesSection()
        qtbot.addWidget(section)

        section.set_files(sample_files)

        header_text = section._section._header_button.text()
        assert "(3)" in header_text

    def test_clear_files(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Can clear all files."""
        section = FilesSection()
        qtbot.addWidget(section)

        section.set_files(sample_files)
        section.clear_files()

        assert section.get_total_file_count() == 0

    def test_header_no_count_when_empty(self, qtbot: QtBot) -> None:
        """Header shows no count when empty."""
        section = FilesSection()
        qtbot.addWidget(section)

        section.set_files({})

        header_text = section._section._header_button.text()
        # Should not have count in parentheses
        assert "(" not in header_text or "(0)" not in header_text


class TestFilesSectionExpansion:
    """Tests for expansion state."""

    def test_set_expanded(self, qtbot: QtBot) -> None:
        """Can programmatically expand/collapse."""
        section = FilesSection()
        qtbot.addWidget(section)

        section.set_expanded(True)
        assert section.is_expanded()

        section.set_expanded(False)
        assert not section.is_expanded()

    def test_expanded_changed_signal(self, qtbot: QtBot) -> None:
        """Signal emitted when expansion changes."""
        section = FilesSection()
        qtbot.addWidget(section)

        with qtbot.waitSignal(section.expanded_changed, timeout=1000) as blocker:
            section.set_expanded(True)

        assert blocker.args == [True]


class TestFilesSectionSignals:
    """Tests for signal forwarding."""

    def test_file_selected_forwarded(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """file_selected signal is forwarded from FilesTabWidget."""
        section = FilesSection(expanded=True)
        qtbot.addWidget(section)
        section.set_files(sample_files)
        section.show()
        process_qt_events()

        # Get the underlying table
        table = section._files_tab._tables[FileType.THREEDE]

        with qtbot.waitSignal(section.file_selected, timeout=1000) as blocker:
            # Click the first row
            index = section._files_tab._models[FileType.THREEDE].index(0, 0)
            rect = table.visualRect(index)
            qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
            process_qt_events()

        assert isinstance(blocker.args[0], SceneFile)


class TestFilesSectionNavigation:
    """Tests for tab navigation."""

    def test_set_current_tab(self, qtbot: QtBot) -> None:
        """Can set current tab by FileType."""
        section = FilesSection()
        qtbot.addWidget(section)

        section.set_current_tab(FileType.MAYA)

        # Verify the underlying tab widget switched
        expected_idx = section._files_tab._tab_indices[FileType.MAYA]
        assert section._files_tab._tab_widget.currentIndex() == expected_idx
