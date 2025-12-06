"""Tests for FilesTabWidget and FileTableModel."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from files_tab_widget import FilesTabWidget, FileTableModel
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
            SceneFile(
                path=Path("/path/to/scene_v004.3de"),
                file_type=FileType.THREEDE,
                modified_time=now,
                user="artist2",
                version=4,
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


class TestFileTableModel:
    """Tests for FileTableModel."""

    def test_empty_model(self, qtbot: QtBot) -> None:
        """Empty model has zero rows."""
        model = FileTableModel()
        assert model.rowCount() == 0

    def test_column_count(self, qtbot: QtBot) -> None:
        """Model has 3 columns (Version, Age, User)."""
        model = FileTableModel()
        assert model.columnCount() == 3

    def test_set_files(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Setting files updates row count."""
        model = FileTableModel()
        model.set_files(sample_files[FileType.THREEDE])

        assert model.rowCount() == 2

    def test_get_file(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Can retrieve file by row index."""
        model = FileTableModel()
        model.set_files(sample_files[FileType.THREEDE])

        file = model.get_file(0)
        assert file is not None
        assert file.version == 5

    def test_get_file_out_of_bounds(self, qtbot: QtBot) -> None:
        """Returns None for out of bounds index."""
        model = FileTableModel()
        assert model.get_file(-1) is None
        assert model.get_file(0) is None
        assert model.get_file(100) is None

    def test_header_data(self, qtbot: QtBot) -> None:
        """Header shows column names."""
        model = FileTableModel()

        assert model.headerData(0, Qt.Orientation.Horizontal) == "Version"
        assert model.headerData(1, Qt.Orientation.Horizontal) == "Age"
        assert model.headerData(2, Qt.Orientation.Horizontal) == "User"

    def test_display_data_version(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Version column shows formatted version."""
        model = FileTableModel()
        model.set_files(sample_files[FileType.THREEDE])

        index = model.index(0, 0)
        data = model.data(index, Qt.ItemDataRole.DisplayRole)
        assert data == "v005"

    def test_display_data_user(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """User column shows username."""
        model = FileTableModel()
        model.set_files(sample_files[FileType.THREEDE])

        index = model.index(0, 2)
        data = model.data(index, Qt.ItemDataRole.DisplayRole)
        assert data == "artist1"

    def test_user_role_returns_scene_file(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """UserRole returns the SceneFile object."""
        model = FileTableModel()
        model.set_files(sample_files[FileType.THREEDE])

        index = model.index(0, 0)
        data = model.data(index, Qt.ItemDataRole.UserRole)
        assert isinstance(data, SceneFile)
        assert data.version == 5

    def test_tooltip_includes_path(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Tooltip includes file path."""
        model = FileTableModel()
        model.set_files(sample_files[FileType.THREEDE])

        index = model.index(0, 0)
        tooltip = model.data(index, Qt.ItemDataRole.ToolTipRole)
        assert "/path/to/scene_v005.3de" in tooltip


class TestFilesTabWidgetInit:
    """Tests for FilesTabWidget initialization."""

    def test_creates_tabs_for_all_file_types(self, qtbot: QtBot) -> None:
        """Creates a tab for each FileType."""
        widget = FilesTabWidget()
        qtbot.addWidget(widget)

        assert len(widget._tab_indices) == len(FileType)
        for file_type in FileType:
            assert file_type in widget._tab_indices

    def test_parent_parameter(self, qtbot: QtBot) -> None:
        """Accepts parent parameter."""
        from PySide6.QtWidgets import QWidget

        parent = QWidget()
        widget = FilesTabWidget(parent=parent)
        qtbot.addWidget(parent)

        assert widget.parent() is parent


class TestFilesTabWidgetFiles:
    """Tests for file management in FilesTabWidget."""

    def test_set_files(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Setting files populates models."""
        widget = FilesTabWidget()
        qtbot.addWidget(widget)

        widget.set_files(sample_files)

        # Check 3DE tab has 2 files
        model = widget._models[FileType.THREEDE]
        assert model.rowCount() == 2

        # Check Nuke tab has 1 file
        model = widget._models[FileType.NUKE]
        assert model.rowCount() == 1

        # Check Maya tab is empty
        model = widget._models[FileType.MAYA]
        assert model.rowCount() == 0

    def test_tab_text_shows_count(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Tab text shows file count."""
        widget = FilesTabWidget()
        qtbot.addWidget(widget)

        widget.set_files(sample_files)

        # Get 3DE tab text
        idx = widget._tab_indices[FileType.THREEDE]
        text = widget._tab_widget.tabText(idx)
        assert "(2)" in text

    def test_clear_files(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Clearing files empties all models."""
        widget = FilesTabWidget()
        qtbot.addWidget(widget)

        widget.set_files(sample_files)
        widget.clear_files()

        for model in widget._models.values():
            assert model.rowCount() == 0

    def test_get_total_file_count(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Returns total file count across tabs."""
        widget = FilesTabWidget()
        qtbot.addWidget(widget)

        widget.set_files(sample_files)

        assert widget.get_total_file_count() == 3  # 2 + 1 + 0


class TestFilesTabWidgetSignals:
    """Tests for signal emission."""

    def test_click_emits_file_selected(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Single click emits file_selected signal."""
        widget = FilesTabWidget()
        qtbot.addWidget(widget)
        widget.set_files(sample_files)
        widget.show()
        process_qt_events()

        # Get the 3DE table
        table = widget._tables[FileType.THREEDE]

        with qtbot.waitSignal(widget.file_selected, timeout=1000) as blocker:
            # Click the first row
            index = widget._models[FileType.THREEDE].index(0, 0)
            rect = table.visualRect(index)
            qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
            process_qt_events()

        assert isinstance(blocker.args[0], SceneFile)

    def test_double_click_emits_file_open_requested(
        self, qtbot: QtBot, sample_files: dict[FileType, list[SceneFile]]
    ) -> None:
        """Double click emits file_open_requested signal."""
        widget = FilesTabWidget()
        qtbot.addWidget(widget)
        widget.set_files(sample_files)
        widget.show()
        process_qt_events()

        # Test via direct signal emission (mouseDClick is unreliable in headless Qt)
        with qtbot.waitSignal(widget.file_open_requested, timeout=1000) as blocker:
            # Simulate double-click by calling the handler directly
            index = widget._models[FileType.THREEDE].index(0, 0)
            widget._on_row_double_clicked(FileType.THREEDE, index)
            process_qt_events()

        assert isinstance(blocker.args[0], SceneFile)


class TestFilesTabWidgetNavigation:
    """Tests for tab navigation."""

    def test_set_current_tab(self, qtbot: QtBot) -> None:
        """Can set current tab by FileType."""
        widget = FilesTabWidget()
        qtbot.addWidget(widget)

        widget.set_current_tab(FileType.NUKE)

        assert widget._tab_widget.currentIndex() == widget._tab_indices[FileType.NUKE]
