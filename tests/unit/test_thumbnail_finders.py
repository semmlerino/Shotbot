"""Unit tests for thumbnail_finders module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from thumbnail_finders import (
    ThumbnailFinders,
    _extract_frame_number,
    _find_first_jpeg_in_version_tree,
)


pytestmark = pytest.mark.unit


# ==============================================================================
# _extract_frame_number
# ==============================================================================


class TestExtractFrameNumber:
    """Tests for the _extract_frame_number helper."""

    def test_standard_frame_1001(self) -> None:
        """Extracts 1001 from a standard EXR filename."""
        assert _extract_frame_number(Path("shot.1001.exr")) == 1001

    def test_different_frame_number(self) -> None:
        """Extracts a non-1001 frame number correctly."""
        assert _extract_frame_number(Path("shot.1050.exr")) == 1050

    def test_no_frame_number_returns_sentinel(self) -> None:
        """Returns 99999 when filename has no matching frame pattern."""
        assert _extract_frame_number(Path("shot.jpg")) == 99999

    def test_case_insensitive_extension(self) -> None:
        """Matches .EXR (uppercase) the same as .exr."""
        assert _extract_frame_number(Path("shot.1001.EXR")) == 1001

    def test_mixed_case_extension(self) -> None:
        """Matches .Exr (mixed case)."""
        assert _extract_frame_number(Path("shot.1001.Exr")) == 1001

    def test_frame_0001(self) -> None:
        """Extracts early frame numbers like 0001."""
        assert _extract_frame_number(Path("shot.0001.exr")) == 1

    def test_long_filename_with_frame(self) -> None:
        """Works with a realistic VFX filename."""
        assert _extract_frame_number(
            Path("GG_000_0050_turnover-plate_EL01_lin_sgamut3cine_v001.1001.exr")
        ) == 1001

    def test_no_extension_returns_sentinel(self) -> None:
        """Returns 99999 for a path with no extension."""
        assert _extract_frame_number(Path("shot_without_extension")) == 99999

    def test_three_digit_number_not_matched(self) -> None:
        """A three-digit number does not match (requires exactly four digits)."""
        assert _extract_frame_number(Path("shot.100.exr")) == 99999

    def test_five_digit_number_not_matched(self) -> None:
        """A five-digit frame number does not match the four-digit pattern."""
        assert _extract_frame_number(Path("shot.10010.exr")) == 99999


# ==============================================================================
# _find_first_jpeg_in_version_tree
# ==============================================================================


class TestFindFirstJpegInVersionTree:
    """Tests for _find_first_jpeg_in_version_tree helper."""

    def test_finds_jpeg_in_version_tree(self, tmp_path: Path) -> None:
        """Returns first JPEG under base_path/version/jpeg/resolution/."""
        base_path = tmp_path / "undistorted_plate"
        jpeg_dir = base_path / "v001" / "jpeg" / "4312x2304"
        jpeg_dir.mkdir(parents=True)
        jpeg_file = jpeg_dir / "frame.0001.jpeg"
        jpeg_file.write_bytes(b"JPEG_DATA")

        with patch("thumbnail_finders.VersionUtils.get_latest_version", return_value="v001"):
            result = _find_first_jpeg_in_version_tree(base_path)

        assert result == jpeg_file

    def test_returns_none_when_no_version_found(self, tmp_path: Path) -> None:
        """Returns None when VersionUtils finds no version directories."""
        base_path = tmp_path / "undistorted_plate"
        base_path.mkdir()

        with patch("thumbnail_finders.VersionUtils.get_latest_version", return_value=None):
            result = _find_first_jpeg_in_version_tree(base_path)

        assert result is None

    def test_returns_none_when_jpeg_base_path_missing(self, tmp_path: Path) -> None:
        """Returns None when the version/jpeg directory doesn't exist."""
        base_path = tmp_path / "undistorted_plate"
        # Create version dir but not the jpeg subdir
        (base_path / "v001").mkdir(parents=True)

        with patch("thumbnail_finders.VersionUtils.get_latest_version", return_value="v001"):
            result = _find_first_jpeg_in_version_tree(base_path)

        assert result is None

    def test_uses_custom_image_subdir(self, tmp_path: Path) -> None:
        """Respects the image_subdir parameter (e.g., 'jpg' for editorial)."""
        base_path = tmp_path / "editorial"
        jpg_dir = base_path / "v002" / "jpg" / "1920x1080"
        jpg_dir.mkdir(parents=True)
        jpg_file = jpg_dir / "cutref.0001.jpg"
        jpg_file.write_bytes(b"JPG_DATA")

        with patch("thumbnail_finders.VersionUtils.get_latest_version", return_value="v002"):
            result = _find_first_jpeg_in_version_tree(base_path, image_subdir="jpg")

        assert result == jpg_file

    def test_skips_non_jpeg_files(self, tmp_path: Path) -> None:
        """Returns None when the resolution dir contains only non-JPEG files."""
        base_path = tmp_path / "undistorted_plate"
        jpeg_dir = base_path / "v001" / "jpeg" / "1920x1080"
        jpeg_dir.mkdir(parents=True)
        (jpeg_dir / "frame.0001.exr").write_bytes(b"EXR_DATA")

        with (
            patch("thumbnail_finders.VersionUtils.get_latest_version", return_value="v001"),
            # get_first_image_file needs to return a non-jpeg
            patch(
                "thumbnail_finders.FileUtils.get_first_image_file",
                return_value=jpeg_dir / "frame.0001.exr",
            ),
        ):
            result = _find_first_jpeg_in_version_tree(base_path)

        assert result is None

    def test_handles_oserror_gracefully(self, tmp_path: Path) -> None:
        """Returns None when iterdir raises OSError."""
        base_path = tmp_path / "undistorted_plate"
        jpeg_base = base_path / "v001" / "jpeg"
        jpeg_base.mkdir(parents=True)

        with (
            patch("thumbnail_finders.VersionUtils.get_latest_version", return_value="v001"),
            patch.object(Path, "iterdir", side_effect=OSError("permission denied")),
        ):
            result = _find_first_jpeg_in_version_tree(base_path)

        assert result is None


