"""Unit tests for FinderUtils class."""

from __future__ import annotations

# Standard library imports
import re
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
from config import Config
from discovery.finder_utils import FinderUtils


class TestSanitizeUsername:
    """Test username sanitization functionality."""

    @pytest.mark.parametrize(
        ("username", "expected"),
        [
            ("john_doe", "john_doe"),
            ("user123", "user123"),
            ("test-user", "test-user"),
            ("UPPERCASE", "UPPERCASE"),
        ],
        ids=["underscore", "alphanumeric", "hyphen", "uppercase"],
    )
    def test_valid_usernames(self, username: str, expected: str) -> None:
        """Test that valid usernames pass through unchanged."""
        assert FinderUtils.sanitize_username(username) == expected

    @pytest.mark.parametrize(
        ("username", "expected"),
        [
            ("user/../etc", "useretc"),
            ("./user", "user"),
            ("user\\system", "usersystem"),
            ("user/admin", "useradmin"),
        ],
        ids=["parent_dir", "current_dir", "backslash", "forward_slash"],
    )
    def test_path_traversal_removal(self, username: str, expected: str) -> None:
        """Test that path traversal characters are removed."""
        assert FinderUtils.sanitize_username(username) == expected

    @pytest.mark.parametrize(
        ("username", "error_match"),
        [
            ("...", "Invalid username after sanitization"),
            ("", "Invalid username after sanitization"),
            ("user@domain", "Username contains invalid characters"),
            ("user!name", "Username contains invalid characters"),
        ],
        ids=["dots_only", "empty_string", "at_symbol", "exclamation"],
    )
    def test_invalid_usernames_raise_error(
        self, username: str, error_match: str
    ) -> None:
        """Test that invalid usernames raise ValueError."""
        with pytest.raises(ValueError, match=error_match):
            FinderUtils.sanitize_username(username)

    def test_edge_cases(self) -> None:
        """Test edge cases for username sanitization."""
        # Single character usernames
        assert FinderUtils.sanitize_username("a") == "a"
        assert FinderUtils.sanitize_username("1") == "1"

        # Usernames with multiple hyphens/underscores
        assert FinderUtils.sanitize_username("user__name") == "user__name"
        assert FinderUtils.sanitize_username("test--user") == "test--user"


