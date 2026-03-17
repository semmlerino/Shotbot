"""Tests for SceneParser 3DE path parsing and plate extraction.

Tests cover:
- extract_plate_from_path(): BG/FG pattern detection, plate patterns, fallbacks
- parse_3de_file_path(): Path parsing with excluded users, sequence/shot extraction
- create_scene_from_file_info(): Scene object construction
- extract_shot_from_workspace_path(): Workspace path parsing
- validate_scene_file(): File existence and extension checking
- Pattern helpers: is_bg_fg_plate, matches_plate_pattern, is_generic_directory
"""

from __future__ import annotations

from pathlib import Path

import pytest

from discovery.scene_parser import SceneParser


pytestmark = [pytest.mark.smoke]


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def parser() -> SceneParser:
    """Create a fresh SceneParser instance."""
    return SceneParser()


@pytest.fixture
def tmp_show_path(tmp_path: Path) -> Path:
    """Create a temporary show directory structure."""
    show_path = tmp_path / "myshow"
    (show_path / "shots" / "seq01" / "seq01_0010" / "user" / "artist").mkdir(
        parents=True
    )
    (show_path / "shots" / "seq01" / "seq01_0010" / "publish" / "mm").mkdir(
        parents=True
    )
    return show_path


# ==============================================================================
# extract_plate_from_path Tests
# ==============================================================================


class TestExtractPlateFromPathBGFGPatterns:
    """Tests for BG/FG plate pattern detection."""

    @pytest.mark.parametrize(
        ("parent_name", "expected"),
        [
            ("bg01", "bg01"),
            ("fg02", "fg02"),
            ("BG01", "BG01"),
            ("FG10", "FG10"),
            ("bg99", "bg99"),
            ("fg00", "fg00"),
        ],
    )
    def test_detects_bg_fg_in_parent_directory(
        self,
        parser: SceneParser,
        tmp_path: Path,
        parent_name: str,
        expected: str,
    ) -> None:
        """BG/FG patterns in parent directory are detected."""
        user_path = tmp_path / "user" / "artist"
        file_path = user_path / parent_name / "scene.3de"
        user_path.mkdir(parents=True)
        (user_path / parent_name).mkdir()

        result = parser.extract_plate_from_path(file_path, user_path)

        assert result == expected

    def test_detects_bg_fg_in_deeper_path(
        self,
        parser: SceneParser,
        tmp_path: Path,
    ) -> None:
        """BG/FG patterns in deeper path parts are detected."""
        user_path = tmp_path / "user" / "artist"
        file_path = user_path / "3de" / "bg01" / "scene.3de"
        (user_path / "3de" / "bg01").mkdir(parents=True)

        result = parser.extract_plate_from_path(file_path, user_path)

        assert result == "bg01"


class TestExtractPlateFromPathOtherPatterns:
    """Tests for other plate pattern detection."""

    @pytest.mark.parametrize(
        ("plate_name", "expected"),
        [
            ("plate_1", "plate_1"),
            ("plate_10", "plate_10"),
            ("comp_1", "comp_1"),
            ("comp_99", "comp_99"),
            ("shot_1", "shot_1"),
            ("sc1", "sc1"),
            ("sc99", "sc99"),
            ("name_v001", "name_v001"),
            ("scene_v123", "scene_v123"),
        ],
    )
    def test_detects_other_plate_patterns(
        self,
        parser: SceneParser,
        tmp_path: Path,
        plate_name: str,
        expected: str,
    ) -> None:
        """Other plate patterns are detected."""
        user_path = tmp_path / "user" / "artist"
        file_path = user_path / plate_name / "scene.3de"
        (user_path / plate_name).mkdir(parents=True)

        result = parser.extract_plate_from_path(file_path, user_path)

        assert result == expected


class TestExtractPlateFromPathFallbacks:
    """Tests for fallback behavior in plate extraction."""

    def test_falls_back_to_non_generic_directory(
        self,
        parser: SceneParser,
        tmp_path: Path,
    ) -> None:
        """Falls back to non-generic directory closest to file."""
        user_path = tmp_path / "user" / "artist"
        file_path = user_path / "custom_plate" / "3de" / "scene.3de"
        (user_path / "custom_plate" / "3de").mkdir(parents=True)

        result = parser.extract_plate_from_path(file_path, user_path)

        # "3de" is generic, so falls back to "custom_plate"
        assert result == "custom_plate"

    def test_uses_parent_when_all_generic(
        self,
        parser: SceneParser,
        tmp_path: Path,
    ) -> None:
        """Uses parent directory name when all are generic."""
        user_path = tmp_path / "user" / "artist"
        file_path = user_path / "3de" / "scenes" / "scene.3de"
        (user_path / "3de" / "scenes").mkdir(parents=True)

        result = parser.extract_plate_from_path(file_path, user_path)

        # Both are generic, so uses immediate parent "scenes"
        assert result == "scenes"

    def test_handles_relative_path_error(
        self,
        parser: SceneParser,
        tmp_path: Path,
    ) -> None:
        """Handles case where file is not relative to user_path."""
        user_path = tmp_path / "user" / "artist"
        file_path = Path("/completely/different/path/scene.3de")
        user_path.mkdir(parents=True)

        result = parser.extract_plate_from_path(file_path, user_path)

        # Falls back to parent directory name
        assert result == "path"


