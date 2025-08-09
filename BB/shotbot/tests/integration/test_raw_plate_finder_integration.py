"""Comprehensive integration tests for Raw Plate Finder workflow."""

import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from config import Config
from raw_plate_finder import RawPlateFinder
from shot_model import Shot


class TestRawPlateFinderIntegration:
    """Integration tests for complete raw plate finder workflow."""

    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace structure for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            yield workspace

    @pytest.fixture
    def mock_plate_structure_complex(self, temp_workspace):
        """Create complex mock plate structure with multiple options."""
        shot_path = (
            temp_workspace / "shows" / "testshow" / "shots" / "108_CHV" / "108_CHV_0015"
        )
        plate_base = shot_path / "sourceimages" / "plates"

        # Create FG01 plates with multiple versions and color spaces
        fg01_v001 = plate_base / "FG01" / "v001" / "exr" / "4312x2304"
        fg01_v001.mkdir(parents=True)
        fg01_v002 = plate_base / "FG01" / "v002" / "exr" / "4312x2304"
        fg01_v002.mkdir(parents=True)

        # Create BG01 plates
        bg01_v001 = plate_base / "BG01" / "v001" / "exr" / "2048x1152"
        bg01_v001.mkdir(parents=True)

        # Create plates with different color spaces
        test_files = [
            # FG01 v001 - aces color space
            (
                fg01_v001 / "108_CHV_0015_turnover-plate_FG01_aces_v001.1001.exr",
                "FG01",
                "v001",
                "aces",
            ),
            (
                fg01_v001 / "108_CHV_0015_turnover-plate_FG01_aces_v001.1002.exr",
                "FG01",
                "v001",
                "aces",
            ),
            # FG01 v002 - lin_sgamut3cine color space
            (
                fg01_v002
                / "108_CHV_0015_turnover-plate_FG01_lin_sgamut3cine_v002.1001.exr",
                "FG01",
                "v002",
                "lin_sgamut3cine",
            ),
            (
                fg01_v002
                / "108_CHV_0015_turnover-plate_FG01_lin_sgamut3cine_v002.1002.exr",
                "FG01",
                "v002",
                "lin_sgamut3cine",
            ),
            # BG01 v001 - alternative pattern without underscore before color space
            (
                bg01_v001 / "108_CHV_0015_turnover-plate_BG01aces_v001.1001.exr",
                "BG01",
                "v001",
                "aces",
            ),
            (
                bg01_v001 / "108_CHV_0015_turnover-plate_BG01aces_v001.1002.exr",
                "BG01",
                "v001",
                "aces",
            ),
        ]

        for file_path, plate, version, color_space in test_files:
            file_path.touch()

        return {
            "shot_workspace_path": str(shot_path),
            "shot_name": "108_CHV_0015",
            "plate_base": plate_base,
            "test_files": test_files,
            "expected_latest": {
                "FG01": {
                    "version": "v002",
                    "color_space": "lin_sgamut3cine",
                    "resolution": "4312x2304",
                },
                "BG01": {
                    "version": "v001",
                    "color_space": "aces",
                    "resolution": "2048x1152",
                },
            },
        }

    @pytest.fixture
    def mock_plate_structure_simple(self, temp_workspace):
        """Create simple mock plate structure for basic testing."""
        shot_path = (
            temp_workspace
            / "shows"
            / "simpleshow"
            / "shots"
            / "001_TST"
            / "001_TST_0001"
        )
        plate_base = shot_path / "sourceimages" / "plates"

        # Simple FG01 structure
        fg01_dir = plate_base / "FG01" / "v001" / "exr" / "1920x1080"
        fg01_dir.mkdir(parents=True)

        # Create test files
        (fg01_dir / "001_TST_0001_turnover-plate_FG01_aces_v001.1001.exr").touch()
        (fg01_dir / "001_TST_0001_turnover-plate_FG01_aces_v001.1002.exr").touch()

        return {
            "shot_workspace_path": str(shot_path),
            "shot_name": "001_TST_0001",
            "expected_pattern": "001_TST_0001_turnover-plate_FG01_aces_v001.####.exr",
        }

    def test_full_workflow_complex_structure(self, mock_plate_structure_complex):
        """Test complete workflow with complex plate structure."""
        shot_workspace_path = mock_plate_structure_complex["shot_workspace_path"]
        shot_name = mock_plate_structure_complex["shot_name"]

        # Find latest raw plate - should prioritize FG01 over BG01
        latest_plate = RawPlateFinder.find_latest_raw_plate(
            shot_workspace_path, shot_name
        )

        assert latest_plate is not None
        assert "FG01" in latest_plate
        assert "v002" in latest_plate  # Latest version
        assert "lin_sgamut3cine" in latest_plate  # Correct color space
        assert "####" in latest_plate  # Frame pattern
        assert latest_plate.endswith(".exr")

        # Verify the constructed path
        expected_pattern = (
            f"{shot_name}_turnover-plate_FG01_lin_sgamut3cine_v002.####.exr"
        )
        assert latest_plate.endswith(expected_pattern)

    def test_plate_priority_selection(self, mock_plate_structure_complex):
        """Test that plates are selected by priority (FG01 > BG01)."""
        shot_workspace_path = mock_plate_structure_complex["shot_workspace_path"]
        shot_name = mock_plate_structure_complex["shot_name"]

        # Should find FG01 even though BG01 exists
        latest_plate = RawPlateFinder.find_latest_raw_plate(
            shot_workspace_path, shot_name
        )

        assert latest_plate is not None
        assert "FG01" in latest_plate
        assert "BG01" not in latest_plate

    def test_version_selection_workflow(self, mock_plate_structure_complex):
        """Test version selection chooses latest version correctly."""
        shot_workspace_path = mock_plate_structure_complex["shot_workspace_path"]
        shot_name = mock_plate_structure_complex["shot_name"]

        latest_plate = RawPlateFinder.find_latest_raw_plate(
            shot_workspace_path, shot_name
        )

        # Should select v002 over v001
        assert latest_plate is not None
        assert "v002" in latest_plate
        assert "v001" not in latest_plate

    def test_color_space_detection_workflow(self, mock_plate_structure_complex):
        """Test color space detection from actual files."""
        shot_workspace_path = mock_plate_structure_complex["shot_workspace_path"]
        shot_name = mock_plate_structure_complex["shot_name"]

        latest_plate = RawPlateFinder.find_latest_raw_plate(
            shot_workspace_path, shot_name
        )

        # Should detect lin_sgamut3cine from v002 files
        assert latest_plate is not None
        assert "lin_sgamut3cine" in latest_plate

    def test_alternative_naming_pattern(self, temp_workspace):
        """Test handling of alternative naming pattern without underscore before color space."""
        shot_path = temp_workspace / "shows" / "altshow" / "shots" / "SEQ" / "SEQ_0001"
        plate_base = shot_path / "sourceimages" / "plates"

        # Create BG01 with alternative pattern
        bg01_dir = plate_base / "BG01" / "v001" / "exr" / "1920x1080"
        bg01_dir.mkdir(parents=True)

        # Alternative pattern: no underscore before color space
        (bg01_dir / "SEQ_0001_turnover-plate_BG01aces_v001.1001.exr").touch()
        (bg01_dir / "SEQ_0001_turnover-plate_BG01aces_v001.1002.exr").touch()

        # Test discovery
        latest_plate = RawPlateFinder.find_latest_raw_plate(str(shot_path), "SEQ_0001")

        assert latest_plate is not None
        assert "BG01aces" in latest_plate  # Should detect pattern without underscore
        assert "####" in latest_plate

    def test_plate_verification_workflow(self, mock_plate_structure_simple):
        """Test plate verification for found patterns."""
        shot_workspace_path = mock_plate_structure_simple["shot_workspace_path"]
        shot_name = mock_plate_structure_simple["shot_name"]

        # Find plate
        latest_plate = RawPlateFinder.find_latest_raw_plate(
            shot_workspace_path, shot_name
        )
        assert latest_plate is not None

        # Verify it exists
        exists = RawPlateFinder.verify_plate_exists(latest_plate)
        assert exists is True

    def test_version_extraction_workflow(self, mock_plate_structure_simple):
        """Test version extraction from found plate paths."""
        shot_workspace_path = mock_plate_structure_simple["shot_workspace_path"]
        shot_name = mock_plate_structure_simple["shot_name"]

        latest_plate = RawPlateFinder.find_latest_raw_plate(
            shot_workspace_path, shot_name
        )
        assert latest_plate is not None

        # Extract version
        version = RawPlateFinder.get_version_from_path(latest_plate)
        assert version == "v001"

    def test_missing_directories_handling(self, temp_workspace):
        """Test handling of missing directory structures."""
        # Non-existent shot path
        fake_path = str(temp_workspace / "nonexistent" / "shot" / "path")

        result = RawPlateFinder.find_latest_raw_plate(fake_path, "FAKE_0001")
        assert result is None

    def test_empty_directories_handling(self, temp_workspace):
        """Test handling of empty directory structures."""
        shot_path = (
            temp_workspace / "shows" / "emptyshow" / "shots" / "EMPTY" / "EMPTY_0001"
        )
        plate_base = shot_path / "sourceimages" / "plates"

        # Create directories but no files
        plate_base.mkdir(parents=True)

        result = RawPlateFinder.find_latest_raw_plate(str(shot_path), "EMPTY_0001")
        assert result is None

    def test_permission_error_handling(self, temp_workspace, monkeypatch):
        """Test handling of permission errors during scanning."""
        shot_path = (
            temp_workspace / "shows" / "permtest" / "shots" / "PERM" / "PERM_0001"
        )

        # Mock PathUtils.validate_path_exists to simulate permission error
        with patch("raw_plate_finder.PathUtils.validate_path_exists") as mock_validate:
            mock_validate.return_value = False  # Simulate access failure

            result = RawPlateFinder.find_latest_raw_plate(str(shot_path), "PERM_0001")
            assert result is None

    def test_multiple_resolution_directories(self, temp_workspace):
        """Test handling when multiple resolution directories exist."""
        shot_path = temp_workspace / "shows" / "multirez" / "shots" / "MR" / "MR_0001"
        plate_base = shot_path / "sourceimages" / "plates"

        # Create FG01 with multiple resolutions
        fg01_base = plate_base / "FG01" / "v001" / "exr"

        # Multiple resolution directories
        res1 = fg01_base / "1920x1080"
        res2 = fg01_base / "3840x2160"
        res1.mkdir(parents=True)
        res2.mkdir(parents=True)

        # Add files to first resolution only
        (res1 / "MR_0001_turnover-plate_FG01_aces_v001.1001.exr").touch()
        (res1 / "MR_0001_turnover-plate_FG01_aces_v001.1002.exr").touch()

        # Should find plates using first resolution directory
        result = RawPlateFinder.find_latest_raw_plate(str(shot_path), "MR_0001")
        assert result is not None
        assert "1920x1080" in result or "3840x2160" in result  # Should pick one of them

    def test_fallback_color_space_detection(self, temp_workspace):
        """Test fallback color space detection when no files match patterns."""
        shot_path = temp_workspace / "shows" / "fallback" / "shots" / "FB" / "FB_0001"
        plate_base = shot_path / "sourceimages" / "plates"

        fg01_dir = plate_base / "FG01" / "v001" / "exr" / "1920x1080"
        fg01_dir.mkdir(parents=True)

        # Create file that matches fallback pattern
        fallback_file = fg01_dir / "FB_0001_turnover-plate_FG01_aces_v001.1001.exr"
        fallback_file.touch()

        # Mock Config.COLOR_SPACE_PATTERNS to include "aces"
        with patch.object(Config, "COLOR_SPACE_PATTERNS", ["aces", "lin_sgamut3cine"]):
            result = RawPlateFinder.find_latest_raw_plate(str(shot_path), "FB_0001")

        assert result is not None
        assert "aces" in result

    @pytest.mark.performance
    def test_performance_large_directory_structure(self, temp_workspace):
        """Performance test with large directory structure."""
        shot_path = (
            temp_workspace / "shows" / "perftest" / "shots" / "PERF" / "PERF_0001"
        )
        plate_base = shot_path / "sourceimages" / "plates"

        # Create large structure with many plates and versions
        plates = ["FG01", "BG01", "BG02", "BG03", "COMP"]
        versions = [f"v{i:03d}" for i in range(1, 21)]  # v001 to v020

        for plate in plates:
            for version in versions:
                plate_dir = plate_base / plate / version / "exr" / "4096x2304"
                plate_dir.mkdir(parents=True)

                # Only add files to latest version of FG01 to test performance
                if plate == "FG01" and version == "v020":
                    for frame in range(1001, 1011):  # 10 frames
                        file_path = (
                            plate_dir
                            / f"PERF_0001_turnover-plate_FG01_aces_{version}.{frame}.exr"
                        )
                        file_path.touch()

        # Time the operation
        start_time = time.time()
        result = RawPlateFinder.find_latest_raw_plate(str(shot_path), "PERF_0001")
        end_time = time.time()

        # Should complete quickly even with large structure
        assert (end_time - start_time) < 1.0  # Should complete in under 1 second
        assert result is not None
        assert "v020" in result  # Should find latest version
        assert "FG01" in result  # Should prioritize FG01

    def test_concurrent_access_simulation(self, mock_plate_structure_complex):
        """Test behavior when multiple processes might access the same directories."""
        from concurrent.futures import ThreadPoolExecutor

        shot_workspace_path = mock_plate_structure_complex["shot_workspace_path"]
        shot_name = mock_plate_structure_complex["shot_name"]

        results = []
        errors = []

        def find_plate_worker():
            try:
                result = RawPlateFinder.find_latest_raw_plate(
                    shot_workspace_path, shot_name
                )
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Run multiple workers concurrently
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(find_plate_worker) for _ in range(10)]

            # Wait for completion
            for future in futures:
                future.result(timeout=5.0)

        # All should succeed with same result
        assert len(errors) == 0
        assert len(results) == 10
        assert all(r == results[0] for r in results)  # All results should be identical

    def test_integration_with_shot_model(self, mock_plate_structure_simple):
        """Test integration between RawPlateFinder and Shot model."""
        shot_workspace_path = mock_plate_structure_simple["shot_workspace_path"]
        shot_name = mock_plate_structure_simple["shot_name"]

        # Create shot object
        shot = Shot("simpleshow", "001_TST", "0001", shot_workspace_path)

        # Use RawPlateFinder to get plate for shot
        plate_path = RawPlateFinder.find_latest_raw_plate(
            shot.workspace_path, shot.full_name
        )

        assert plate_path is not None
        assert shot.full_name in plate_path

        # Verify plate exists
        assert RawPlateFinder.verify_plate_exists(plate_path)

    def test_edge_case_very_long_paths(self, temp_workspace):
        """Test handling of very long file paths."""
        # Create nested directory structure
        shot_path = (
            temp_workspace
            / "shows"
            / "verylongshowname"
            / "shots"
            / "VERYLONGSEQUENCENAME"
            / "VERYLONGSEQUENCENAME_0001"
        )
        plate_base = shot_path / "sourceimages" / "plates"

        very_long_plate_dir = (
            plate_base / "VERYLONGPLATENAME" / "v001" / "exr" / "7680x4320"
        )
        very_long_plate_dir.mkdir(parents=True)

        # Create file with very long name
        long_filename = "VERYLONGSEQUENCENAME_0001_turnover-plate_VERYLONGPLATENAME_verylongcolorspacename_v001.1001.exr"
        (very_long_plate_dir / long_filename).touch()

        result = RawPlateFinder.find_latest_raw_plate(
            str(shot_path), "VERYLONGSEQUENCENAME_0001"
        )

        # Should handle long paths gracefully
        assert result is not None
        assert len(result) > 200  # Verify we got a long path
        assert "VERYLONGPLATENAME" in result

    def test_case_insensitive_matching(self, temp_workspace):
        """Test case-insensitive pattern matching."""
        shot_path = (
            temp_workspace / "shows" / "casetest" / "shots" / "CASE" / "CASE_0001"
        )
        plate_base = shot_path / "sourceimages" / "plates"

        fg01_dir = (
            plate_base / "fg01" / "V001" / "EXR" / "1920x1080"
        )  # Mixed case directories
        fg01_dir.mkdir(parents=True)

        # Mixed case filename
        (fg01_dir / "case_0001_turnover-plate_FG01_ACES_V001.1001.EXR").touch()

        result = RawPlateFinder.find_latest_raw_plate(str(shot_path), "CASE_0001")

        # Should find despite case differences
        assert result is not None
        assert "fg01" in result.lower() or "FG01" in result