class TestExtractVersion:
    """Test version extraction functionality."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            (Path("file_v001.ma"), 1),
            (Path("scene_v042.3de"), 42),
            (Path("render_v999.exr"), 999),
            ("string_path_v123.txt", 123),
        ],
        ids=["v001_maya", "v042_3de", "v999_exr", "string_path"],
    )
    def test_default_pattern(self, path, expected: int) -> None:
        """Test version extraction with default pattern."""
        assert FinderUtils.extract_version(path) == expected

    def test_custom_pattern_string(self) -> None:
        """Test version extraction with custom string pattern."""
        pattern = r"\.v(\d{4})\."
        assert FinderUtils.extract_version("file.v0001.exr", pattern) == 1
        assert FinderUtils.extract_version("plate.v1234.dpx", pattern) == 1234

    def test_custom_pattern_compiled(self) -> None:
        """Test version extraction with compiled pattern."""
        pattern = re.compile(r"_ver(\d{2})")
        assert FinderUtils.extract_version("file_ver01.txt", pattern) == 1
        assert FinderUtils.extract_version("scene_ver99.ma", pattern) == 99

    @pytest.mark.parametrize(
        "path",
        [
            Path("file_without_version.txt"),
            "no_version_here.ma",
            "v_but_no_numbers.txt",
        ],
        ids=["no_version_pattern", "missing_version", "v_without_numbers"],
    )
    def test_no_version_found(self, path) -> None:
        """Test that None is returned when no version found."""
        assert FinderUtils.extract_version(path) is None

    def test_multiple_versions(self) -> None:
        """Test that first matching version is extracted."""
        assert FinderUtils.extract_version("file_v001_v002.ma") == 1
        assert (
            FinderUtils.extract_version("text_v001_file_v002.txt") == 1
        )  # Fixed to match _v pattern


class TestBuildUserPath:
    """Test VFX user path building."""

    @pytest.mark.parametrize(
        ("workspace", "username", "app", "subdir", "expected"),
        [
            (
                Path(f"{Config.SHOWS_ROOT}/test/shots/010/0010"),
                "john",
                "maya",
                None,
                Path(f"{Config.SHOWS_ROOT}/test/shots/010/0010/user/john/maya/scenes"),
            ),
            (
                Path(f"{Config.SHOWS_ROOT}/test/shots/020/0020"),
                "jane",
                "nuke",
                None,
                Path(f"{Config.SHOWS_ROOT}/test/shots/020/0020/user/jane/nuke/scenes"),
            ),
            (
                Path(f"{Config.SHOWS_ROOT}/test/shots/030/0030"),
                "bob",
                "3de",
                None,
                Path(
                    f"{Config.SHOWS_ROOT}/test/shots/030/0030/user/bob/mm/3de/mm-default/scenes/scene"
                ),
            ),
            (
                Path(f"{Config.SHOWS_ROOT}/test/shots/040/0040"),
                "alice",
                "maya",
                "scripts",
                Path(f"{Config.SHOWS_ROOT}/test/shots/040/0040/user/alice/maya/scripts"),
            ),
        ],
        ids=["maya_default", "nuke_default", "3de_special", "maya_custom_subdir"],
    )
    def test_build_paths(
        self,
        workspace: Path,
        username: str,
        app: str,
        subdir: str | None,
        expected: Path,
    ) -> None:
        """Test VFX user path building for different apps."""
        if subdir:
            path = FinderUtils.build_user_path(workspace, username, app, subdir)
        else:
            path = FinderUtils.build_user_path(workspace, username, app)
        assert path == expected

    def test_3de_ignores_subdir(self) -> None:
        """Test that 3DE ignores custom subdir parameter."""
        workspace = Path(f"{Config.SHOWS_ROOT}/test/shots/050/0050")
        path = FinderUtils.build_user_path(workspace, "charlie", "3de", "custom")
        # 3DE should still use its special structure
        expected = Path(
            f"{Config.SHOWS_ROOT}/test/shots/050/0050/user/charlie/mm/3de/mm-default/scenes/scene"
        )
        assert path == expected


class TestFindLatestByVersion:
    """Test finding latest file by version."""

    def test_find_latest_from_versioned_files(self) -> None:
        """Test finding latest version from list."""
        files = [
            Path("file_v001.ma"),
            Path("file_v005.ma"),
            Path("file_v003.ma"),
            Path("file_v002.ma"),
        ]
        latest = FinderUtils.find_latest_by_version(files)
        assert latest == Path("file_v005.ma")

    @pytest.mark.parametrize(
        "files",
        [
            [],
            [Path("file_without_version.ma"), Path("another_file.txt")],
        ],
        ids=["empty_list", "no_versioned_files"],
    )
    def test_returns_none_when_no_version(self, files: list[Path]) -> None:
        """Test that None is returned when no versioned files."""
        assert FinderUtils.find_latest_by_version(files) is None

    def test_mixed_versioned_and_unversioned(self) -> None:
        """Test handling mix of versioned and unversioned files."""
        files = [
            Path("file_v001.ma"),
            Path("no_version.ma"),
            Path("file_v003.ma"),
            Path("also_no_version.txt"),
        ]
        latest = FinderUtils.find_latest_by_version(files)
        assert latest == Path("file_v003.ma")

    def test_custom_version_pattern(self) -> None:
        """Test with custom version pattern."""
        files = [
            Path("file.v0001.exr"),
            Path("file.v0010.exr"),
            Path("file.v0005.exr"),
        ]
        pattern = r"\.v(\d{4})\."
        latest = FinderUtils.find_latest_by_version(files, pattern)
        assert latest == Path("file.v0010.exr")


class TestSortByVersion:
    """Test version-based sorting."""

    def test_sort_ascending(self) -> None:
        """Test sorting files in ascending version order."""
        files = [
            Path("file_v003.ma"),
            Path("file_v001.ma"),
            Path("file_v002.ma"),
        ]
        sorted_files = FinderUtils.sort_by_version(files)
        assert sorted_files == [
            Path("file_v001.ma"),
            Path("file_v002.ma"),
            Path("file_v003.ma"),
        ]

    def test_sort_descending(self) -> None:
        """Test sorting files in descending version order."""
        files = [
            Path("file_v003.ma"),
            Path("file_v001.ma"),
            Path("file_v002.ma"),
        ]
        sorted_files = FinderUtils.sort_by_version(files, reverse=True)
        assert sorted_files == [
            Path("file_v003.ma"),
            Path("file_v002.ma"),
            Path("file_v001.ma"),
        ]

    def test_unversioned_files_at_end(self) -> None:
        """Test that unversioned files are placed at the end."""
        files = [
            Path("file_v002.ma"),
            Path("no_version.ma"),
            Path("file_v001.ma"),
            Path("also_no_version.txt"),
        ]
        sorted_files = FinderUtils.sort_by_version(files)
        assert sorted_files == [
            Path("file_v001.ma"),
            Path("file_v002.ma"),
            Path("also_no_version.txt"),  # Alphabetically sorted
            Path("no_version.ma"),
        ]


class TestSortByPriority:
    """Test priority-based sorting."""

    def test_basic_priority_sorting(self) -> None:
        """Test sorting items by priority order."""
        items = [
            ("BG01", Path("bg_plate.exr")),
            ("FG01", Path("fg_plate.exr")),
            ("PL01", Path("main_plate.exr")),
        ]
        priority = ["FG01", "PL01", "BG01"]
        sorted_items = FinderUtils.sort_by_priority(items, priority)
        assert sorted_items == [
            ("FG01", Path("fg_plate.exr")),
            ("PL01", Path("main_plate.exr")),
            ("BG01", Path("bg_plate.exr")),
        ]

    def test_unknown_items_go_last(self) -> None:
        """Test that unknown items are placed at the end."""
        items = [
            ("UNKNOWN", Path("unknown.exr")),
            ("PL01", Path("main_plate.exr")),
            ("FG01", Path("fg_plate.exr")),
        ]
        priority = ["FG01", "PL01"]
        sorted_items = FinderUtils.sort_by_priority(items, priority)
        assert sorted_items == [
            ("FG01", Path("fg_plate.exr")),
            ("PL01", Path("main_plate.exr")),
            ("UNKNOWN", Path("unknown.exr")),
        ]

    def test_empty_priority_list(self) -> None:
        """Test behavior with empty priority list."""
        items = [
            ("BG01", Path("bg.exr")),
            ("FG01", Path("fg.exr")),
        ]
        sorted_items = FinderUtils.sort_by_priority(items, [])
        # All items should have same priority, order unchanged
        assert sorted_items == items


class TestParseShotPath:
    """Test shot path parsing."""

    def test_valid_shot_path(self, mock_shows_root: str) -> None:
        """Test parsing valid VFX shot path."""
        path = "/tmp/mock_vfx/shows/test_show/shots/010/0010/user/john/maya/scenes"
        result = FinderUtils.parse_shot_path(path)
        assert result == ("test_show", "010", "0010")

    def test_partial_shot_path(self, mock_shows_root: str) -> None:
        """Test parsing path up to shot level."""
        path = "/tmp/mock_vfx/shows/myshow/shots/020/0020/"
        result = FinderUtils.parse_shot_path(path)
        assert result == ("myshow", "020", "0020")

    @pytest.mark.parametrize(
        "path",
        [
            "/tmp/mock_vfx/shows/test/010/0010",  # Missing shots directory
            "/different/root/test/shots/010/0010",  # Not under shows root
            "",  # Empty path
        ],
        ids=["missing_shots_dir", "wrong_root", "empty_path"],
    )
    def test_invalid_path_returns_none(self, mock_shows_root: str, path: str) -> None:
        """Test that invalid paths return None."""
        assert FinderUtils.parse_shot_path(path) is None


class TestGetWorkspaceFromPath:
    """Test workspace extraction from path."""

    def test_extract_workspace(self, monkeypatch) -> None:
        """Test extracting workspace from full path."""
        # Patch both references used by FinderUtils without reloading modules.
        # Deleting/reimporting modules leaks global state into later tests.
        from config import Config
        from discovery import finder_utils

        test_shows_root = "/tmp/mock_vfx/shows"
        monkeypatch.setattr(Config, "SHOWS_ROOT", test_shows_root)
        monkeypatch.setattr(finder_utils.Config, "SHOWS_ROOT", test_shows_root)

        # Follow VFX naming convention: {sequence}_{shot}
        path = f"{test_shows_root}/test/shots/010/010_0010/user/john/maya/scenes/file.ma"
        workspace = finder_utils.FinderUtils.get_workspace_from_path(path)
        assert workspace == f"{test_shows_root}/test/shots/010/010_0010"

    @pytest.mark.parametrize(
        "path",
        ["/invalid/path", ""],
        ids=["invalid_path", "empty_path"],
    )
    def test_invalid_path_returns_none(self, path: str) -> None:
        """Test that invalid paths return None."""
        assert FinderUtils.get_workspace_from_path(path) is None


class TestIsValidVfxPath:
    """Test VFX path validation."""

    def test_valid_vfx_paths(self, mock_shows_root: str) -> None:
        """Test that valid VFX paths return True."""
        assert (
            FinderUtils.is_valid_vfx_path("/tmp/mock_vfx/shows/test/shots/010/0010/")
            is True
        )
        assert (
            FinderUtils.is_valid_vfx_path(
                "/tmp/mock_vfx/shows/show/shots/seq/shot/user"
            )
            is True
        )

    def test_invalid_vfx_paths(self, mock_shows_root: str) -> None:
        """Test that invalid paths return False."""
        assert FinderUtils.is_valid_vfx_path("/random/path") is False
        assert FinderUtils.is_valid_vfx_path("") is False
        assert (
            FinderUtils.is_valid_vfx_path("/tmp/mock_vfx/shows/test/010/0010") is False
        )


class TestFilterByExtensions:
    """Test file extension filtering."""

    def test_filter_case_insensitive(self) -> None:
        """Test case-insensitive extension filtering."""
        files = [
            Path("file.MA"),
            Path("scene.mb"),
            Path("test.txt"),
            Path("render.exr"),
            Path("MAYA.MB"),
        ]
        filtered = FinderUtils.filter_by_extensions(files, [".ma", ".mb"])
        assert set(filtered) == {Path("file.MA"), Path("scene.mb"), Path("MAYA.MB")}

    def test_filter_case_sensitive(self) -> None:
        """Test case-sensitive extension filtering."""
        files = [
            Path("file.MA"),
            Path("scene.mb"),
            Path("test.txt"),
        ]
        filtered = FinderUtils.filter_by_extensions(
            files, [".ma", ".mb"], case_sensitive=True
        )
        assert filtered == [Path("scene.mb")]

    def test_empty_files_list(self) -> None:
        """Test filtering empty file list."""
        assert FinderUtils.filter_by_extensions([], [".ma"]) == []

    def test_no_matching_extensions(self) -> None:
        """Test when no files match extensions."""
        files = [Path("file.txt"), Path("doc.pdf")]
        assert FinderUtils.filter_by_extensions(files, [".ma", ".mb"]) == []


class TestGetRelativePath:
    """Test relative path calculation."""

    def test_valid_relative_path(self) -> None:
        """Test getting relative path with common base."""
        path = Path(f"{Config.SHOWS_ROOT}/test/shots/010/0010/user/file.ma")
        base = Path(f"{Config.SHOWS_ROOT}/test/shots")
        relative = FinderUtils.get_relative_path(path, base)
        assert relative == Path("010/0010/user/file.ma")

    def test_no_common_base_returns_original(self) -> None:
        """Test that paths without common base return original."""
        path = Path("/different/root/file.ma")
        base = Path(f"{Config.SHOWS_ROOT}/test")
        result = FinderUtils.get_relative_path(path, base)
        assert result == path

    def test_same_path(self) -> None:
        """Test relative path when path equals base."""
        path = Path(f"{Config.SHOWS_ROOT}/test")
        base = Path(f"{Config.SHOWS_ROOT}/test")
        relative = FinderUtils.get_relative_path(path, base)
        assert relative == Path()


class TestFindFilesRecursive:
    """Test recursive file finding with depth limit."""

    def test_find_files_no_depth_limit(self, tmp_path) -> None:
        """Test recursive search without depth limit."""
        # Create test structure
        (tmp_path / "level1").mkdir()
        (tmp_path / "level1" / "file1.ma").touch()
        (tmp_path / "level1" / "level2").mkdir()
        (tmp_path / "level1" / "level2" / "file2.ma").touch()
        (tmp_path / "level1" / "level2" / "level3").mkdir()
        (tmp_path / "level1" / "level2" / "level3" / "file3.ma").touch()

        files = FinderUtils.find_files_recursive(tmp_path, "*.ma")
        assert len(files) == 3

    def test_find_files_with_depth_limit(self, tmp_path) -> None:
        """Test recursive search with depth limit."""
        # Create test structure
        (tmp_path / "level1").mkdir()
        (tmp_path / "file0.ma").touch()  # Depth 0
        (tmp_path / "level1" / "file1.ma").touch()  # Depth 1
        (tmp_path / "level1" / "level2").mkdir()
        (tmp_path / "level1" / "level2" / "file2.ma").touch()  # Depth 2

        # Depth 0: only file0.ma
        files = FinderUtils.find_files_recursive(tmp_path, "*.ma", max_depth=0)
        assert len(files) == 1
        assert "file0.ma" in [f.name for f in files]

        # Depth 1: file0.ma and file1.ma
        files = FinderUtils.find_files_recursive(tmp_path, "*.ma", max_depth=1)
        assert len(files) == 2

        # Depth 2: all files
        files = FinderUtils.find_files_recursive(tmp_path, "*.ma", max_depth=2)
        assert len(files) == 3

    def test_nonexistent_root_returns_empty(self) -> None:
        """Test that nonexistent root returns empty list."""
        files = FinderUtils.find_files_recursive(Path("/nonexistent"), "*.ma")
        assert files == []

    def test_complex_pattern(self, tmp_path) -> None:
        """Test with complex glob pattern."""
        # Create mixed file types
        (tmp_path / "file1.ma").touch()
        (tmp_path / "file2.mb").touch()
        (tmp_path / "file3.txt").touch()
        (tmp_path / "scene_v001.ma").touch()

        # Find versioned Maya files
        files = FinderUtils.find_files_recursive(tmp_path, "*_v*.ma")
        assert len(files) == 1
        assert files[0].name == "scene_v001.ma"