# ==============================================================================
# parse_3de_file_path Tests
# ==============================================================================


class TestParse3DEFilePathStandard:
    """Tests for standard 3DE file path parsing."""

    def test_parses_standard_user_path(
        self,
        parser: SceneParser,
        tmp_show_path: Path,
    ) -> None:
        """Parses standard user directory structure."""
        threede_file = (
            tmp_show_path
            / "shots"
            / "seq01"
            / "seq01_0010"
            / "user"
            / "artist"
            / "bg01"
            / "scene.3de"
        )
        threede_file.parent.mkdir(parents=True)
        threede_file.touch()

        result = parser.parse_3de_file_path(
            threede_file,
            tmp_show_path,
            "myshow",
            excluded_users=set(),
        )

        assert result is not None
        file_path, show, sequence, shot, user, plate = result
        assert file_path == threede_file
        assert show == "myshow"
        assert sequence == "seq01"
        assert shot == "0010"
        assert user == "artist"
        assert plate == "bg01"

    def test_parses_published_path(
        self,
        parser: SceneParser,
        tmp_show_path: Path,
    ) -> None:
        """Parses published directory structure with pseudo-user."""
        threede_file = (
            tmp_show_path
            / "shots"
            / "seq01"
            / "seq01_0010"
            / "publish"
            / "mm"
            / "scene.3de"
        )
        threede_file.parent.mkdir(parents=True, exist_ok=True)
        threede_file.touch()

        result = parser.parse_3de_file_path(
            threede_file,
            tmp_show_path,
            "myshow",
            excluded_users=set(),
        )

        assert result is not None
        _, _, _, _, user, _ = result
        assert user == "published-mm"


class TestParse3DEFilePathExcludedUsers:
    """Tests for excluded user filtering."""

    def test_excludes_specified_users(
        self,
        parser: SceneParser,
        tmp_show_path: Path,
    ) -> None:
        """Paths from excluded users return None."""
        threede_file = (
            tmp_show_path
            / "shots"
            / "seq01"
            / "seq01_0010"
            / "user"
            / "excluded_artist"
            / "scene.3de"
        )
        threede_file.parent.mkdir(parents=True)
        threede_file.touch()

        result = parser.parse_3de_file_path(
            threede_file,
            tmp_show_path,
            "myshow",
            excluded_users={"excluded_artist"},
        )

        assert result is None

    def test_allows_non_excluded_users(
        self,
        parser: SceneParser,
        tmp_show_path: Path,
    ) -> None:
        """Paths from non-excluded users are parsed."""
        threede_file = (
            tmp_show_path
            / "shots"
            / "seq01"
            / "seq01_0010"
            / "user"
            / "allowed_artist"
            / "scene.3de"
        )
        threede_file.parent.mkdir(parents=True)
        threede_file.touch()

        result = parser.parse_3de_file_path(
            threede_file,
            tmp_show_path,
            "myshow",
            excluded_users={"other_user"},
        )

        assert result is not None


class TestParse3DEFilePathInvalidPaths:
    """Tests for invalid path handling."""

    def test_rejects_path_without_shots_directory(
        self,
        parser: SceneParser,
        tmp_show_path: Path,
    ) -> None:
        """Paths without 'shots' directory return None."""
        invalid_path = tmp_show_path / "assets" / "seq01" / "scene.3de"
        invalid_path.parent.mkdir(parents=True)

        result = parser.parse_3de_file_path(
            invalid_path,
            tmp_show_path,
            "myshow",
            excluded_users=set(),
        )

        assert result is None

    def test_rejects_path_too_short(
        self,
        parser: SceneParser,
        tmp_show_path: Path,
    ) -> None:
        """Paths with too few segments return None."""
        short_path = tmp_show_path / "shots" / "scene.3de"
        short_path.parent.mkdir(parents=True, exist_ok=True)

        result = parser.parse_3de_file_path(
            short_path,
            tmp_show_path,
            "myshow",
            excluded_users=set(),
        )

        assert result is None

    def test_rejects_non_standard_structure(
        self,
        parser: SceneParser,
        tmp_show_path: Path,
    ) -> None:
        """Paths without user/publish directory return None."""
        weird_path = (
            tmp_show_path
            / "shots"
            / "seq01"
            / "seq01_0010"
            / "other"
            / "scene.3de"
        )
        weird_path.parent.mkdir(parents=True)

        result = parser.parse_3de_file_path(
            weird_path,
            tmp_show_path,
            "myshow",
            excluded_users=set(),
        )

        assert result is None


