"""Tests for shot_file_finder module."""
# ruff: noqa: DTZ005  # Tests use naive local time to match production behavior

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dcc.scene_file import FileType, SceneFile
from shots.shot_file_finder import ShotFileFinder


class TestSceneFile:
    """Tests for SceneFile dataclass."""

    @pytest.mark.parametrize(
        ("offset", "expected_substring", "exact_match"),
        [
            (timedelta(0), "just now", True),
            (timedelta(minutes=30), "minute", False),
            (timedelta(hours=5), "hour", False),
            (timedelta(days=1), "yesterday at", False),
            (timedelta(days=5), "days ago at", False),
        ],
    )
    def test_scene_file_relative_age(
        self, offset: timedelta, expected_substring: str, exact_match: bool
    ) -> None:
        """Test relative_age for files at various ages."""
        now = datetime.now()
        scene_file = SceneFile(
            path=Path("/test/file.3de"),
            file_type=FileType.THREEDE,
            modified_time=now - offset,
            user="test",
        )
        if exact_match:
            assert scene_file.relative_age == expected_substring
        else:
            assert expected_substring in scene_file.relative_age

    def test_scene_file_colors(self) -> None:
        """Test that each file type has a color."""
        now = datetime.now()
        path = Path("/test/file.ext")

        for file_type in FileType:
            scene_file = SceneFile(
                path=path,
                file_type=file_type,
                modified_time=now,
                user="test",
            )
            assert scene_file.color.startswith("#")
            assert len(scene_file.color) == 7  # #RRGGBB format


class TestShotFileFinder:
    """Tests for ShotFileFinder class."""

    def test_extract_version_valid(self) -> None:
        """Test version extraction from valid filenames."""
        finder = ShotFileFinder()

        assert finder._extract_version(Path("scene_v001.3de")) == 1
        assert finder._extract_version(Path("maya_scene_v123.ma")) == 123
        assert finder._extract_version(Path("nuke_script_v999.nk")) == 999

    def test_extract_version_invalid(self) -> None:
        """Test version extraction from invalid filenames."""
        finder = ShotFileFinder()

        assert finder._extract_version(Path("scene.3de")) is None
        assert finder._extract_version(Path("scene_v1.3de")) is None  # Need 3 digits
        assert (
            finder._extract_version(Path("scene_v1234.3de")) is None
        )  # Too many digits

    def test_extract_user_from_path(self) -> None:
        """Test user extraction from file paths."""
        finder = ShotFileFinder()

        path = Path(
            "/shows/test/shots/sq010/sq010_sh0010/user/gabriel-h/mm/3de/scene.3de"
        )
        assert finder._extract_user_from_path(path) == "gabriel-h"

        path = Path(
            "/shows/test/shots/sq010/sq010_sh0010/user/john.doe/maya/scenes/test.ma"
        )
        assert finder._extract_user_from_path(path) == "john.doe"

    def test_extract_user_from_path_no_user(self) -> None:
        """Test user extraction when path doesn't contain 'user' segment."""
        finder = ShotFileFinder()

        path = Path("/tmp/test/scene.3de")
        assert finder._extract_user_from_path(path) == "unknown"

    @patch.object(ShotFileFinder, "_find_threede_files")
    @patch.object(ShotFileFinder, "_find_maya_files")
    @patch.object(ShotFileFinder, "_find_nuke_files")
    def test_find_all_files_returns_grouped_results(
        self,
        mock_nuke: MagicMock,
        mock_maya: MagicMock,
        mock_threede: MagicMock,
    ) -> None:
        """Test that find_all_files returns properly grouped results."""
        # Create mock shot
        mock_shot = MagicMock()
        mock_shot.workspace_path = "/shows/test/shots/sq010/sq010_sh0010"

        # Set up mock returns
        mock_threede.return_value = [
            SceneFile(
                path=Path("/test/scene.3de"),
                file_type=FileType.THREEDE,
                modified_time=datetime.now(),
                user="test",
            )
        ]
        mock_maya.return_value = []
        mock_nuke.return_value = []

        finder = ShotFileFinder()
        result = finder.find_all_files(mock_shot)

        assert FileType.THREEDE in result
        assert FileType.MAYA in result
        assert FileType.NUKE in result
        assert len(result[FileType.THREEDE]) == 1
        assert len(result[FileType.MAYA]) == 0
        assert len(result[FileType.NUKE]) == 0

    def test_find_all_files_empty_workspace(self, tmp_path: Path) -> None:
        """Test find_all_files with empty workspace."""
        # Create mock shot with empty workspace
        mock_shot = MagicMock()
        mock_shot.workspace_path = str(tmp_path)

        finder = ShotFileFinder()
        result = finder.find_all_files(mock_shot)

        # All types should be present but empty
        assert len(result[FileType.THREEDE]) == 0
        assert len(result[FileType.MAYA]) == 0
        assert len(result[FileType.NUKE]) == 0

    def test_find_all_files_nonexistent_workspace(self) -> None:
        """Test find_all_files with non-existent workspace."""
        mock_shot = MagicMock()
        mock_shot.workspace_path = "/nonexistent/path"

        finder = ShotFileFinder()
        result = finder.find_all_files(mock_shot)

        # All types should be present but empty
        assert len(result[FileType.THREEDE]) == 0
        assert len(result[FileType.MAYA]) == 0
        assert len(result[FileType.NUKE]) == 0