# ==============================================================================
# ThumbnailFinders._shot_path
# ==============================================================================


class TestShotPath:
    """Tests for ThumbnailFinders._shot_path."""

    def test_builds_correct_path(self) -> None:
        """Constructs the standard VFX shot directory path."""
        result = ThumbnailFinders._shot_path("/shows", "demo", "seq01", "0010")
        assert result == Path("/shows/demo/shots/seq01/seq01_0010")

    def test_builds_path_with_suffix(self) -> None:
        """Appends optional suffix segments correctly."""
        result = ThumbnailFinders._shot_path(
            "/shows", "demo", "seq01", "0010", "publish"
        )
        assert result == Path("/shows/demo/shots/seq01/seq01_0010/publish")

    def test_builds_path_with_multiple_suffix_parts(self) -> None:
        """Appends multiple suffix components."""
        result = ThumbnailFinders._shot_path(
            "/shows", "demo", "seq01", "0010", "publish", "editorial", "cutref"
        )
        assert result == Path(
            "/shows/demo/shots/seq01/seq01_0010/publish/editorial/cutref"
        )

    def test_shot_dir_uses_sequence_prefix(self) -> None:
        """Shot directory is named {sequence}_{shot}."""
        result = ThumbnailFinders._shot_path("/shows", "myshow", "ABC", "1234")
        assert result.name == "ABC_1234"

    def test_sequence_appears_in_path(self) -> None:
        """Sequence name appears as a path component."""
        result = ThumbnailFinders._shot_path("/shows", "myshow", "ABC", "1234")
        assert "ABC" in result.parts


# ==============================================================================
# ThumbnailFinders.find_turnover_plate_thumbnail
# ==============================================================================


