"""Tests for FileTableModel."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from dcc.scene_file import FileType, SceneFile
from ui.files_tab_widget import FileTableModel


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
        """Model has 4 columns (Version, Age, User, Comment)."""
        model = FileTableModel()
        assert model.columnCount() == 4

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
        assert model.headerData(3, Qt.Orientation.Horizontal) == "Comment"

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

    def test_comment_column_empty_when_no_comment(self, qtbot: QtBot) -> None:
        """Comment column shows empty string when file has no comment."""
        model = FileTableModel()
        file = SceneFile(
            path=Path("/path/to/scene_v001.ma"),
            file_type=FileType.MAYA,
            modified_time=datetime.now(),  # noqa: DTZ005
            user="artist",
            version=1,
        )
        model.set_files([file])
        index = model.index(0, 3)
        assert model.data(index, Qt.ItemDataRole.DisplayRole) == ""

    def test_comment_column_shows_comment(self, qtbot: QtBot) -> None:
        """Comment column shows the comment text."""
        model = FileTableModel()
        file = SceneFile(
            path=Path("/path/to/scene_v001.ma"),
            file_type=FileType.MAYA,
            modified_time=datetime.now(),  # noqa: DTZ005
            user="artist",
            version=1,
            comment="Fixed camera drift",
        )
        model.set_files([file])
        index = model.index(0, 3)
        assert model.data(index, Qt.ItemDataRole.DisplayRole) == "Fixed camera drift"

    def test_tooltip_includes_comment(self, qtbot: QtBot) -> None:
        """Tooltip includes comment when present."""
        model = FileTableModel()
        file = SceneFile(
            path=Path("/path/to/scene_v001.ma"),
            file_type=FileType.MAYA,
            modified_time=datetime.now(),  # noqa: DTZ005
            user="artist",
            version=1,
            comment="Fixed camera drift",
        )
        model.set_files([file])
        index = model.index(0, 0)
        tooltip = model.data(index, Qt.ItemDataRole.ToolTipRole)
        assert "Comment: Fixed camera drift" in tooltip

    def test_tooltip_no_comment_line_when_none(self, qtbot: QtBot) -> None:
        """Tooltip omits comment line when no comment."""
        model = FileTableModel()
        file = SceneFile(
            path=Path("/path/to/scene_v001.ma"),
            file_type=FileType.MAYA,
            modified_time=datetime.now(),  # noqa: DTZ005
            user="artist",
            version=1,
        )
        model.set_files([file])
        index = model.index(0, 0)
        tooltip = model.data(index, Qt.ItemDataRole.ToolTipRole)
        assert "Comment" not in tooltip

    def test_update_file_comment(self, qtbot: QtBot) -> None:
        """update_file_comment replaces the comment and refreshes the row."""
        model = FileTableModel()
        file = SceneFile(
            path=Path("/path/to/scene_v001.ma"),
            file_type=FileType.MAYA,
            modified_time=datetime.now(),  # noqa: DTZ005
            user="artist",
            version=1,
        )
        model.set_files([file])

        updated = model.update_file_comment(0, "Camera fix")
        assert updated is not None
        assert updated.comment == "Camera fix"

        index = model.index(0, 3)
        assert model.data(index, Qt.ItemDataRole.DisplayRole) == "Camera fix"

    def test_update_file_comment_empty_clears(self, qtbot: QtBot) -> None:
        """Empty string sets comment to None."""
        model = FileTableModel()
        file = SceneFile(
            path=Path("/path/to/scene_v001.ma"),
            file_type=FileType.MAYA,
            modified_time=datetime.now(),  # noqa: DTZ005
            user="artist",
            version=1,
            comment="Old comment",
        )
        model.set_files([file])

        updated = model.update_file_comment(0, "")
        assert updated is not None
        assert updated.comment is None

    def test_update_file_comment_out_of_range(self, qtbot: QtBot) -> None:
        """Returns None for out-of-range row."""
        model = FileTableModel()
        assert model.update_file_comment(0, "nope") is None
        assert model.update_file_comment(-1, "nope") is None
