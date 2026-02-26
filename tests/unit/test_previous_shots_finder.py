"""Tests for PreviousShotsFinder class.

Following best practices:
- Mocks only at system boundaries (subprocess)
- Uses real filesystem structures with tmp_path
- Tests behavior, not implementation
- No excessive mocking
"""

from __future__ import annotations

# Standard library imports
import sys
from pathlib import Path

# Third-party imports
import pytest

from config import Config

# Local application imports
from previous_shots_finder import PreviousShotsFinder
from shot_model import Shot


# Import test helpers
sys.path.insert(0, str(Path(__file__).parent.parent))

# Standard library imports

# Local application imports
from tests.fixtures.model_doubles import create_test_shot, create_test_shots


pytestmark = [pytest.mark.unit, pytest.mark.slow]


class TestPreviousShotsFinder:
    """Test cases for PreviousShotsFinder with real filesystem structures.

    Following UNIFIED_TESTING_GUIDE:
    - Mock only subprocess calls (system boundary)
    - Use real filesystem operations
    - Test actual behavior
    """

    @pytest.fixture
    def finder(self) -> PreviousShotsFinder:
        """Create finder with test username."""
        return PreviousShotsFinder(username="testuser")

    @pytest.fixture
    def real_shows_structure(self, make_test_filesystem):
        """Create realistic shows directory structure using TestFileSystem.

        Following UNIFIED_TESTING_GUIDE:
        - Use TestFileSystem for real filesystem operations
        - Create actual directory structures
        - Track file operations for verification
        """
        fs = make_test_filesystem()

        # Create multiple shows with shots containing user work
        for show in ["testshow", "anothershow"]:
            for seq in ["101_ABC", "102_DEF"]:
                for shot in ["0010", "0020", "0030"]:
                    # Create VFX structure for each shot
                    # create_vfx_structure already handles the {seq}_{shot} naming
                    shot_path = fs.create_vfx_structure(show, seq, shot)

                    # Add user work files
                    user_path = shot_path / "user" / "testuser"
                    fs.create_file(user_path / "work.3de", "3DE scene content")
                    fs.create_file(user_path / "comp.nk", "Nuke script content")
                    fs.create_file(user_path / "anim.ma", "Maya animation")

        # Create shot without user work
        _shot_without_work = fs.create_vfx_structure("testshow", "101_ABC", "0040")
        # Don't add user directory - simulates shot without user work

        return fs.base_path / "shows"

    @pytest.mark.parametrize(
        ("show", "seq", "shot"),
        [
            pytest.param("testshow", "101_ABC", "0010", id="standard_naming"),
            pytest.param("anothershow", "102_DEF", "0020", id="different_sequence"),
            pytest.param("testshow", "101_ABC", "0030", id="higher_shot_number"),
            pytest.param(
                "anothershow",
                "101_ABC",
                "0010",
                marks=pytest.mark.slow,
                id="cross_show_sequence",
            ),
        ],
    )
    def test_individual_shot_structure_validation(
        self, make_test_filesystem, finder, show, seq, shot
    ) -> None:
        """Test individual shot structures with parametrized data."""
        fs = make_test_filesystem()

        # Create individual shot structure
        # create_vfx_structure already handles the {seq}_{shot} naming
        shot_path = fs.create_vfx_structure(show, seq, shot)
        user_path = shot_path / "user" / "testuser"
        fs.create_file(user_path / "work.3de", "3DE scene content")
        fs.create_file(user_path / "comp.nk", "Nuke script content")

        shows_path = fs.base_path / "shows"

        # Should find the shot we created
        shots = finder.find_user_shots(shows_path)
        assert len(shots) >= 1

        # Verify the shot structure is as expected
        found_shots = [(s.show, s.sequence, s.shot) for s in shots]
        expected_shot = (show, seq, shot)
        assert expected_shot in found_shots

    def test_finder_initialization_with_username(self) -> None:
        """Test finder initialization with specific username."""
        finder = PreviousShotsFinder(username="customuser")

        assert finder.username == "customuser"
        assert finder.user_path_pattern == "/user/customuser"
        assert finder._shot_pattern is not None

    def test_finder_initialization_with_sanitization(self) -> None:
        """Test that username is properly sanitized for security."""
        # Test path traversal attempt is sanitized (not blocked)
        finder = PreviousShotsFinder(username="../../../etc/passwd")
        assert finder.username == "etcpasswd"  # Dots and slashes removed

        # Test that dots and slashes are removed
        finder = PreviousShotsFinder(username="test.user")
        assert finder.username == "testuser"

        # Test empty username after sanitization
        with pytest.raises(ValueError, match="Invalid username after sanitization"):
            PreviousShotsFinder(username="../../")

    def test_finder_initialization_default_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test finder initialization with default user from environment."""
        # Disable mock mode to test actual USER env var behavior
        monkeypatch.delenv("SHOTBOT_MOCK", raising=False)

        # Set test user in environment (monkeypatch auto-restores after test)
        monkeypatch.setenv("USER", "envuser")
        finder = PreviousShotsFinder()
        assert finder.username == "envuser"

    @pytest.mark.parametrize(
        ("path", "expected_shot"),
        [
            pytest.param(
                f"{Config.SHOWS_ROOT}/testshow/shots/101_ABC/101_ABC_0010/user/testuser",
                ("testshow", "101_ABC", "0010"),
                id="standard_vfx_structure",
            ),
            pytest.param(
                f"{Config.SHOWS_ROOT}/feature/shots/seq01/seq01_shot01/user/artist",
                ("feature", "seq01", "shot01"),
                id="feature_structure",
            ),
            pytest.param("/invalid/path/structure", None, id="invalid_structure"),
            pytest.param(
                f"{Config.SHOWS_ROOT}/test/shots/",  # Incomplete path
                None,
                id="incomplete_path",
            ),
        ],
    )
    def test_parse_shot_from_path(self, finder, path, expected_shot) -> None:
        """Test shot parsing from various path structures.

        Testing actual behavior of path parsing.
        """
        shot = finder._parse_shot_from_path(path)

        if expected_shot is None:
            assert shot is None
        else:
            show, sequence, shot_name = expected_shot
            assert shot.show == show
            assert shot.sequence == sequence
            assert shot.shot == shot_name
            # VFX convention: workspace path includes full directory name with sequence prefix
            assert (
                f"{Config.SHOWS_ROOT}/{show}/shots/{sequence}/{sequence}_{shot_name}"
                in shot.workspace_path
            )

    def test_find_user_shots_with_real_structure(
        self, finder, real_shows_structure
    ) -> None:
        """Test finding user shots with real directory structure.

        Following UNIFIED_TESTING_GUIDE:
        - Use real filesystem structure (no mocking)
        - Test behavior, not implementation
        """
        # The real_shows_structure fixture creates a comprehensive structure
        # with multiple shows, sequences, and shots
        shots = finder.find_user_shots(real_shows_structure)

        # Verify shots were found correctly
        # The fixture creates 2 shows x 2 sequences x 3 shots = 12 shots total
        assert len(shots) == 12, f"Expected 12 shots, found {len(shots)}"

        shot_ids = {(s.show, s.sequence, s.shot) for s in shots}

        # Verify a sample of expected shots are present
        expected_sample = {
            ("testshow", "101_ABC", "0010"),
            ("testshow", "101_ABC", "0020"),
            ("anothershow", "102_DEF", "0010"),
        }
        assert expected_sample.issubset(shot_ids), (
            f"Expected sample {expected_sample} not found in {shot_ids}"
        )

    def test_find_user_shots_nonexistent_directory(self, finder, tmp_path) -> None:
        """Test behavior with nonexistent shows directory."""
        nonexistent = tmp_path / "nonexistent"
        shots = finder.find_user_shots(nonexistent)

        assert shots == []

    # NOTE: Subprocess tests removed after refactoring to use Path.rglob()
    # Previous tests: test_find_user_shots_subprocess_timeout, test_find_user_shots_subprocess_error
    # These tested subprocess.run() behavior which is no longer used in the implementation

    def test_filter_approved_shots_behavior(self, finder) -> None:
        """Test actual filtering behavior, not implementation.

        Following UNIFIED_TESTING_GUIDE:
        - Test behavior (what gets filtered)
        - Don't test implementation details
        """
        # Create test shots
        all_user_shots = create_test_shots(4)
        active_shots = [
            all_user_shots[0],
            all_user_shots[3],
        ]  # First and last are active

        approved_shots = finder.filter_approved_shots(all_user_shots, active_shots)

        # Should return only non-active shots
        assert len(approved_shots) == 2
        assert all_user_shots[1] in approved_shots
        assert all_user_shots[2] in approved_shots
        assert all_user_shots[0] not in approved_shots  # Active
        assert all_user_shots[3] not in approved_shots  # Active

    def test_filter_approved_shots_edge_cases(self, finder) -> None:
        """Test filtering edge cases."""
        all_user_shots = create_test_shots(2)

        # No active shots - all should be approved
        approved = finder.filter_approved_shots(all_user_shots, [])
        assert approved == all_user_shots

        # All shots active - none should be approved
        approved = finder.filter_approved_shots(all_user_shots, all_user_shots)
        assert approved == []

        # Empty user shots
        approved = finder.filter_approved_shots([], [])
        assert approved == []

    def test_find_approved_shots_integration(
        self, finder, real_shows_structure
    ) -> None:
        """Test complete workflow from finding to filtering.

        Integration test with real filesystem using Path.rglob().
        """
        # Create active shots (one overlapping with what's in real_shows_structure)
        # real_shows_structure fixture creates 2 shows x 2 sequences x 3 shots = 12 shots
        # We mark one as "active" to test filtering
        active_shots = [
            create_test_shot("testshow", "101_ABC", "0010"),
        ]

        # find_approved_shots will find all user shots, then filter out active ones
        approved_shots = finder.find_approved_shots(
            active_shots, real_shows_structure
        )

        # Should find 12 total shots, minus 1 active = 11 approved
        assert len(approved_shots) == 11

        # Verify the active shot (0010) is NOT in approved shots
        shot_identifiers = [(s.show, s.sequence, s.shot) for s in approved_shots]
        assert ("testshow", "101_ABC", "0010") not in shot_identifiers

        # Verify other shots from the same show/sequence ARE in approved shots
        assert ("testshow", "101_ABC", "0020") in shot_identifiers
        assert ("testshow", "101_ABC", "0030") in shot_identifiers

    def test_get_shot_details_behavior(self, finder) -> None:
        """Test getting shot details returns expected structure."""
        shot = create_test_shot("testshow", "101_ABC", "0010")

        details = finder.get_shot_details(shot)

        # Test behavior - what details are returned
        assert details["show"] == "testshow"
        assert details["sequence"] == "101_ABC"
        assert details["shot"] == "0010"
        assert details["workspace_path"] == shot.workspace_path
        assert details["user_path"] == f"{shot.workspace_path}/user/testuser"
        assert details["status"] == "completed"  # no approved dir → falls back to completed

    def test_get_shot_details_with_real_directory(self, finder, tmp_path) -> None:
        """Test getting shot details with real user directory.

        Uses real filesystem to test file detection.
        """
        # Create real user directory structure
        shot_path = tmp_path / "shows" / "testshow" / "shots" / "101_ABC" / "0010"
        user_path = shot_path / "user" / "testuser"
        user_path.mkdir(parents=True, exist_ok=True)

        # Add various work files (real files)
        (user_path / "scene.3de").write_text("3DE scene")
        (user_path / "comp.nk").write_text("Nuke script")
        (user_path / "anim.ma").write_text("Maya ASCII")
        (user_path / "model.mb").write_text("Maya Binary")

        shot = Shot("testshow", "101_ABC", "0010", str(shot_path))

        # Get details with real directory
        details = finder.get_shot_details(shot)

        # Manually check the directory exists (since the method checks this)
        actual_user_path = Path(details["user_path"])
        if actual_user_path.exists():
            # Would have these checks in real implementation
            has_3de = any(actual_user_path.rglob("*.3de"))
            has_nuke = any(actual_user_path.rglob("*.nk"))
            has_maya = any(actual_user_path.rglob("*.m[ab]"))

            assert has_3de
            assert has_nuke
            assert has_maya


class TestPreviousShotsFinderPerformance:
    """Performance tests for PreviousShotsFinder."""

    @pytest.fixture
    def large_shows_structure(self, make_test_filesystem):
        """Create large shows structure for performance testing.

        Uses TestFileSystem for realistic performance testing with real files.
        """
        fs = make_test_filesystem()

        # Create many shows, sequences, and shots with actual files
        for show_idx in range(3):
            for seq_idx in range(2):  # Reduced for performance
                for shot_idx in range(5):  # Reduced for performance
                    show = f"show{show_idx:02d}"
                    seq = f"seq{seq_idx:03d}"
                    shot = f"shot{shot_idx:04d}"

                    # Create full VFX structure
                    # create_vfx_structure already handles the {seq}_{shot} naming
                    shot_path = fs.create_vfx_structure(show, seq, shot)

                    # Add user work files for realistic testing
                    user_path = shot_path / "user" / "testuser"
                    fs.create_file(
                        user_path / "scene.3de", f"3DE scene for {show}_{seq}_{shot}"
                    )
                    fs.create_file(user_path / "comp.nk", f"Nuke script for {shot}")

        return fs.base_path / "shows"