class TestFindTurnoverPlateThumbnail:
    """Tests for ThumbnailFinders.find_turnover_plate_thumbnail."""

    def _make_plate(
        self,
        base: Path,
        plate_name: str,
        filename: str = "shot.1001.exr",
    ) -> Path:
        """Create a minimal plate directory structure and return the EXR file path."""
        exr_dir = base / plate_name / "v001" / "exr" / "2K"
        exr_dir.mkdir(parents=True)
        f = exr_dir / filename
        f.write_bytes(b"EXR")
        return f

    def test_returns_fg_plate_when_only_fg_exists(self, tmp_path: Path) -> None:
        """Returns the FG plate when it is the only plate present."""
        base = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01"
            / "publish" / "turnover" / "plate"
        )
        fg_file = self._make_plate(base, "FG01")

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )

        assert result == fg_file

    def test_fg_preferred_over_bg(self, tmp_path: Path) -> None:
        """FG plate is chosen over BG when both exist."""
        base = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01"
            / "publish" / "turnover" / "plate"
        )
        fg_file = self._make_plate(base, "FG01")
        self._make_plate(base, "BG01", "shot.1001.exr")

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )

        assert result == fg_file
        assert "FG01" in str(result)

    def test_bg_preferred_over_other(self, tmp_path: Path) -> None:
        """BG plate is chosen over an EL plate when no FG exists."""
        base = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01"
            / "publish" / "turnover" / "plate"
        )
        bg_file = self._make_plate(base, "BG01")
        self._make_plate(base, "EL01", "shot.1001.exr")

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )

        assert result == bg_file

    def test_returns_none_when_directory_missing(self, tmp_path: Path) -> None:
        """Returns None when the turnover plate directory doesn't exist."""
        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )
        assert result is None

    def test_returns_none_when_no_plates_in_dir(self, tmp_path: Path) -> None:
        """Returns None when the plate directory is empty."""
        base = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01"
            / "publish" / "turnover" / "plate"
        )
        base.mkdir(parents=True)

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )
        assert result is None

    def test_handles_oserror_on_iterdir(self, tmp_path: Path) -> None:
        """Returns None gracefully when iterdir raises OSError."""
        base = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01"
            / "publish" / "turnover" / "plate"
        )
        base.mkdir(parents=True)

        with patch.object(Path, "iterdir", side_effect=OSError("no access")):
            result = ThumbnailFinders.find_turnover_plate_thumbnail(
                str(tmp_path / "shows"), "show", "seq01", "shot01"
            )

        assert result is None

    def test_picks_first_frame_from_sequence(self, tmp_path: Path) -> None:
        """Returns the lowest frame number from an EXR sequence."""
        exr_dir = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01"
            / "publish" / "turnover" / "plate"
            / "FG01" / "v001" / "exr" / "2K"
        )
        exr_dir.mkdir(parents=True)
        f1001 = exr_dir / "shot.1001.exr"
        f1010 = exr_dir / "shot.1010.exr"
        f1001.write_bytes(b"FRAME1001")
        f1010.write_bytes(b"FRAME1010")

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )

        assert result == f1001

    def test_with_input_plate_subdirectory(self, tmp_path: Path) -> None:
        """Finds plates inside optional input_plate subdirectory."""
        base = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01"
            / "publish" / "turnover" / "plate" / "input_plate"
        )
        fg_file = self._make_plate(base, "FG01")

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )

        assert result == fg_file


# ==============================================================================
# ThumbnailFinders.find_any_publish_thumbnail
# ==============================================================================


