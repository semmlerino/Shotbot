"""Tests for PathBuilders VFX path construction utilities.

Tests cover:
- build_path(): Basic path construction with segments
- build_thumbnail_path(): VFX thumbnail directory paths
- build_raw_plate_path(): Raw plate directory paths
- build_threede_scene_path(): 3DE scene paths with username
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import Config
from path_builders import PathBuilders


class TestBuildPath:
    """Tests for PathBuilders.build_path()."""

    def test_concatenates_segments(self) -> None:
        """Segments are appended to base path."""
        result = PathBuilders.build_path("/base", "dir1", "dir2", "file.txt")

        assert result == Path("/base/dir1/dir2/file.txt")

    def test_returns_path_object(self) -> None:
        """Result is a Path object."""
        result = PathBuilders.build_path("/base", "segment")

        assert isinstance(result, Path)

    def test_raises_on_empty_base_path(self) -> None:
        """Empty base_path raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            PathBuilders.build_path("", "segment")

    def test_skips_empty_segments_with_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Empty segments are skipped with warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            result = PathBuilders.build_path("/base", "good", "", "also_good")

        assert result == Path("/base/good/also_good")
        assert "Empty segment" in caplog.text

    def test_accepts_path_object_as_base(self) -> None:
        """Path object can be used as base_path."""
        result = PathBuilders.build_path(Path("/base"), "segment")

        assert result == Path("/base/segment")

    def test_no_segments_returns_base(self) -> None:
        """No segments returns just the base path."""
        result = PathBuilders.build_path("/base")

        assert result == Path("/base")


class TestBuildThumbnailPath:
    """Tests for PathBuilders.build_thumbnail_path()."""

    def test_builds_correct_thumbnail_path(self) -> None:
        """Thumbnail path follows VFX convention."""
        result = PathBuilders.build_thumbnail_path(
            shows_root="/shows",
            show="testshow",
            sequence="seq01",
            shot="0010",
        )

        # Expected: /shows/testshow/shots/seq01/seq01_0010/{THUMBNAIL_SEGMENTS}
        expected_base = Path("/shows/testshow/shots/seq01/seq01_0010")
        for segment in Config.THUMBNAIL_SEGMENTS:
            expected_base = expected_base / segment

        assert result == expected_base

    def test_shot_dir_uses_sequence_underscore_shot(self) -> None:
        """Shot directory is named {sequence}_{shot}."""
        result = PathBuilders.build_thumbnail_path(
            shows_root="/shows",
            show="testshow",
            sequence="ABC",
            shot="123",
        )

        # Check that path contains ABC_123
        assert "ABC_123" in str(result)

    def test_uses_config_thumbnail_segments(self) -> None:
        """Path includes Config.THUMBNAIL_SEGMENTS."""
        result = PathBuilders.build_thumbnail_path(
            shows_root="/shows",
            show="show",
            sequence="seq",
            shot="shot",
        )

        # All thumbnail segments should be in the path
        path_str = str(result)
        for segment in Config.THUMBNAIL_SEGMENTS:
            assert segment in path_str


class TestBuildRawPlatePath:
    """Tests for PathBuilders.build_raw_plate_path()."""

    def test_builds_raw_plate_path(self) -> None:
        """Raw plate path uses Config.RAW_PLATE_SEGMENTS."""
        result = PathBuilders.build_raw_plate_path("/shows/demo/shots/seq01/seq01_0010")

        expected = Path("/shows/demo/shots/seq01/seq01_0010")
        for segment in Config.RAW_PLATE_SEGMENTS:
            expected = expected / segment

        assert result == expected

    def test_uses_config_raw_plate_segments(self) -> None:
        """Path includes Config.RAW_PLATE_SEGMENTS."""
        result = PathBuilders.build_raw_plate_path("/workspace")

        path_str = str(result)
        for segment in Config.RAW_PLATE_SEGMENTS:
            assert segment in path_str


class TestBuildThreeDeScenePath:
    """Tests for PathBuilders.build_threede_scene_path()."""

    def test_builds_threede_scene_path(self) -> None:
        """3DE scene path includes user directory."""
        result = PathBuilders.build_threede_scene_path(
            workspace_path="/shows/demo/shots/seq01/seq01_0010",
            username="artist1",
        )

        # Should contain user/artist1
        assert "user" in str(result)
        assert "artist1" in str(result)

    def test_includes_user_segment(self) -> None:
        """Path includes 'user/{username}' segment."""
        result = PathBuilders.build_threede_scene_path("/workspace", "testuser")

        path_parts = result.parts
        user_idx = path_parts.index("user")
        assert path_parts[user_idx + 1] == "testuser"

    def test_uses_config_threede_segments(self) -> None:
        """Path includes Config.THREEDE_SCENE_SEGMENTS."""
        result = PathBuilders.build_threede_scene_path("/workspace", "user")

        path_str = str(result)
        for segment in Config.THREEDE_SCENE_SEGMENTS:
            assert segment in path_str

    def test_correct_segment_order(self) -> None:
        """Segments are in correct order: user/{username}/{THREEDE_SEGMENTS}."""
        result = PathBuilders.build_threede_scene_path("/workspace", "artist")

        expected = Path("/workspace/user/artist")
        for segment in Config.THREEDE_SCENE_SEGMENTS:
            expected = expected / segment

        assert result == expected
