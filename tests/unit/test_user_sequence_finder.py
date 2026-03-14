"""Unit tests for UserSequenceFinder."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from user_sequence_finder import UserSequenceFinder


class TestFindMayaPlayblasts:
    """Test find_maya_playblasts method."""

    def test_finds_playblast_with_single_version(self, tmp_path: Path) -> None:
        """Test finding playblast with a single version."""
        workspace = tmp_path / "workspace"
        playblast_dir = workspace / "user" / "john" / "mm" / "maya" / "playblast"
        wireframe_dir = playblast_dir / "Wireframe" / "v001"
        wireframe_dir.mkdir(parents=True)

        # Create PNG sequence files
        for frame in range(1001, 1011):
            (wireframe_dir / f"Wireframe.{frame}.png").touch()

        result = UserSequenceFinder.find_maya_playblasts(
            str(workspace), username="john"
        )

        assert len(result) == 1
        seq = result[0]
        assert seq.sequence_type == "maya_playblast"
        assert seq.render_type == "Wireframe"
        assert seq.version == 1
        assert seq.user == "john"
        assert seq.first_frame == 1001
        assert seq.last_frame == 1010

    def test_finds_latest_version_only(self, tmp_path: Path) -> None:
        """Test that only latest version is returned for each type."""
        workspace = tmp_path / "workspace"
        playblast_dir = workspace / "user" / "alice" / "mm" / "maya" / "playblast"

        # Create multiple versions
        for version in ["v001", "v002", "v003"]:
            version_dir = playblast_dir / "Cones" / version
            version_dir.mkdir(parents=True)
            for frame in range(1001, 1005):
                (version_dir / f"Cones.{frame}.png").touch()

        result = UserSequenceFinder.find_maya_playblasts(
            str(workspace), username="alice"
        )

        assert len(result) == 1
        assert result[0].version == 3  # Latest version
        assert result[0].render_type == "Cones"

    def test_finds_multiple_playblast_types(self, tmp_path: Path) -> None:
        """Test finding multiple playblast types."""
        workspace = tmp_path / "workspace"
        playblast_dir = workspace / "user" / "bob" / "mm" / "maya" / "playblast"

        # Create two types
        for ptype in ["Wireframe", "Cones"]:
            type_dir = playblast_dir / ptype / "v001"
            type_dir.mkdir(parents=True)
            for frame in range(1001, 1003):
                (type_dir / f"{ptype}.{frame}.png").touch()

        result = UserSequenceFinder.find_maya_playblasts(
            str(workspace), username="bob"
        )

        assert len(result) == 2
        types = {s.render_type for s in result}
        assert types == {"Wireframe", "Cones"}

    def test_returns_empty_when_path_not_exists(self, tmp_path: Path) -> None:
        """Test returns empty list when playblast path doesn't exist."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = UserSequenceFinder.find_maya_playblasts(
            str(workspace), username="nonexistent"
        )

        assert result == []

    def test_uses_current_user_when_username_not_provided(
        self, tmp_path: Path
    ) -> None:
        """Test that current username is used when not explicitly provided."""
        workspace = tmp_path / "workspace"
        playblast_dir = workspace / "user" / "testuser" / "mm" / "maya" / "playblast"
        version_dir = playblast_dir / "Test" / "v001"
        version_dir.mkdir(parents=True)
        (version_dir / "Test.1001.png").touch()

        with patch("user_sequence_finder.get_current_username", return_value="testuser"):
            result = UserSequenceFinder.find_maya_playblasts(str(workspace))

        assert len(result) == 1

    def test_ignores_non_directory_entries(self, tmp_path: Path) -> None:
        """Test that non-directory entries are ignored."""
        workspace = tmp_path / "workspace"
        playblast_dir = workspace / "user" / "john" / "mm" / "maya" / "playblast"
        playblast_dir.mkdir(parents=True)

        # Create a file (not a directory) at the type level
        (playblast_dir / "not_a_directory.txt").touch()

        # Create a valid playblast type
        version_dir = playblast_dir / "Valid" / "v001"
        version_dir.mkdir(parents=True)
        (version_dir / "Valid.1001.png").touch()

        result = UserSequenceFinder.find_maya_playblasts(
            str(workspace), username="john"
        )

        assert len(result) == 1
        assert result[0].render_type == "Valid"

    def test_sorted_by_modified_time_newest_first(self, tmp_path: Path) -> None:
        """Test results are sorted by modified time, newest first."""
        workspace = tmp_path / "workspace"
        playblast_dir = workspace / "user" / "john" / "mm" / "maya" / "playblast"

        # Create two types with different modification times
        old_dir = playblast_dir / "Old" / "v001"
        old_dir.mkdir(parents=True)
        old_file = old_dir / "Old.1001.png"
        old_file.touch()

        new_dir = playblast_dir / "New" / "v001"
        new_dir.mkdir(parents=True)
        new_file = new_dir / "New.1001.png"
        new_file.touch()

        # Set modification times (old file first, new file second)
        import time

        os.utime(old_file, (time.time() - 100, time.time() - 100))
        os.utime(new_file, (time.time(), time.time()))

        result = UserSequenceFinder.find_maya_playblasts(
            str(workspace), username="john"
        )

        assert len(result) == 2
        assert result[0].render_type == "New"  # Newest first
        assert result[1].render_type == "Old"