class TestFindAnyPublishThumbnail:
    """Tests for ThumbnailFinders.find_any_publish_thumbnail."""

    def _make_publish_dir(self, tmp_path: Path) -> Path:
        """Return the publish directory Path after creating it."""
        publish = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01" / "publish"
        )
        publish.mkdir(parents=True)
        return publish

    def test_finds_exr_with_1001_in_name(self, tmp_path: Path) -> None:
        """Returns an EXR file that has '1001' in its filename."""
        publish = self._make_publish_dir(tmp_path)
        exr = publish / "comp.1001.exr"
        exr.write_bytes(b"EXR")

        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )

        assert result == exr

    def test_ignores_exr_without_1001(self, tmp_path: Path) -> None:
        """Skips EXR files whose names don't contain '1001'."""
        publish = self._make_publish_dir(tmp_path)
        (publish / "comp.1002.exr").write_bytes(b"EXR")

        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )

        assert result is None

    def test_ignores_non_exr_with_1001(self, tmp_path: Path) -> None:
        """Skips files with '1001' but a non-EXR extension."""
        publish = self._make_publish_dir(tmp_path)
        (publish / "thumb.1001.jpg").write_bytes(b"JPG")

        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )

        assert result is None

    def test_returns_none_when_publish_dir_missing(self, tmp_path: Path) -> None:
        """Returns None when the publish directory doesn't exist."""
        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )

        assert result is None

    def test_respects_max_depth(self, tmp_path: Path) -> None:
        """Does not descend beyond max_depth levels.

        The file is at 4 levels inside publish (publish/a/b/c/d/file).
        os.walk yields root=publish/a/b/c/d → rel_path parts = ('a','b','c','d') → depth=4.
        The guard is ``if depth >= max_depth: dirs.clear(); continue``, so:
          - max_depth=4 → depth(4) >= 4 → skip → file not found
          - max_depth=5 → depth(4) < 5  → check files → file found
        """
        publish = self._make_publish_dir(tmp_path)
        # Place file at depth 4 (publish/a/b/c/d/)
        deep = publish / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "shot.1001.exr").write_bytes(b"EXR")

        # max_depth=4 should NOT reach depth-4 files (depth >= max_depth is skipped)
        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01", max_depth=4
        )
        assert result is None

        # max_depth=5 should reach the depth-4 file
        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01", max_depth=5
        )
        assert result is not None

    def test_finds_exr_in_subdirectory(self, tmp_path: Path) -> None:
        """Finds EXR nested one level inside publish."""
        publish = self._make_publish_dir(tmp_path)
        sub = publish / "mm" / "renders"
        sub.mkdir(parents=True)
        exr = sub / "beauty.1001.exr"
        exr.write_bytes(b"EXR")

        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )

        assert result == exr

    def test_handles_oserror_gracefully(self, tmp_path: Path) -> None:
        """Returns None when os.walk raises OSError."""
        publish = self._make_publish_dir(tmp_path)
        (publish / "shot.1001.exr").write_bytes(b"EXR")

        with patch("thumbnail_finders.os.walk", side_effect=OSError("permission denied")):
            result = ThumbnailFinders.find_any_publish_thumbnail(
                str(tmp_path / "shows"), "show", "seq01", "shot01"
            )

        assert result is None


# ==============================================================================
# ThumbnailFinders.find_shot_thumbnail (orchestrator)
# ==============================================================================


