"""Integration tests for raw plate finder with real filesystem operations."""

import logging
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from raw_plate_finder import RawPlateFinder
from utils import PathUtils

logger = logging.getLogger(__name__)


class TestRawPlateFinderIntegration:
    """Integration tests for the complete raw plate finding workflow."""

    @pytest.fixture
    def workspace_structure(self):
        """Create a realistic workspace structure with plates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            # Create shot workspace structure
            shot_path = (
                base / "shows" / "testshow" / "shots" / "TST_001" / "TST_001_0010"
            )
            plate_base = shot_path / "publish" / "turnover" / "plate" / "input_plate"

            # Create multiple plate types with different versions
            plates_data = [
                ("FG01", "v001", "lin_sgamut3cine", "4312x2304"),
                ("FG01", "v002", "lin_sgamut3cine", "4312x2304"),
                ("BG01", "v001", "aces", "4042x2274"),
                ("BG02", "v001", "aces", "2021x1137"),
                ("bg01", "v003", "rec709", "1920x1080"),  # lowercase variant
            ]

            created_plates = []
            for plate_name, version, color_space, resolution in plates_data:
                plate_dir = plate_base / plate_name / version / "exr" / resolution
                plate_dir.mkdir(parents=True)

                # Create actual EXR files
                for frame in range(1001, 1011):
                    plate_file = (
                        plate_dir
                        / f"TST_001_0010_turnover-plate_{plate_name}_{color_space}_{version}.{frame:04d}.exr"
                    )
                    plate_file.touch()

                created_plates.append(
                    (plate_name, version, color_space, resolution, plate_dir)
                )

            yield {
                "base": base,
                "shot_path": shot_path,
                "plate_base": plate_base,
                "plates": created_plates,
                "shot_name": "TST_001_0010",
            }

    def test_find_latest_plate_with_priority(self, workspace_structure):
        """Test finding the latest plate respecting priority order."""
        shot_path = str(workspace_structure["shot_path"])
        shot_name = workspace_structure["shot_name"]

        result = RawPlateFinder.find_latest_raw_plate(shot_path, shot_name)

        # Should find BG01 (higher priority than FG01)
        assert result is not None
        assert "BG01" in result
        assert "aces" in result
        assert "v001" in result
        assert "####" in result

    def test_discover_all_plate_directories(self, workspace_structure):
        """Test discovering all available plate directories."""
        plate_base = workspace_structure["plate_base"]

        plates = PathUtils.discover_plate_directories(plate_base)

        # Should find all 5 plate directories
        assert len(plates) == 5

        # Check priority ordering
        plate_names = [p[0] for p in plates]
        assert plate_names[0] == "BG01"  # Highest priority

        # Check that both bg01 and BG01 are found
        assert "bg01" in plate_names
        assert "FG01" in plate_names
        assert "BG02" in plate_names

    def test_color_space_detection(self, workspace_structure):
        """Test automatic color space detection from actual files."""
        # Create a plate with unusual color space
        plate_base = workspace_structure["plate_base"]
        special_plate = plate_base / "FG03" / "v001" / "exr" / "4096x2160"
        special_plate.mkdir(parents=True)

        # Create file with custom color space
        plate_file = (
            special_plate
            / f"{workspace_structure['shot_name']}_turnover-plate_FG03_linear_ap0_v001.1001.exr"
        )
        plate_file.touch()

        result = RawPlateFinder.find_latest_raw_plate(
            str(workspace_structure["shot_path"]), workspace_structure["shot_name"]
        )

        # Should still find a plate (BG01 has priority)
        assert result is not None

    def test_concurrent_plate_discovery(self, workspace_structure):
        """Test concurrent access to plate directories."""
        import threading

        shot_path = str(workspace_structure["shot_path"])
        shot_name = workspace_structure["shot_name"]
        results = []
        errors = []

        def find_plate():
            try:
                result = RawPlateFinder.find_latest_raw_plate(shot_path, shot_name)
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        # Launch multiple threads
        threads = []
        for _ in range(10):
            t = threading.Thread(target=find_plate)
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join(timeout=5.0)

        # All threads should succeed
        assert len(errors) == 0
        assert len(results) == 10
        # All should find the same plate
        assert all(r == results[0] for r in results)

    def test_performance_large_directory(self, workspace_structure):
        """Test performance with large number of files."""
        import time

        # Create many extra files in a plate directory
        plate_dir = workspace_structure["plates"][0][4]  # Get first plate dir
        for frame in range(1001, 2001):  # 1000 frames
            dummy_file = plate_dir / f"extra_file_{frame:04d}.exr"
            dummy_file.touch()

        shot_path = str(workspace_structure["shot_path"])
        shot_name = workspace_structure["shot_name"]

        start_time = time.time()
        result = RawPlateFinder.find_latest_raw_plate(shot_path, shot_name)
        elapsed = time.time() - start_time

        assert result is not None
        # Should complete in reasonable time even with 1000+ files
        assert elapsed < 2.0, f"Took {elapsed:.2f}s, expected < 2.0s"

    def test_missing_permissions_handling(self, workspace_structure, monkeypatch):
        """Test handling of permission errors."""

        def mock_iterdir(self):
            raise PermissionError("Access denied")

        shot_path = str(workspace_structure["shot_path"])
        shot_name = workspace_structure["shot_name"]

        with patch.object(Path, "iterdir", mock_iterdir):
            result = RawPlateFinder.find_latest_raw_plate(shot_path, shot_name)
            # Should handle gracefully
            assert result is None

    def test_plate_verification(self, workspace_structure):
        """Test plate existence verification."""
        # Get a valid plate path
        shot_path = str(workspace_structure["shot_path"])
        shot_name = workspace_structure["shot_name"]

        plate_path = RawPlateFinder.find_latest_raw_plate(shot_path, shot_name)
        assert plate_path is not None

        # Verify the plate exists
        exists = RawPlateFinder.verify_plate_exists(plate_path)
        assert exists is True

        # Test with non-existent plate
        fake_path = plate_path.replace("BG01", "FAKE99")
        exists = RawPlateFinder.verify_plate_exists(fake_path)
        assert exists is False

    def test_version_extraction(self, workspace_structure):
        """Test version extraction from plate paths."""
        shot_path = str(workspace_structure["shot_path"])
        shot_name = workspace_structure["shot_name"]

        plate_path = RawPlateFinder.find_latest_raw_plate(shot_path, shot_name)
        version = RawPlateFinder.get_version_from_path(plate_path)

        assert version in ["v001", "v002", "v003"]

    def test_empty_workspace(self):
        """Test behavior with empty workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = RawPlateFinder.find_latest_raw_plate(tmpdir, "TEST_SHOT")
            assert result is None

    def test_real_world_plate_structures(self):
        """Test with various real-world plate naming conventions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            shot_name = "PROD_042_1337"

            # Create various real-world naming patterns
            patterns = [
                # Standard VFX pattern
                ("FG01", "lin_sgamut3cine", "v001"),
                # Alternative naming
                ("plate", "aces", "v001"),
                # Numbered plates
                ("FG02", "rec709", "v001"),
                # Mixed case
                ("Bg01", "linear", "v001"),
            ]

            shot_path = base / "shots" / shot_name
            plate_base = shot_path / "publish" / "turnover" / "plate" / "input_plate"

            for plate_name, color_space, version in patterns:
                plate_dir = plate_base / plate_name / version / "exr" / "4096x2160"
                plate_dir.mkdir(parents=True)

                # Create plate file
                plate_file = (
                    plate_dir
                    / f"{shot_name}_turnover-plate_{plate_name}_{color_space}_{version}.1001.exr"
                )
                plate_file.touch()

            # Test discovery
            plates = PathUtils.discover_plate_directories(plate_base)
            assert len(plates) >= 3  # Should find at least FG01, FG02, Bg01

            # Test finding
            result = RawPlateFinder.find_latest_raw_plate(str(shot_path), shot_name)
            assert result is not None