class TestRawPlateFinderStressTests:
    """Stress tests for RawPlateFinder under heavy load."""

    @pytest.mark.stress
    def test_stress_many_concurrent_requests(self, temp_workspace):
        """Stress test with many concurrent plate finder requests."""
        from concurrent.futures import ThreadPoolExecutor

        # Create multiple shot structures
        shots_data = []
        for i in range(20):  # 20 different shots
            shot_path = (
                temp_workspace
                / "shows"
                / f"show{i}"
                / "shots"
                / f"SEQ{i:03d}"
                / f"SEQ{i:03d}_0001"
            )
            plate_base = shot_path / "sourceimages" / "plates"

            fg01_dir = plate_base / "FG01" / "v001" / "exr" / "1920x1080"
            fg01_dir.mkdir(parents=True)

            shot_name = f"SEQ{i:03d}_0001"
            (fg01_dir / f"{shot_name}_turnover-plate_FG01_aces_v001.1001.exr").touch()
            (fg01_dir / f"{shot_name}_turnover-plate_FG01_aces_v001.1002.exr").touch()

            shots_data.append((str(shot_path), shot_name))

        results = []
        errors = []

        def stress_worker(shot_data):
            shot_path, shot_name = shot_data
            try:
                # Make multiple requests per worker
                for _ in range(5):
                    result = RawPlateFinder.find_latest_raw_plate(shot_path, shot_name)
                    results.append(result)
            except Exception as e:
                errors.append(e)

        # Run with high concurrency
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(stress_worker, shot_data) for shot_data in shots_data
            ]

            for future in futures:
                future.result(timeout=10.0)

        end_time = time.time()

        # Should complete all requests without errors
        assert len(errors) == 0
        assert len(results) == 20 * 5  # 20 shots × 5 requests each
        assert all(r is not None for r in results)  # All should find plates

        # Should complete in reasonable time even under stress
        assert (end_time - start_time) < 5.0  # Should complete within 5 seconds

    @pytest.mark.stress
    def test_stress_memory_usage_large_structures(self, temp_workspace):
        """Test memory usage doesn't grow excessively with large directory structures."""
        import os

        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        # Create very large directory structure
        shot_path = temp_workspace / "shows" / "memtest" / "shots" / "MEM" / "MEM_0001"
        plate_base = shot_path / "sourceimages" / "plates"

        # Create many plate directories
        for plate_num in range(50):  # 50 plates
            for version_num in range(10):  # 10 versions each
                plate_name = f"PLATE{plate_num:02d}"
                version = f"v{version_num:03d}"

                plate_dir = plate_base / plate_name / version / "exr" / "4096x2304"
                plate_dir.mkdir(parents=True)

                # Only add actual files to the last plate/version to test memory usage
                if plate_num == 49 and version_num == 9:
                    for frame in range(1001, 1101):  # 100 frames
                        file_path = (
                            plate_dir
                            / f"MEM_0001_turnover-plate_{plate_name}_aces_{version}.{frame}.exr"
                        )
                        file_path.touch()

        # Perform multiple searches
        for _ in range(10):
            result = RawPlateFinder.find_latest_raw_plate(str(shot_path), "MEM_0001")

        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory

        # Memory increase should be reasonable (less than 100MB)
        assert memory_increase < 100 * 1024 * 1024  # 100MB
        assert result is not None  # Should still find result