class TestFindShotThumbnail:
    """Tests for ThumbnailFinders.find_shot_thumbnail (main entry point)."""

    def _args(self) -> tuple[str, str, str, str]:
        return "/shows", "show", "seq01", "shot01"

    def test_returns_editorial_thumbnail_when_found(self) -> None:
        """Returns editorial result when _find_editorial_cutref_thumbnail succeeds."""
        editorial_jpeg = Path("/fake/editorial.jpg")

        with (
            patch(
                "thumbnail_finders.PathValidators.validate_path_exists",
                return_value=True,
            ),
            patch.object(
                ThumbnailFinders,
                "_find_editorial_cutref_thumbnail",
                return_value=editorial_jpeg,
            ),
        ):
            result = ThumbnailFinders.find_shot_thumbnail(*self._args())

        assert result == editorial_jpeg

    def test_falls_through_to_turnover_when_editorial_missing(self) -> None:
        """Falls through to turnover plate when editorial cutref doesn't exist."""
        turnover_exr = Path("/fake/turnover.exr")

        with (
            patch(
                "thumbnail_finders.PathValidators.validate_path_exists",
                return_value=False,
            ),
            patch.object(
                ThumbnailFinders,
                "find_turnover_plate_thumbnail",
                return_value=turnover_exr,
            ),
            patch.object(
                ThumbnailFinders,
                "find_any_publish_thumbnail",
                return_value=None,
            ),
        ):
            result = ThumbnailFinders.find_shot_thumbnail(*self._args())

        assert result == turnover_exr

    def test_falls_through_to_publish_when_turnover_missing(self) -> None:
        """Falls through to any publish EXR when neither editorial nor turnover found."""
        publish_exr = Path("/fake/publish.1001.exr")

        with (
            patch(
                "thumbnail_finders.PathValidators.validate_path_exists",
                return_value=False,
            ),
            patch.object(
                ThumbnailFinders,
                "find_turnover_plate_thumbnail",
                return_value=None,
            ),
            patch.object(
                ThumbnailFinders,
                "find_any_publish_thumbnail",
                return_value=publish_exr,
            ),
        ):
            result = ThumbnailFinders.find_shot_thumbnail(*self._args())

        assert result == publish_exr

    def test_returns_none_when_nothing_found(self) -> None:
        """Returns None when all three finders fail."""
        with (
            patch(
                "thumbnail_finders.PathValidators.validate_path_exists",
                return_value=False,
            ),
            patch.object(
                ThumbnailFinders,
                "find_turnover_plate_thumbnail",
                return_value=None,
            ),
            patch.object(
                ThumbnailFinders,
                "find_any_publish_thumbnail",
                return_value=None,
            ),
        ):
            result = ThumbnailFinders.find_shot_thumbnail(*self._args())

        assert result is None

    def test_editorial_result_takes_priority_over_turnover(self) -> None:
        """Editorial JPEG is returned even when turnover plate also exists."""
        editorial_jpeg = Path("/fake/editorial.jpg")
        turnover_exr = Path("/fake/turnover.exr")

        with (
            patch(
                "thumbnail_finders.PathValidators.validate_path_exists",
                return_value=True,
            ),
            patch.object(
                ThumbnailFinders,
                "_find_editorial_cutref_thumbnail",
                return_value=editorial_jpeg,
            ),
            patch.object(
                ThumbnailFinders,
                "find_turnover_plate_thumbnail",
                return_value=turnover_exr,
            ) as mock_turnover,
        ):
            result = ThumbnailFinders.find_shot_thumbnail(*self._args())

        assert result == editorial_jpeg
        mock_turnover.assert_not_called()


# ==============================================================================
# ThumbnailFinders._find_editorial_cutref_thumbnail
# ==============================================================================


class TestFindEditorialCutrefThumbnail:
    """Tests for ThumbnailFinders._find_editorial_cutref_thumbnail."""

    def test_returns_jpeg_from_version_tree(self, tmp_path: Path) -> None:
        """Returns JPEG found in editorial/version/jpg/resolution structure."""
        editorial_base = tmp_path / "cutref"
        jpg_dir = editorial_base / "v003" / "jpg" / "1920x1080"
        jpg_dir.mkdir(parents=True)
        jpg_file = jpg_dir / "cutref.0001.jpg"
        jpg_file.write_bytes(b"JPG_DATA")

        with patch("thumbnail_finders.VersionUtils.get_latest_version", return_value="v003"):
            result = ThumbnailFinders._find_editorial_cutref_thumbnail(editorial_base)

        assert result == jpg_file

    def test_returns_none_when_no_version_dirs(self, tmp_path: Path) -> None:
        """Returns None when no version directories exist."""
        editorial_base = tmp_path / "cutref"
        editorial_base.mkdir()

        with patch("thumbnail_finders.VersionUtils.get_latest_version", return_value=None):
            result = ThumbnailFinders._find_editorial_cutref_thumbnail(editorial_base)

        assert result is None


# ==============================================================================
# ThumbnailFinders.find_undistorted_jpeg_thumbnail
# ==============================================================================