class TestParse3DEFilePathShotExtraction:
    """Tests for shot name extraction from directory names."""

    @pytest.mark.parametrize(
        ("shot_dir", "expected_shot"),
        [
            ("seq01_0010", "0010"),
            ("seq01_0020", "0020"),
            ("ABC_001", "001"),
            ("finale_finalshot", "finalshot"),
        ],
    )
    def test_extracts_shot_with_sequence_prefix(
        self,
        parser: SceneParser,
        tmp_path: Path,
        shot_dir: str,
        expected_shot: str,
    ) -> None:
        """Extracts shot name when directory has sequence prefix."""
        sequence = shot_dir.split("_", maxsplit=1)[0]
        show_path = tmp_path / "myshow"
        threede_file = (
            show_path
            / "shots"
            / sequence
            / shot_dir
            / "user"
            / "artist"
            / "scene.3de"
        )
        threede_file.parent.mkdir(parents=True)
        threede_file.touch()

        result = parser.parse_3de_file_path(
            threede_file,
            show_path,
            "myshow",
            excluded_users=set(),
        )

        assert result is not None
        _, _, _, shot, _, _ = result
        assert shot == expected_shot

    def test_handles_no_underscore_in_shot_dir(
        self,
        parser: SceneParser,
        tmp_path: Path,
    ) -> None:
        """Uses full directory name when no underscore present."""
        show_path = tmp_path / "myshow"
        threede_file = (
            show_path
            / "shots"
            / "seq"
            / "nounderscoreshot"
            / "user"
            / "artist"
            / "scene.3de"
        )
        threede_file.parent.mkdir(parents=True)
        threede_file.touch()

        result = parser.parse_3de_file_path(
            threede_file,
            show_path,
            "myshow",
            excluded_users=set(),
        )

        assert result is not None
        _, _, _, shot, _, _ = result
        assert shot == "nounderscoreshot"


# ==============================================================================
# extract_shot_from_workspace_path Tests
# ==============================================================================


class TestExtractShotFromWorkspacePath:
    """Tests for workspace path parsing."""

    def test_extracts_from_standard_workspace(self, parser: SceneParser) -> None:
        """Extracts show, sequence, shot from standard workspace."""
        workspace = "/shows/myshow/shots/seq01/seq01_0010"

        result = parser.extract_shot_from_workspace_path(workspace)

        assert result is not None
        show, sequence, shot = result
        assert show == "myshow"
        assert sequence == "seq01"
        assert shot == "0010"

    def test_extracts_from_workspace_with_subpath(
        self,
        parser: SceneParser,
    ) -> None:
        """Extracts from workspace path with additional subdirectories."""
        workspace = "/shows/myshow/shots/seq01/seq01_0010/user/artist/3de"

        result = parser.extract_shot_from_workspace_path(workspace)

        assert result is not None
        show, sequence, shot = result
        assert show == "myshow"
        assert sequence == "seq01"
        assert shot == "0010"

    def test_returns_none_for_invalid_path(self, parser: SceneParser) -> None:
        """Returns None for paths without 'shots' directory."""
        invalid_workspace = "/shows/myshow/assets/seq01"

        result = parser.extract_shot_from_workspace_path(invalid_workspace)

        assert result is None

    def test_handles_show_name_with_underscore(self, parser: SceneParser) -> None:
        """Handles show names containing underscores."""
        workspace = "/shows/jack_ryan/shots/100/100_0010"

        result = parser.extract_shot_from_workspace_path(workspace)

        assert result is not None
        show, _, _ = result
        assert show == "jack_ryan"


# ==============================================================================
# validate_scene_file Tests
# ==============================================================================


