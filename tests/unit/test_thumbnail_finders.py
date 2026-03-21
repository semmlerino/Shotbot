"""Unit tests for thumbnail_finders module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from discovery.thumbnail_finders import (
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

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            pytest.param("shot.jpg", 99999, id="no_frame_number_returns_sentinel"),
            pytest.param("shot_without_extension", 99999, id="no_extension_returns_sentinel"),
        ],
    )
    def test_missing_frame_pattern_returns_sentinel(self, filename: str, expected: int) -> None:
        """Returns 99999 when filename has no matching frame pattern."""
        assert _extract_frame_number(Path(filename)) == expected

    @pytest.mark.parametrize(
        "filename",
        [
            pytest.param("shot.1001.EXR", id="uppercase_extension"),
            pytest.param("shot.1001.Exr", id="mixed_case_extension"),
        ],
    )
    def test_case_insensitive_extension(self, filename: str) -> None:
        """Matches EXR extension regardless of case."""
        assert _extract_frame_number(Path(filename)) == 1001

    def test_frame_0001(self) -> None:
        """Extracts early frame numbers like 0001."""
        assert _extract_frame_number(Path("shot.0001.exr")) == 1

    def test_long_filename_with_frame(self) -> None:
        """Works with a realistic VFX filename."""
        assert _extract_frame_number(
            Path("GG_000_0050_turnover-plate_EL01_lin_sgamut3cine_v001.1001.exr")
        ) == 1001

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

        with patch("discovery.thumbnail_finders.VersionUtils.get_latest_version", return_value="v001"):
            result = _find_first_jpeg_in_version_tree(base_path)

        assert result == jpeg_file

    def test_returns_none_when_no_version_found(self, tmp_path: Path) -> None:
        """Returns None when VersionUtils finds no version directories."""
        base_path = tmp_path / "undistorted_plate"
        base_path.mkdir()

        with patch("discovery.thumbnail_finders.VersionUtils.get_latest_version", return_value=None):
            result = _find_first_jpeg_in_version_tree(base_path)

        assert result is None

    def test_returns_none_when_jpeg_base_path_missing(self, tmp_path: Path) -> None:
        """Returns None when the version/jpeg directory doesn't exist."""
        base_path = tmp_path / "undistorted_plate"
        # Create version dir but not the jpeg subdir
        (base_path / "v001").mkdir(parents=True)

        with patch("discovery.thumbnail_finders.VersionUtils.get_latest_version", return_value="v001"):
            result = _find_first_jpeg_in_version_tree(base_path)

        assert result is None

    def test_uses_custom_image_subdir(self, tmp_path: Path) -> None:
        """Respects the image_subdir parameter (e.g., 'jpg' for editorial)."""
        base_path = tmp_path / "editorial"
        jpg_dir = base_path / "v002" / "jpg" / "1920x1080"
        jpg_dir.mkdir(parents=True)
        jpg_file = jpg_dir / "cutref.0001.jpg"
        jpg_file.write_bytes(b"JPG_DATA")

        with patch("discovery.thumbnail_finders.VersionUtils.get_latest_version", return_value="v002"):
            result = _find_first_jpeg_in_version_tree(base_path, image_subdir="jpg")

        assert result == jpg_file

    def test_skips_non_jpeg_files(self, tmp_path: Path) -> None:
        """Returns None when the resolution dir contains only non-JPEG files."""
        base_path = tmp_path / "undistorted_plate"
        jpeg_dir = base_path / "v001" / "jpeg" / "1920x1080"
        jpeg_dir.mkdir(parents=True)
        (jpeg_dir / "frame.0001.exr").write_bytes(b"EXR_DATA")

        with (
            patch("discovery.thumbnail_finders.VersionUtils.get_latest_version", return_value="v001"),
            # get_first_image_file needs to return a non-jpeg
            patch(
                "discovery.thumbnail_finders.FileUtils.get_first_image_file",
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
            patch("discovery.thumbnail_finders.VersionUtils.get_latest_version", return_value="v001"),
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
        """Constructs the standard VFX shot directory path with correct structure."""
        result = ThumbnailFinders._shot_path("/shows", "myshow", "ABC", "1234")
        assert result == Path("/shows/myshow/shots/ABC/ABC_1234")
        assert result.name == "ABC_1234"
        assert "ABC" in result.parts

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

        with patch("discovery.thumbnail_finders.os.walk", side_effect=OSError("permission denied")):
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

    def test_falls_through_to_turnover_when_editorial_missing(self) -> None:
        """Falls through to turnover plate when editorial cutref doesn't exist."""
        turnover_exr = Path("/fake/turnover.exr")

        with (
            patch(
                "discovery.thumbnail_finders.PathValidators.validate_path_exists",
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
                "discovery.thumbnail_finders.PathValidators.validate_path_exists",
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
                "discovery.thumbnail_finders.PathValidators.validate_path_exists",
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
                "discovery.thumbnail_finders.PathValidators.validate_path_exists",
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

        with patch("discovery.thumbnail_finders.VersionUtils.get_latest_version", return_value="v003"):
            result = ThumbnailFinders._find_editorial_cutref_thumbnail(editorial_base)

        assert result == jpg_file

    def test_returns_none_when_no_version_dirs(self, tmp_path: Path) -> None:
        """Returns None when no version directories exist."""
        editorial_base = tmp_path / "cutref"
        editorial_base.mkdir()

        with patch("discovery.thumbnail_finders.VersionUtils.get_latest_version", return_value=None):
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
                "discovery.thumbnail_finders.FileDiscovery.discover_plate_directories",
                return_value=[("FG01", 0)],
            ),
            patch(
                "discovery.thumbnail_finders.find_path_case_insensitive",
                side_effect=lambda base, name: base / name,
            ),
            patch(
                "discovery.thumbnail_finders.VersionUtils.get_latest_version",
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
            "discovery.thumbnail_finders.FileDiscovery.discover_plate_directories",
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
                "discovery.thumbnail_finders.FileDiscovery.discover_plate_directories",
                return_value=[("FG01", 0)],
            ),
            patch(
                "discovery.thumbnail_finders.find_path_case_insensitive",
                side_effect=lambda base, name: base / name,
            ),
            patch(
                "discovery.thumbnail_finders.VersionUtils.get_latest_version",
                return_value="v001",
            ),
            patch(
                "discovery.thumbnail_finders.FileUtils.get_first_image_file",
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


# ==============================================================================
# Integration-style tests moved from test_utils.py
# These exercise real filesystem structures end-to-end without mocking internals.
# ==============================================================================


class TestFindTurnoverPlateThumbnailIntegration:
    """Integration tests for the complex turnover plate thumbnail discovery logic."""

    def test_find_turnover_plate_thumbnail_success(self, tmp_path: Path) -> None:
        """Test successful turnover plate thumbnail discovery."""
        # Create directory structure:
        # /shows/myshow/shots/seq01/seq01_shot01/publish/turnover/plate/input_plate/FG01/v001/exr/1920x1080/
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"
        plate_path = (
            shot_path
            / "publish"
            / "turnover"
            / "plate"
            / "input_plate"
            / "FG01"
            / "v001"
            / "exr"
            / "1920x1080"
        )
        plate_path.mkdir(parents=True)

        # Create test EXR file
        test_frame = (
            plate_path / "GG_000_0050_turnover-plate_FG01_lin_sgamut3cine_v001.1001.exr"
        )
        test_frame.write_text("fake exr content")

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(shows_root),
            "myshow",
            "seq01",
            "shot01",
        )

        assert result is not None
        assert (
            result.name
            == "GG_000_0050_turnover-plate_FG01_lin_sgamut3cine_v001.1001.exr"
        )
        assert result.exists()

    @pytest.mark.parametrize(
        ("plates_present", "expected_prefix"),
        [
            pytest.param(["FG01", "BG01"], "FG01", id="fg_beats_bg"),
            pytest.param(["BG01", "EL01"], "BG01", id="bg_beats_el"),
            pytest.param(["FG01", "BG01", "EL01"], "FG01", id="fg_beats_bg_and_el"),
        ],
    )
    def test_find_turnover_plate_thumbnail_priority_order(
        self, tmp_path: Path, plates_present: list[str], expected_prefix: str
    ) -> None:
        """Test that FG > BG > EL priority ordering is respected."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"
        base_plate_path = shot_path / "publish" / "turnover" / "plate" / "input_plate"

        for plate in plates_present:
            plate_path = base_plate_path / plate / "v001" / "exr" / "1920x1080"
            plate_path.mkdir(parents=True)
            (plate_path / f"shot_{plate}.1001.exr").write_text(f"{plate} content")

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(shows_root),
            "myshow",
            "seq01",
            "shot01",
        )

        assert result is not None
        assert expected_prefix in str(result)

    def test_find_turnover_plate_thumbnail_frame_number_sorting(
        self, tmp_path: Path
    ) -> None:
        """Test that frame numbers are sorted correctly."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"
        plate_path = (
            shot_path
            / "publish"
            / "turnover"
            / "plate"
            / "input_plate"
            / "FG01"
            / "v001"
            / "exr"
            / "1920x1080"
        )
        plate_path.mkdir(parents=True)

        # Create frames in non-sequential order
        (plate_path / "shot.1010.exr").write_text("frame 1010")
        (plate_path / "shot.1001.exr").write_text("frame 1001")  # Should be first
        (plate_path / "shot.1005.exr").write_text("frame 1005")

        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(shows_root),
            "myshow",
            "seq01",
            "shot01",
        )

        assert result is not None
        assert "1001" in result.name  # Should get the earliest frame

    def test_find_turnover_plate_thumbnail_no_base_path(self) -> None:
        """Test turnover plate discovery when base path doesn't exist."""
        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            "/nonexistent",
            "show",
            "seq",
            "shot",
        )
        assert result is None


class TestFindAnyPublishThumbnailIntegration:
    """Integration tests for recursive publish thumbnail discovery fallback logic."""

    def test_find_any_publish_thumbnail_recursive(self, tmp_path: Path) -> None:
        """Find the first 1001 EXR recursively under publish/."""
        publish_path = (
            tmp_path
            / "shows"
            / "testshow"
            / "shots"
            / "seq01"
            / "seq01_shot01"
            / "publish"
        )
        deep_path = publish_path / "comp" / "v001" / "exr"
        deep_path.mkdir(parents=True)

        test_file = deep_path / "comp_v001.1001.exr"
        test_file.write_text("fake exr")
        (deep_path / "comp_v001.1002.exr").write_text("other frame")
        (deep_path / "comp_v001.jpg").write_text("wrong extension")

        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(tmp_path / "shows"),
            "testshow",
            "seq01",
            "shot01",
        )

        assert result is not None
        assert result.name == test_file.name

    def test_find_any_publish_thumbnail_max_depth(self, tmp_path: Path) -> None:
        """Respect max_depth and prefer shallow hits when deep hits exceed limit."""
        shows_root = tmp_path / "shows"
        publish_path = (
            shows_root / "testshow" / "shots" / "seq01" / "seq01_shot01" / "publish"
        )

        very_deep = publish_path
        for i in range(10):
            very_deep = very_deep / f"level{i}"
        very_deep.mkdir(parents=True)
        (very_deep / "too_deep.1001.exr").write_text("deep")

        shallow = publish_path / "level0" / "level1"
        shallow.mkdir(parents=True, exist_ok=True)
        shallow_file = shallow / "shallow.1001.exr"
        shallow_file.write_text("shallow")

        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(shows_root),
            "testshow",
            "seq01",
            "shot01",
            max_depth=3,
        )

        assert result is not None
        assert result.name == shallow_file.name

    def test_find_any_publish_thumbnail_no_publish_dir(self, tmp_path: Path) -> None:
        """Return None when the publish path does not exist."""
        shows_root = tmp_path / "shows"
        shows_root.mkdir()

        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(shows_root),
            "testshow",
            "seq01",
            "shot01",
        )
        assert result is None