class TestFindUndistortedJpegThumbnail:
    """Tests for ThumbnailFinders.find_undistorted_jpeg_thumbnail."""

    def test_returns_none_when_mm_default_missing(self, tmp_path: Path) -> None:
        """Returns None when publish/mm/default directory doesn't exist."""
        result = ThumbnailFinders.find_undistorted_jpeg_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )
        assert result is None

    def test_finds_jpeg_for_known_plate(self, tmp_path: Path) -> None:
        """Returns JPEG found for a plate discovered by FileDiscovery."""
        mm_default = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01"
            / "publish" / "mm" / "default"
        )
        plate_path = mm_default / "FG01" / "undistorted_plate"
        jpeg_dir = plate_path / "v001" / "jpeg" / "2K"
        jpeg_dir.mkdir(parents=True)
        jpeg_file = jpeg_dir / "shot.0001.jpeg"
        jpeg_file.write_bytes(b"JPEG")

        with (
            patch(
                "thumbnail_finders.FileDiscovery.discover_plate_directories",
                return_value=[("FG01", 0)],
            ),
            patch(
                "thumbnail_finders.find_path_case_insensitive",
                side_effect=lambda base, name: base / name,
            ),
            patch(
                "thumbnail_finders.VersionUtils.get_latest_version",
                return_value="v001",
            ),
        ):
            result = ThumbnailFinders.find_undistorted_jpeg_thumbnail(
                str(tmp_path / "shows"), "show", "seq01", "shot01"
            )

        assert result == jpeg_file

    def test_returns_none_when_no_plates_discovered(self, tmp_path: Path) -> None:
        """Returns None when FileDiscovery finds no plate directories."""
        mm_default = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01"
            / "publish" / "mm" / "default"
        )
        mm_default.mkdir(parents=True)

        with patch(
            "thumbnail_finders.FileDiscovery.discover_plate_directories",
            return_value=[],
        ):
            result = ThumbnailFinders.find_undistorted_jpeg_thumbnail(
                str(tmp_path / "shows"), "show", "seq01", "shot01"
            )

        assert result is None


# ==============================================================================
# ThumbnailFinders.find_user_workspace_jpeg_thumbnail
# ==============================================================================


class TestFindUserWorkspaceJpegThumbnail:
    """Tests for ThumbnailFinders.find_user_workspace_jpeg_thumbnail."""

    def test_returns_none_when_user_dir_missing(self, tmp_path: Path) -> None:
        """Returns None when the user directory doesn't exist."""
        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )
        assert result is None

    def test_finds_jpeg_in_undistort_output(self, tmp_path: Path) -> None:
        """Returns JPEG from user/username/mm/nuke/outputs/mm-default/undistort structure."""
        user_dir = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01" / "user"
        )
        user_path = user_dir / "artistname"
        mm_default_base = user_path / "mm" / "nuke" / "outputs" / "mm-default"
        plate_undistorted = mm_default_base / "undistort" / "FG01" / "undistorted_plate"
        jpeg_dir = plate_undistorted / "v001" / "2K" / "jpeg"
        jpeg_dir.mkdir(parents=True)
        jpeg_file = jpeg_dir / "frame.0001.jpg"
        jpeg_file.write_bytes(b"JPG")

        with (
            patch(
                "thumbnail_finders.FileDiscovery.discover_plate_directories",
                return_value=[("FG01", 0)],
            ),
            patch(
                "thumbnail_finders.find_path_case_insensitive",
                side_effect=lambda base, name: base / name,
            ),
            patch(
                "thumbnail_finders.VersionUtils.get_latest_version",
                return_value="v001",
            ),
            patch(
                "thumbnail_finders.FileUtils.get_first_image_file",
                return_value=jpeg_file,
            ),
        ):
            result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
                str(tmp_path / "shows"), "show", "seq01", "shot01"
            )

        assert result == jpeg_file

    def test_returns_none_when_no_mm_default_for_any_user(self, tmp_path: Path) -> None:
        """Returns None when no user has an mm-default Nuke output directory."""
        user_dir = (
            tmp_path
            / "shows" / "show" / "shots" / "seq01" / "seq01_shot01" / "user"
        )
        # Create user directory but without the expected mm/nuke/outputs structure
        (user_dir / "someuser").mkdir(parents=True)

        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(tmp_path / "shows"), "show", "seq01", "shot01"
        )

        assert result is None