class TestValidateSceneFile:
    """Tests for scene file validation."""

    def test_valid_3de_file(
        self,
        parser: SceneParser,
        tmp_path: Path,
    ) -> None:
        """Valid .3de file passes validation."""
        scene_file = tmp_path / "scene.3de"
        scene_file.write_text("scene content")

        assert parser.validate_scene_file(scene_file) is True

    def test_rejects_nonexistent_file(self, parser: SceneParser) -> None:
        """Nonexistent file fails validation."""
        assert parser.validate_scene_file(Path("/nonexistent/scene.3de")) is False

    def test_rejects_wrong_extension(
        self,
        parser: SceneParser,
        tmp_path: Path,
    ) -> None:
        """Files with wrong extension fail validation."""
        wrong_ext = tmp_path / "scene.ma"
        wrong_ext.write_text("maya scene")

        assert parser.validate_scene_file(wrong_ext) is False

    def test_rejects_empty_file(
        self,
        parser: SceneParser,
        tmp_path: Path,
    ) -> None:
        """Empty files fail validation."""
        empty_file = tmp_path / "empty.3de"
        empty_file.touch()

        assert parser.validate_scene_file(empty_file) is False

    def test_rejects_directory(
        self,
        parser: SceneParser,
        tmp_path: Path,
    ) -> None:
        """Directories fail validation."""
        dir_path = tmp_path / "scene.3de"
        dir_path.mkdir()

        assert parser.validate_scene_file(dir_path) is False


# ==============================================================================
# Pattern Helper Tests
# ==============================================================================


class TestIsBgFgPlate:
    """Tests for is_bg_fg_plate() helper."""

    @pytest.mark.parametrize(
        "plate_name",
        ["bg01", "fg02", "BG01", "FG10", "bg99", "fg00"],
    )
    def test_matches_valid_bg_fg_patterns(
        self,
        parser: SceneParser,
        plate_name: str,
    ) -> None:
        """Valid BG/FG patterns return True."""
        assert parser.is_bg_fg_plate(plate_name) is True

    @pytest.mark.parametrize(
        "plate_name",
        ["plate_1", "comp_1", "bg", "fg", "bg001", "fg1", "background"],
    )
    def test_rejects_invalid_patterns(
        self,
        parser: SceneParser,
        plate_name: str,
    ) -> None:
        """Invalid patterns return False."""
        assert parser.is_bg_fg_plate(plate_name) is False


class TestMatchesPlatePattern:
    """Tests for matches_plate_pattern() helper."""

    @pytest.mark.parametrize(
        "name",
        [
            "bg01",
            "fg02",
            "plate_1",
            "plate_10",
            "comp_1",
            "shot_1",
            "sc1",
            "name_v001",
        ],
    )
    def test_matches_valid_patterns(
        self,
        parser: SceneParser,
        name: str,
    ) -> None:
        """Valid plate patterns return True."""
        assert parser.matches_plate_pattern(name) is True

    @pytest.mark.parametrize(
        "name",
        ["random_name", "3de", "scenes", "work", "user"],
    )
    def test_rejects_non_plate_patterns(
        self,
        parser: SceneParser,
        name: str,
    ) -> None:
        """Non-plate patterns return False."""
        assert parser.matches_plate_pattern(name) is False


class TestIsGenericDirectory:
    """Tests for is_generic_directory() helper."""

    @pytest.mark.parametrize(
        "dir_name",
        [
            "3de",
            "scenes",
            "scene",
            "mm",
            "matchmove",
            "tracking",
            "work",
            "wip",
            "exports",
            "user",
            "files",
            "data",
        ],
    )
    def test_identifies_generic_directories(
        self,
        parser: SceneParser,
        dir_name: str,
    ) -> None:
        """Generic directories return True."""
        assert parser.is_generic_directory(dir_name) is True

    @pytest.mark.parametrize(
        "dir_name",
        ["bg01", "plate_1", "custom_folder", "my_shots"],
    )
    def test_rejects_non_generic_directories(
        self,
        parser: SceneParser,
        dir_name: str,
    ) -> None:
        """Non-generic directories return False."""
        assert parser.is_generic_directory(dir_name) is False

    def test_case_insensitive(self, parser: SceneParser) -> None:
        """Generic directory check is case-insensitive."""
        assert parser.is_generic_directory("3DE") is True
        assert parser.is_generic_directory("Scenes") is True
        assert parser.is_generic_directory("MATCHMOVE") is True


class TestGetPatterns:
    """Tests for pattern accessor methods."""

    def test_get_plate_patterns_returns_copy(self, parser: SceneParser) -> None:
        """get_plate_patterns() returns a copy of patterns list."""
        patterns1 = parser.get_plate_patterns()
        patterns2 = parser.get_plate_patterns()

        assert patterns1 is not patterns2
        assert len(patterns1) > 0

    def test_get_generic_directories_returns_copy(
        self,
        parser: SceneParser,
    ) -> None:
        """get_generic_directories() returns a copy of directory set."""
        dirs1 = parser.get_generic_directories()
        dirs2 = parser.get_generic_directories()

        assert dirs1 is not dirs2
        assert len(dirs1) > 0
        assert "3de" in dirs1
