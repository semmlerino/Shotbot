"""Integration tests for thumbnail discovery with minimal pytest overhead."""

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns

# Standard library imports
import sys
import traceback
from pathlib import Path

# Third-party imports
import pytest

from discovery import ThumbnailFinders

# Local application imports
# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.fixtures.test_doubles import (
    TestSubprocess,
)


pytestmark = [
    pytest.mark.integration,  # CRITICAL: Qt state must be serialized
]


class TestThumbnailDiscoveryIntegration:
    """Integration tests for thumbnail discovery."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path) -> None:
        """Minimal setup to avoid pytest fixture overhead."""
        # Use test double for subprocess (UNIFIED_TESTING_GUIDE)
        self.test_subprocess = TestSubprocess()
        self.temp_dir = tmp_path / "shotbot"
        self.temp_dir.mkdir()
        self.shows_root = self.temp_dir / "shows"
        self.shows_root.mkdir(parents=True, exist_ok=True)

    def test_turnover_plate_discovery_integration(self) -> None:
        """Integration test for turnover plate discovery across different structures."""
        # Import locally to avoid pytest environment issues

        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        # Test Case 1: Structure without input_plate subdirectory
        plate_path1 = (
            self.shows_root
            / "show1"
            / "shots"
            / "seq01"
            / "seq01_shot01"
            / "publish"
            / "turnover"
            / "plate"
            / "FG01"
            / "v001"
            / "exr"
            / "4K"
        )
        plate_path1.mkdir(parents=True)
        test_file1 = plate_path1 / "seq01_shot01_FG01_v001.1001.exr"
        test_file1.write_bytes(b"EXR1")

        result1 = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(self.shows_root), "show1", "seq01", "shot01"
        )

        assert result1 == test_file1
        assert "FG01" in str(result1)

        # Test Case 2: Structure with input_plate subdirectory
        plate_path2 = (
            self.shows_root
            / "show2"
            / "shots"
            / "seq02"
            / "seq02_shot02"
            / "publish"
            / "turnover"
            / "plate"
            / "input_plate"
            / "BG01"
            / "v001"
            / "exr"
            / "2K"
        )
        plate_path2.mkdir(parents=True)
        test_file2 = plate_path2 / "seq02_shot02_BG01_v001.1001.exr"
        test_file2.write_bytes(b"EXR2")

        result2 = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(self.shows_root), "show2", "seq02", "shot02"
        )

        assert result2 == test_file2
        assert "BG01" in str(result2)

    def test_plate_priority_integration(self) -> None:
        """Integration test for plate priority ordering (FG > BG > others)."""
        # Import locally

        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        # Create multiple plate types in same shot
        base_path = (
            self.shows_root
            / "priority_test"
            / "shots"
            / "seq01"
            / "seq01_shot01"
            / "publish"
            / "turnover"
            / "plate"
        )

        # Create BG01 (second priority)
        bg_path = base_path / "BG01" / "v001" / "exr" / "2K"
        bg_path.mkdir(parents=True)
        bg_file = bg_path / "shot01_BG01.1001.exr"
        bg_file.write_bytes(b"BG_EXR")

        # Create EL01 (lowest priority)
        el_path = base_path / "EL01" / "v001" / "exr" / "2K"
        el_path.mkdir(parents=True)
        el_file = el_path / "shot01_EL01.1001.exr"
        el_file.write_bytes(b"EL_EXR")

        # Create FG01 (highest priority)
        fg_path = base_path / "FG01" / "v001" / "exr" / "2K"
        fg_path.mkdir(parents=True)
        fg_file = fg_path / "shot01_FG01.1001.exr"
        fg_file.write_bytes(b"FG_EXR")

        # Should return FG01 as it has highest priority
        result = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(self.shows_root), "priority_test", "seq01", "shot01"
        )

        assert result == fg_file
        assert "FG01" in str(result)

    def test_fallback_discovery_integration(self) -> None:
        """Integration test for fallback thumbnail discovery."""
        # Import locally

        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        # Create shot structure with publish directory for fallback search
        shot_path = (
            self.shows_root
            / "fallback_test"
            / "shots"
            / "seq01"
            / "seq01_shot01"
            / "publish"
            / "comp"
            / "renders"
        )
        shot_path.mkdir(parents=True)

        # Create fallback EXR file with 1001 in the name (required by find_any_publish_thumbnail)
        fallback_file = shot_path / "comp_beauty.1001.exr"
        fallback_file.write_bytes(b"FALLBACK_EXR")

        # Should find the fallback file when no turnover plates exist
        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(self.shows_root), "fallback_test", "seq01", "shot01", max_depth=5
        )

        assert result is not None, "Should find fallback EXR file"
        assert result == fallback_file
        assert "1001" in result.name

    def test_deep_nesting_integration(self) -> None:
        """Integration test for deeply nested file discovery."""
        # Import locally

        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        # Create deeply nested structure in publish directory
        deep_path = (
            self.shows_root
            / "deep_test"
            / "shots"
            / "seq01"
            / "seq01_shot01"
            / "publish"
            / "level1"
            / "level2"
            / "level3"
            / "level4"
            / "level5"
        )
        deep_path.mkdir(parents=True)

        # Create deeply nested file with 1001 in name
        deep_file = deep_path / "deep_nested.1001.exr"
        deep_file.write_bytes(b"DEEP_EXR")

        # Should find deeply nested files within max_depth limit
        result = ThumbnailFinders.find_any_publish_thumbnail(
            str(self.shows_root), "deep_test", "seq01", "shot01", max_depth=8
        )

        assert result is not None, "Should find deeply nested file within max_depth"
        assert result == deep_file
        assert "1001" in result.name

        # Should NOT find files beyond max_depth limit
        result_limited = ThumbnailFinders.find_any_publish_thumbnail(
            str(self.shows_root), "deep_test", "seq01", "shot01", max_depth=3
        )

        # With max_depth=3, it should not reach the deeply nested file
        assert result_limited is None, "Should not find file beyond max_depth limit"

    def test_no_files_found_integration(self) -> None:
        """Integration test for cases where no files are found."""
        # Import locally

        sys.path.insert(0, str(Path(__file__).parent.parent.parent))

        # Create empty shot structure
        shot_path = (
            self.shows_root
            / "empty_test"
            / "shots"
            / "seq01"
            / "seq01_shot01"
            / "publish"
        )
        shot_path.mkdir(parents=True)

        # Should return None when no turnover plates exist
        result1 = ThumbnailFinders.find_turnover_plate_thumbnail(
            str(self.shows_root), "empty_test", "seq01", "shot01"
        )
        assert result1 is None

        # Should return None when no 1001 files exist
        result2 = ThumbnailFinders.find_any_publish_thumbnail(
            str(self.shows_root), "empty_test", "seq01", "shot01", max_depth=5
        )
        assert result2 is None


# Allow running as standalone test
if __name__ == "__main__":
    import shutil
    import tempfile

    standalone_temp = Path(tempfile.mkdtemp(prefix="shotbot_integration_"))
    test = TestThumbnailDiscoveryIntegration()
    test.temp_dir = standalone_temp
    test.shows_root = standalone_temp / "shows"
    test.shows_root.mkdir(parents=True, exist_ok=True)
    test.test_subprocess = TestSubprocess()
    try:
        print("Running turnover plate discovery integration...")
        test.test_turnover_plate_discovery_integration()
        print("✓ Turnover plate discovery passed")

        print("Running plate priority integration...")
        test.test_plate_priority_integration()
        print("✓ Plate priority integration passed")

        print("Running fallback discovery integration...")
        test.test_fallback_discovery_integration()
        print("✓ Fallback discovery integration passed")

        print("Running deep nesting integration...")
        test.test_deep_nesting_integration()
        print("✓ Deep nesting integration passed")

        print("Running no files found integration...")
        test.test_no_files_found_integration()
        print("✓ No files found integration passed")

        print("All integration tests passed!")
    except Exception as e:  # noqa: BLE001
        print(f"Test failed: {e}")

        traceback.print_exc()
    finally:
        shutil.rmtree(standalone_temp, ignore_errors=True)