class TestFindNukeRenders:
    """Test find_nuke_renders method."""

    def test_finds_nuke_render_sequence(self, tmp_path: Path) -> None:
        """Test finding a Nuke render sequence."""
        workspace = tmp_path / "workspace"
        # Nuke path: {workspace}/user/{username}/mm/nuke/outputs/mm-default/scene/{plate}/camera/{type}/v###/{resolution}/exr/
        exr_dir = (
            workspace
            / "user"
            / "john"
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / "scene"
            / "FG01"
            / "camera"
            / "lineupGeo"
            / "v001"
            / "1920x1080"
            / "exr"
        )
        exr_dir.mkdir(parents=True)

        # Create EXR sequence
        for frame in range(1001, 1011):
            (exr_dir / f"render.{frame}.exr").touch()

        result = UserSequenceFinder.find_nuke_renders(str(workspace), username="john")

        assert len(result) == 1
        seq = result[0]
        assert seq.sequence_type == "nuke_render"
        assert seq.render_type == "lineupGeo"
        assert seq.version == 1
        assert seq.user == "john"
        assert seq.first_frame == 1001
        assert seq.last_frame == 1010

    def test_finds_latest_version_per_render_type(self, tmp_path: Path) -> None:
        """Test that only latest version is kept per render type."""
        workspace = tmp_path / "workspace"
        base = workspace / "user" / "alice" / "mm" / "nuke" / "outputs"

        # Create two versions of the same render type
        for version in ["v001", "v003"]:
            exr_dir = (
                base
                / "mm-default"
                / "scene"
                / "FG01"
                / "camera"
                / "beauty"
                / version
                / "1920x1080"
                / "exr"
            )
            exr_dir.mkdir(parents=True)
            for frame in range(1001, 1003):
                (exr_dir / f"render.{frame}.exr").touch()

        result = UserSequenceFinder.find_nuke_renders(str(workspace), username="alice")

        assert len(result) == 1
        assert result[0].version == 3  # Latest version

    def test_returns_empty_when_path_not_exists(self, tmp_path: Path) -> None:
        """Test returns empty list when nuke outputs path doesn't exist."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = UserSequenceFinder.find_nuke_renders(
            str(workspace), username="nonexistent"
        )

        assert result == []

    def test_ignores_empty_exr_directories(self, tmp_path: Path) -> None:
        """Test that empty exr directories are ignored."""
        workspace = tmp_path / "workspace"
        exr_dir = (
            workspace
            / "user"
            / "john"
            / "mm"
            / "nuke"
            / "outputs"
            / "empty"
            / "exr"
        )
        exr_dir.mkdir(parents=True)
        # Don't create any EXR files

        result = UserSequenceFinder.find_nuke_renders(str(workspace), username="john")

        assert result == []


class TestExtractRenderTypeFromPath:
    """Test _extract_render_type_from_path static method."""

    def test_extracts_render_type_from_standard_path(self, tmp_path: Path) -> None:
        """Test extraction from standard Nuke output path."""
        # Path: .../camera/{type}/v###/{resolution}/exr/
        exr_dir = tmp_path / "camera" / "lineupGeo" / "v001" / "1920x1080" / "exr"
        exr_dir.mkdir(parents=True)

        render_type = UserSequenceFinder._extract_render_type_from_path(exr_dir)

        assert render_type == "lineupGeo"

    def test_extracts_from_path_with_beauty_type(self, tmp_path: Path) -> None:
        """Test extraction with 'beauty' render type."""
        exr_dir = tmp_path / "camera" / "beauty" / "v005" / "2048x1152" / "exr"
        exr_dir.mkdir(parents=True)

        render_type = UserSequenceFinder._extract_render_type_from_path(exr_dir)

        assert render_type == "beauty"

    def test_fallback_when_path_too_short(self, tmp_path: Path) -> None:
        """Test fallback when path structure is unexpected."""
        exr_dir = tmp_path / "short" / "exr"
        exr_dir.mkdir(parents=True)

        render_type = UserSequenceFinder._extract_render_type_from_path(exr_dir)

        # Should fall back to parent directory name
        assert render_type == "short"


class TestDetectFrameRange:
    """Test _detect_frame_range static method."""

    def test_detects_frame_range_from_files(self, tmp_path: Path) -> None:
        """Test frame range detection from existing files."""
        for frame in [1001, 1050, 1100]:
            (tmp_path / f"file.{frame}.png").touch()

        first, last = UserSequenceFinder._detect_frame_range(tmp_path, "png")

        assert first == 1001
        assert last == 1100

    def test_handles_5_digit_frame_numbers(self, tmp_path: Path) -> None:
        """Test handling of 5-digit frame numbers."""
        for frame in [10001, 10050, 10100]:
            (tmp_path / f"file.{frame}.exr").touch()

        first, last = UserSequenceFinder._detect_frame_range(tmp_path, "exr")

        assert first == 10001
        assert last == 10100

    def test_returns_default_when_no_files(self, tmp_path: Path) -> None:
        """Test default frame range when no matching files."""
        first, last = UserSequenceFinder._detect_frame_range(tmp_path, "png")

        assert first == 1001
        assert last == 1100

    def test_ignores_non_sequence_files(self, tmp_path: Path) -> None:
        """Test that non-sequence files are ignored."""
        # Create sequence files
        for frame in [1001, 1010]:
            (tmp_path / f"render.{frame}.exr").touch()

        # Create non-sequence files
        (tmp_path / "thumbnail.exr").touch()
        (tmp_path / "render.1.exr").touch()  # Only 1 digit, ignored

        first, last = UserSequenceFinder._detect_frame_range(tmp_path, "exr")

        assert first == 1001
        assert last == 1010


class TestFindLatestVersionSequence:
    """Test _find_latest_version_sequence method."""

    def test_finds_latest_from_multiple_versions(self, tmp_path: Path) -> None:
        """Test finding latest version directory."""
        type_dir = tmp_path / "Wireframe"

        # Create multiple versions
        for v in [1, 2, 5, 3]:
            version_dir = type_dir / f"v{v:03d}"
            version_dir.mkdir(parents=True)
            (version_dir / "Wireframe.1001.png").touch()

        result = UserSequenceFinder._find_latest_version_sequence(
            type_dir=type_dir,
            render_type="Wireframe",
            sequence_type="maya_playblast",
            username="testuser",
            extension="png",
        )

        assert result is not None
        assert result.version == 5
        assert result.render_type == "Wireframe"

    def test_returns_none_when_no_version_dirs(self, tmp_path: Path) -> None:
        """Test returns None when no version directories exist."""
        type_dir = tmp_path / "Empty"
        type_dir.mkdir()

        result = UserSequenceFinder._find_latest_version_sequence(
            type_dir=type_dir,
            render_type="Empty",
            sequence_type="maya_playblast",
            username="testuser",
            extension="png",
        )

        assert result is None

    def test_returns_none_when_version_dir_empty(self, tmp_path: Path) -> None:
        """Test returns None when version directory has no sequence files."""
        type_dir = tmp_path / "NoFiles"
        version_dir = type_dir / "v001"
        version_dir.mkdir(parents=True)
        # No files created

        result = UserSequenceFinder._find_latest_version_sequence(
            type_dir=type_dir,
            render_type="NoFiles",
            sequence_type="maya_playblast",
            username="testuser",
            extension="png",
        )

        assert result is None


class TestImageSequenceCreation:
    """Test that created ImageSequence objects have correct attributes."""

    def test_maya_playblast_sequence_attributes(self, tmp_path: Path) -> None:
        """Test ImageSequence attributes for Maya playblast."""
        workspace = tmp_path / "workspace"
        version_dir = (
            workspace / "user" / "artist" / "mm" / "maya" / "playblast" / "Cones" / "v002"
        )
        version_dir.mkdir(parents=True)

        # Create sequence with specific frame range
        for frame in [1020, 1021, 1022, 1023, 1024]:
            (version_dir / f"Cones.{frame}.png").touch()

        result = UserSequenceFinder.find_maya_playblasts(
            str(workspace), username="artist"
        )

        assert len(result) == 1
        seq = result[0]

        # Verify all attributes
        assert seq.sequence_type == "maya_playblast"
        assert seq.render_type == "Cones"
        assert seq.version == 2
        assert seq.user == "artist"
        assert seq.first_frame == 1020
        assert seq.last_frame == 1024
        assert "####" in seq.path.name  # Pattern path
        assert isinstance(seq.modified_time, datetime)

    def test_nuke_render_sequence_attributes(self, tmp_path: Path) -> None:
        """Test ImageSequence attributes for Nuke render."""
        workspace = tmp_path / "workspace"
        exr_dir = (
            workspace
            / "user"
            / "compositor"
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / "scene"
            / "BG01"
            / "camera"
            / "beauty"
            / "v003"
            / "4096x2160"
            / "exr"
        )
        exr_dir.mkdir(parents=True)

        for frame in [1001, 1002, 1003]:
            (exr_dir / f"output.{frame}.exr").touch()

        result = UserSequenceFinder.find_nuke_renders(
            str(workspace), username="compositor"
        )

        assert len(result) == 1
        seq = result[0]

        assert seq.sequence_type == "nuke_render"
        assert seq.render_type == "beauty"
        assert seq.version == 3
        assert seq.user == "compositor"
        assert seq.first_frame == 1001
        assert seq.last_frame == 1003