class TestUserWorkspaceJPEGDiscovery:
    """Integration tests for user workspace JPEG discovery with undistort/ and scene/ structures."""

    @pytest.mark.parametrize(
        ("subdir", "user", "seq", "shot", "plate", "filename"),
        [
            (
                "undistort",
                "ryan-p",
                "SF_000",
                "0030",
                "pl01",
                "SF_000_0030_mm-default_PL01_undistorted_v001.1001.jpeg",
            ),
            (
                "scene",
                "sarah-b",
                "DA_000",
                "0005",
                "FG01",
                "DA_000_0005_mm-default_FG01_undistorted_v001.1001.jpeg",
            ),
        ],
        ids=["undistort_structure", "scene_structure"],
    )
    def test_find_user_workspace_jpeg_output_structure(
        self,
        tmp_path: Path,
        subdir: str,
        user: str,
        seq: str,
        shot: str,
        plate: str,
        filename: str,
    ) -> None:
        """Test finding JPEGs in undistort/ and scene/ directory structures."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "jack_ryan" / "shots" / seq / f"{seq}_{shot}"
        jpeg_dir = (
            shot_path
            / "user"
            / user
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / subdir
            / plate
            / "undistorted_plate"
            / "v001"
            / "4312x2304"
            / "jpeg"
        )
        jpeg_dir.mkdir(parents=True)

        jpeg_file = jpeg_dir / filename
        jpeg_file.write_text("fake jpeg content")

        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(shows_root), "jack_ryan", seq, shot
        )

        assert result is not None
        assert result.name == jpeg_file.name
        assert subdir in str(result)

    def test_find_user_workspace_jpeg_undistort_priority_over_scene(
        self, tmp_path: Path
    ) -> None:
        """Test that undistort/ is checked before scene/ (as per implementation)."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"

        # Create BOTH undistort and scene structures
        undistort_jpeg = (
            shot_path
            / "user"
            / "user1"
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / "undistort"
            / "fg01"
            / "undistorted_plate"
            / "v001"
            / "4096x2160"
            / "jpeg"
            / "undistort_version.jpeg"
        )
        undistort_jpeg.parent.mkdir(parents=True)
        undistort_jpeg.write_text("undistort jpeg")

        scene_jpeg = (
            shot_path
            / "user"
            / "user1"
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / "scene"
            / "fg01"
            / "undistorted_plate"
            / "v002"
            / "4096x2160"
            / "jpeg"
            / "scene_version.jpeg"
        )
        scene_jpeg.parent.mkdir(parents=True)
        scene_jpeg.write_text("scene jpeg")

        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        # Should find undistort version first (checked first in loop)
        assert result is not None
        assert result.name == "undistort_version.jpeg"

    def test_find_user_workspace_jpeg_case_insensitive_plates(
        self, tmp_path: Path
    ) -> None:
        """Test that lowercase plate names (pl01) are found with case-insensitive matching."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"

        # Create lowercase plate directory (pl01, not PL01)
        jpeg_dir = (
            shot_path
            / "user"
            / "artist"
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / "undistort"
            / "pl01"
            / "undistorted_plate"
            / "v001"
            / "4096x2160"
            / "jpeg"
        )
        jpeg_dir.mkdir(parents=True)
        jpeg_file = jpeg_dir / "lowercase_plate.jpeg"
        jpeg_file.write_text("jpeg")

        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        # Should find it via case-insensitive plate discovery
        assert result is not None
        assert result.name == "lowercase_plate.jpeg"

    def test_find_user_workspace_jpeg_no_user_directory(self, tmp_path: Path) -> None:
        """Test graceful handling when no user/ directory exists."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"
        shot_path.mkdir(parents=True)
        # No user/ directory created

        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        assert result is None  # Should return None, not crash

    def test_find_user_workspace_jpeg_multiple_users(self, tmp_path: Path) -> None:
        """Test that it discovers JPEGs from any user's workspace."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"

        # Create JPEG in second user's directory (first has none)
        (shot_path / "user" / "user1" / "mm" / "nuke" / "outputs").mkdir(
            parents=True
        )  # Empty
        user2_jpeg_dir = (
            shot_path
            / "user"
            / "user2"
            / "mm"
            / "nuke"
            / "outputs"
            / "mm-default"
            / "scene"
            / "FG01"
            / "undistorted_plate"
            / "v001"
            / "4096x2160"
            / "jpeg"
        )
        user2_jpeg_dir.mkdir(parents=True)
        jpeg_file = user2_jpeg_dir / "user2_work.jpeg"
        jpeg_file.write_text("jpeg from user2")

        result = ThumbnailFinders.find_user_workspace_jpeg_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        # Should find JPEG from user2
        assert result is not None
        assert "user2" in str(result)


class TestThumbnailFallbackOrder:
    """Integration tests for editorial/cutref thumbnail discovery with automatic version detection."""

    def test_find_shot_thumbnail_editorial_cutref_latest_version(
        self, tmp_path: Path
    ) -> None:
        """Test that editorial/cutref finds latest version directory automatically."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"

        # Create v001 editorial cutref JPEG
        v001_dir = (
            shot_path
            / "publish"
            / "editorial"
            / "cutref"
            / "v001"
            / "jpg"
            / "1920x1080"
        )
        v001_dir.mkdir(parents=True)
        v001_jpeg = v001_dir / "seq01_shot01_editorial-cutref_v001.1001.jpg"
        v001_jpeg.write_text("v001 jpeg")

        # Create v002 editorial cutref JPEG (should be found - latest version)
        v002_dir = (
            shot_path
            / "publish"
            / "editorial"
            / "cutref"
            / "v002"
            / "jpg"
            / "1920x1080"
        )
        v002_dir.mkdir(parents=True)
        v002_jpeg = v002_dir / "seq01_shot01_editorial-cutref_v002.1001.jpg"
        v002_jpeg.write_text("v002 jpeg")

        result = ThumbnailFinders.find_shot_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        # Should find v002 (latest version)
        assert result is not None
        assert result.suffix.lower() in [".jpg", ".jpeg"]
        assert "v002" in str(result)
        assert result.name == "seq01_shot01_editorial-cutref_v002.1001.jpg"

    def test_find_shot_thumbnail_no_editorial_returns_none(
        self, tmp_path: Path
    ) -> None:
        """Test that find_shot_thumbnail returns None when no editorial/cutref exists."""
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "myshow" / "shots" / "seq01" / "seq01_shot01"

        # Create shot directory but no editorial/cutref
        shot_path.mkdir(parents=True)

        # Create other directories that are NOT editorial/cutref (should be ignored)
        other_dir = shot_path / "publish" / "mm" / "default" / "v001" / "jpeg"
        other_dir.mkdir(parents=True)
        other_jpeg = other_dir / "other.jpg"
        other_jpeg.write_text("other jpeg")

        result = ThumbnailFinders.find_shot_thumbnail(
            str(shows_root), "myshow", "seq01", "shot01"
        )

        # Should return None (no editorial/cutref directory)
        assert result is None
