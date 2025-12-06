"""Tests for ShotHeader widget."""

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
from shot_header import DCCStatus, ShotHeader
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


class TestShotHeaderInit:
    """Tests for ShotHeader initialization."""

    def test_default_empty_message(self, qtbot: QtBot) -> None:
        """Default empty message is displayed."""
        header = ShotHeader()
        qtbot.addWidget(header)

        assert "No Shot Selected" in header._shot_name_label.text()

    def test_custom_parent(self, qtbot: QtBot) -> None:
        """Can be created with parent widget."""
        from PySide6.QtWidgets import QWidget

        parent = QWidget()
        header = ShotHeader(parent=parent)
        qtbot.addWidget(parent)

        assert header.parent() is parent


class TestShotHeaderDisplay:
    """Tests for shot information display."""

    def test_set_shot_updates_display(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Setting shot updates all display fields."""
        header = ShotHeader()
        qtbot.addWidget(header)

        header.set_shot(mock_shot)

        assert "sq010_sh0010" in header._shot_name_label.text()
        assert "myshow" in header._show_sequence_label.text()
        assert "sq010" in header._show_sequence_label.text()
        assert "/shows/myshow/shots/sq010/sh0010" in header._path_label.text()

    def test_clear_shot_resets_display(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Clearing shot resets display to empty state."""
        header = ShotHeader()
        qtbot.addWidget(header)

        header.set_shot(mock_shot)
        header.set_shot(None)

        assert "No Shot Selected" in header._shot_name_label.text()
        assert header._show_sequence_label.text() == ""
        assert header._path_label.text() == ""

    def test_set_empty_message(self, qtbot: QtBot) -> None:
        """Custom empty message can be set."""
        header = ShotHeader()
        qtbot.addWidget(header)

        header.set_empty_message("Select a Shot")

        assert "Select a Shot" in header._shot_name_label.text()


class TestShotHeaderCopyPath:
    """Tests for path copy functionality."""

    def test_copy_button_emits_signal(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Copy button emits path_copy_requested signal."""
        header = ShotHeader()
        qtbot.addWidget(header)
        header.set_shot(mock_shot)

        with qtbot.waitSignal(header.path_copy_requested, timeout=1000):
            qtbot.mouseClick(header._copy_path_btn, Qt.MouseButton.LeftButton)
            process_qt_events()

    def test_copy_button_copies_to_clipboard(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Copy button copies workspace path to clipboard."""
        from PySide6.QtWidgets import QApplication

        header = ShotHeader()
        qtbot.addWidget(header)
        header.set_shot(mock_shot)

        qtbot.mouseClick(header._copy_path_btn, Qt.MouseButton.LeftButton)
        process_qt_events()

        clipboard = QApplication.clipboard()
        if clipboard:
            assert clipboard.text() == "/shows/myshow/shots/sq010/sh0010"


class TestShotHeaderDCCStatus:
    """Tests for DCC status strip."""

    def test_set_dcc_status_shows_labels(self, qtbot: QtBot) -> None:
        """Setting DCC status makes labels visible."""
        header = ShotHeader()
        qtbot.addWidget(header)
        header.show()
        process_qt_events()

        status = {
            FileType.THREEDE: DCCStatus(version="v005", age="21 minutes ago"),
        }
        header.set_dcc_status(status)
        process_qt_events()

        label = header._status_labels[FileType.THREEDE]
        assert label.isVisible()
        assert "v005" in label.text()
        assert "3DE" in label.text()

    def test_empty_status_hides_label(self, qtbot: QtBot) -> None:
        """Empty status hides the label."""
        header = ShotHeader()
        qtbot.addWidget(header)

        status = {
            FileType.THREEDE: DCCStatus(version=None),
        }
        header.set_dcc_status(status)

        label = header._status_labels[FileType.THREEDE]
        assert not label.isVisible()

    def test_multiple_dcc_statuses(self, qtbot: QtBot) -> None:
        """Multiple DCC statuses displayed correctly."""
        header = ShotHeader()
        qtbot.addWidget(header)
        header.show()
        process_qt_events()

        status = {
            FileType.THREEDE: DCCStatus(version="v005", age="21 minutes ago"),
            FileType.NUKE: DCCStatus(version="v012", age="2 hours ago"),
            FileType.MAYA: DCCStatus(version=None),  # No maya files
        }
        header.set_dcc_status(status)
        process_qt_events()

        assert header._status_labels[FileType.THREEDE].isVisible()
        assert header._status_labels[FileType.NUKE].isVisible()
        assert not header._status_labels[FileType.MAYA].isVisible()

    def test_age_shortened_in_display(self, qtbot: QtBot) -> None:
        """Age strings are shortened for compact display."""
        header = ShotHeader()
        qtbot.addWidget(header)

        status = {
            FileType.THREEDE: DCCStatus(version="v005", age="21 minutes ago"),
        }
        header.set_dcc_status(status)

        label = header._status_labels[FileType.THREEDE]
        text = label.text()
        # Should be shortened: "21 minutes ago" -> "21m"
        assert "21m" in text
        assert "minutes" not in text


class TestShotHeaderUpdateFromFiles:
    """Tests for updating status from scene files."""

    def test_update_from_files(self, qtbot: QtBot) -> None:
        """Status updated correctly from scene files."""
        header = ShotHeader()
        qtbot.addWidget(header)
        header.show()
        process_qt_events()

        # Create mock scene files
        threede_file = SceneFile(
            path=Path("/path/to/scene_v005.3de"),
            file_type=FileType.THREEDE,
            modified_time=datetime.now(),  # noqa: DTZ005
            user="artist1",
            version=5,
        )

        nuke_file = SceneFile(
            path=Path("/path/to/comp_v012.nk"),
            file_type=FileType.NUKE,
            modified_time=datetime.now(),  # noqa: DTZ005
            user="artist2",
            version=12,
        )

        files_by_type = {
            FileType.THREEDE: [threede_file],
            FileType.NUKE: [nuke_file],
            FileType.MAYA: [],
        }

        header.update_from_files(files_by_type)
        process_qt_events()

        # Check status updated
        assert header._status_labels[FileType.THREEDE].isVisible()
        assert "v005" in header._status_labels[FileType.THREEDE].text()

        assert header._status_labels[FileType.NUKE].isVisible()
        assert "v012" in header._status_labels[FileType.NUKE].text()

        assert not header._status_labels[FileType.MAYA].isVisible()

    def test_uses_first_file_as_latest(self, qtbot: QtBot) -> None:
        """Uses first file in list as latest (assumes sorted)."""
        header = ShotHeader()
        qtbot.addWidget(header)

        # Multiple files - first should be used
        files = [
            SceneFile(
                path=Path("/path/scene_v010.3de"),
                file_type=FileType.THREEDE,
                modified_time=datetime.now(),  # noqa: DTZ005
                user="artist",
                version=10,
            ),
            SceneFile(
                path=Path("/path/scene_v005.3de"),
                file_type=FileType.THREEDE,
                modified_time=datetime.now(),  # noqa: DTZ005
                user="artist",
                version=5,
            ),
        ]

        header.update_from_files({FileType.THREEDE: files})

        # Should use v010 (first in list)
        assert "v010" in header._status_labels[FileType.THREEDE].text()


class TestShotHeaderShortenAge:
    """Tests for age string shortening."""

    def test_shorten_minutes(self, qtbot: QtBot) -> None:
        """Minutes shortened correctly."""
        header = ShotHeader()
        qtbot.addWidget(header)

        assert header._shorten_age("21 minutes ago") == "21m"
        assert header._shorten_age("1 minute ago") == "1m"

    def test_shorten_hours(self, qtbot: QtBot) -> None:
        """Hours shortened correctly."""
        header = ShotHeader()
        qtbot.addWidget(header)

        assert header._shorten_age("2 hours ago") == "2h"
        assert header._shorten_age("1 hour ago") == "1h"

    def test_shorten_days(self, qtbot: QtBot) -> None:
        """Days shortened correctly."""
        header = ShotHeader()
        qtbot.addWidget(header)

        assert header._shorten_age("3 days ago") == "3d"
        assert header._shorten_age("1 day ago") == "1d"
        assert header._shorten_age("yesterday") == "1d"

    def test_shorten_weeks(self, qtbot: QtBot) -> None:
        """Weeks shortened correctly."""
        header = ShotHeader()
        qtbot.addWidget(header)

        assert header._shorten_age("2 weeks ago") == "2w"
        assert header._shorten_age("1 week ago") == "1w"

    def test_shorten_just_now(self, qtbot: QtBot) -> None:
        """Just now shortened correctly."""
        header = ShotHeader()
        qtbot.addWidget(header)

        assert header._shorten_age("just now") == "now"
