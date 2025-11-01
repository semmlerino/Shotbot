"""Integration tests for type safety across the entire system."""

# pyright: basic
# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cache_manager import CacheManager
from raw_plate_finder import RawPlateFinder
from shot_model import RefreshResult, Shot, ShotModel
from utils import FileUtils, PathUtils, ValidationUtils, VersionUtils


class TestEndToEndTypeSafety:
    """Test type safety across the entire application workflow."""

    def test_complete_shot_workflow_types(self, qtbot, tmp_path):
        """Test complete shot workflow maintains type safety."""
        # Setup cache manager with temporary directory
        cache = CacheManager(cache_dir=tmp_path)
        # CacheManager is QObject, not QWidget, so no need to add to qtbot

        # Setup shot model
        model = ShotModel(cache_manager=cache, load_cache=False)

        # Mock subprocess for ws command
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = """
        workspace /shows/test_show/shots/seq_001/seq_001_shot_001
        workspace /shows/test_show/shots/seq_001/seq_001_shot_002
        workspace /shows/test_show/shots/seq_002/seq_002_shot_001
        """
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            # Refresh shots
            refresh_result = model.refresh_shots()

            # Verify RefreshResult type
            assert isinstance(refresh_result, RefreshResult)
            assert isinstance(refresh_result.success, bool)
            assert isinstance(refresh_result.has_changes, bool)
            assert refresh_result.success is True

            # Verify shot list types
            assert isinstance(model.shots, list)
            assert len(model.shots) == 3

            for shot in model.shots:
                # Verify Shot type and attributes
                assert isinstance(shot, Shot)
                assert isinstance(shot.show, str)
                assert isinstance(shot.sequence, str)
                assert isinstance(shot.shot, str)
                assert isinstance(shot.workspace_path, str)

                # Verify properties
                full_name = shot.full_name
                assert isinstance(full_name, str)
                assert "_" in full_name  # Should be sequence_shot format

                thumb_dir = shot.thumbnail_dir
                assert isinstance(thumb_dir, Path)

                # Verify serialization
                shot_dict = shot.to_dict()
                assert isinstance(shot_dict, dict)
                for key, value in shot_dict.items():
                    assert isinstance(key, str)
                    assert isinstance(value, str)

                # Verify deserialization
                recreated_shot = Shot.from_dict(shot_dict)
                assert isinstance(recreated_shot, Shot)
                assert recreated_shot.show == shot.show
                assert recreated_shot.sequence == shot.sequence
                assert recreated_shot.shot == shot.shot
                assert recreated_shot.workspace_path == shot.workspace_path

    def test_cache_integration_types(self, qtbot, tmp_path):
        """Test cache integration maintains type safety."""
        cache = CacheManager(cache_dir=tmp_path)
        # CacheManager is QObject, not QWidget

        # Create test shots
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq2", "shot2", "/path2"),
            Shot("show3", "seq3", "shot3", "/path3"),
        ]

        # Cache the shots
        cache.cache_shots(shots)

        # Retrieve from cache
        cached_data = cache.get_cached_shots()
        assert cached_data is not None
        assert isinstance(cached_data, list)
        assert len(cached_data) == 3

        # Verify cached data types
        for shot_data in cached_data:
            assert isinstance(shot_data, dict)
            for key, value in shot_data.items():
                assert isinstance(key, str)
                assert isinstance(value, str)

        # Recreate shots from cache
        recreated_shots = [Shot.from_dict(shot_data) for shot_data in cached_data]

        # Verify recreated shots
        assert len(recreated_shots) == len(shots)
        for orig, recreated in zip(shots, recreated_shots):
            assert isinstance(recreated, Shot)
            assert orig.show == recreated.show
            assert orig.sequence == recreated.sequence
            assert orig.shot == recreated.shot
            assert orig.workspace_path == recreated.workspace_path

        # Test memory usage stats
        memory_stats = cache.get_memory_usage()
        assert isinstance(memory_stats, dict)

        expected_keys = [
            "total_bytes",
            "total_mb",
            "max_mb",
            "usage_percent",
            "thumbnail_count",
        ]
        for key in expected_keys:
            assert key in memory_stats
            value = memory_stats[key]
            if key in ["total_bytes", "thumbnail_count"]:
                assert isinstance(value, int)
            else:
                assert isinstance(value, float)

    def test_raw_plate_finder_integration_types(self, tmp_path, monkeypatch):
        """Test RawPlateFinder integration maintains type safety using real workspace structure."""
        # Create realistic workspace directory structure
        workspace_path = tmp_path / "shows" / "test_show" / "shots" / "seq" / "shot"
        workspace_path.mkdir(parents=True)

        shot_name = "seq_shot"

        # Create real plate directory structure matching what RawPlateFinder expects
        # workspace_path / "publish" / "turnover" / "plate" / "input_plate" / "BG01" / "v001" / "exr" / "4096x2304"
        raw_plate_base = (
            workspace_path / "publish" / "turnover" / "plate" / "input_plate"
        )
        bg_plate_dir = raw_plate_base / "BG01" / "v001" / "exr" / "4096x2304"
        bg_plate_dir.mkdir(parents=True)

        # Create test plate file with proper naming
        test_plate = (
            bg_plate_dir / f"{shot_name}_turnover-plate_BG01_aces_v001.1001.exr"
        )
        test_plate.touch()

        # Also create a few more frames to make it realistic
        for frame in range(1002, 1005):
            frame_file = (
                bg_plate_dir
                / f"{shot_name}_turnover-plate_BG01_aces_v001.{frame:04d}.exr"
            )
            frame_file.touch()

        # Use REAL PathUtils methods - no mocking needed since we have real structure
        # Find plate using real workspace path
        result = RawPlateFinder.find_latest_raw_plate(str(workspace_path), shot_name)

        # Verify return type
        assert isinstance(result, (str, type(None)))
        if result is not None:
            assert isinstance(result, str)
            assert "####" in result
            assert result.endswith(".exr")

        # Test version extraction
        if result:
            version = RawPlateFinder.get_version_from_path(result)
            assert isinstance(version, (str, type(None)))
            if version:
                assert isinstance(version, str)
                assert version.startswith("v")

        # Test plate verification
        if result:
            exists = RawPlateFinder.verify_plate_exists(result)
            assert isinstance(exists, bool)

    def test_utils_integration_types(self, tmp_path):
        """Test utils module integration maintains type safety."""
        # Test PathUtils
        base_path = tmp_path / "base"
        result_path = PathUtils.build_path(base_path, "seg1", "seg2", "seg3")
        assert isinstance(result_path, Path)
        assert str(result_path).endswith("seg3")

        # Test path validation
        exists_result = PathUtils.validate_path_exists(tmp_path, "Test directory")
        assert isinstance(exists_result, bool)
        assert exists_result is True

        # Test batch validation
        paths_to_check = [tmp_path, tmp_path / "nonexistent", Path("/also/nonexistent")]
        batch_results = PathUtils.batch_validate_paths(paths_to_check)
        assert isinstance(batch_results, dict)
        for path_str, exists in batch_results.items():
            assert isinstance(path_str, str)
            assert isinstance(exists, bool)

        # Test VersionUtils
        version_dirs = VersionUtils.find_version_directories(tmp_path)
        assert isinstance(version_dirs, list)
        for version_num, version_str in version_dirs:
            assert isinstance(version_num, int)
            assert isinstance(version_str, str)

        # Test FileUtils
        image_files = FileUtils.find_files_by_extension(
            tmp_path, ["jpg", "png"], limit=5
        )
        assert isinstance(image_files, list)
        for file_path in image_files:
            assert isinstance(file_path, Path)

        first_image = FileUtils.get_first_image_file(tmp_path)
        assert isinstance(first_image, (Path, type(None)))

        # Test ValidationUtils
        validation_result = ValidationUtils.validate_not_empty(
            "test1", "test2", "test3"
        )
        assert isinstance(validation_result, bool)

        username = ValidationUtils.get_current_username()
        assert isinstance(username, str)
        assert len(username) > 0

        excluded_users = ValidationUtils.get_excluded_users()
        assert isinstance(excluded_users, set)
        for user in excluded_users:
            assert isinstance(user, str)

    def test_error_propagation_types(self, qtbot, tmp_path, monkeypatch):
        """Test that errors maintain type safety throughout propagation."""
        cache = CacheManager(cache_dir=tmp_path)
        # CacheManager is a QObject, not QWidget - don't need to add to qtbot for error propagation testing
        model = ShotModel(cache_manager=cache, load_cache=False)

        # Test various error scenarios
        error_scenarios = [
            (FileNotFoundError("Command not found"), "FileNotFoundError"),
            (PermissionError("Permission denied"), "PermissionError"),
            (TimeoutError("Operation timed out"), "TimeoutError"),
            (ValueError("Invalid data"), "ValueError"),
            (RuntimeError("Generic runtime error"), "RuntimeError"),
        ]

        for error, error_name in error_scenarios:
            with patch("subprocess.run", side_effect=error):
                result = model.refresh_shots()

                # Should always return RefreshResult with correct types
                assert isinstance(result, RefreshResult), f"Wrong type for {error_name}"
                assert isinstance(result.success, bool), (
                    f"Wrong success type for {error_name}"
                )
                assert isinstance(result.has_changes, bool), (
                    f"Wrong has_changes type for {error_name}"
                )
                assert result.success is False, f"Should be False for {error_name}"
                assert result.has_changes is False, f"Should be False for {error_name}"

                # Model state should remain type-safe
                assert isinstance(model.shots, list), (
                    f"Wrong shots type for {error_name}"
                )

    def test_json_serialization_roundtrip_types(self, qtbot, tmp_path):
        """Test JSON serialization roundtrip maintains types."""
        cache = CacheManager(cache_dir=tmp_path)
        # CacheManager is QObject, not QWidget

        # Create complex shot data
        original_shots = [
            Shot(
                "show_with_underscores",
                "seq_001_special",
                "shot_001",
                "/complex/path/with/spaces",
            ),
            Shot("UPPERCASE", "lowercase", "MiXeD", "/another/path"),
            Shot("numbers123", "456_seq", "789", "/path/with/123/numbers"),
        ]

        # Cache shots (involves JSON serialization)
        cache.cache_shots(original_shots)

        # Read back (involves JSON deserialization)
        cached_data = cache.get_cached_shots()
        assert cached_data is not None
        assert isinstance(cached_data, list)

        # Verify all data maintains string types after JSON roundtrip
        for shot_data in cached_data:
            assert isinstance(shot_data, dict)
            for key, value in shot_data.items():
                assert isinstance(key, str)
                assert isinstance(value, str)

        # Recreate Shot objects
        recreated_shots = [Shot.from_dict(shot_data) for shot_data in cached_data]

        # Verify complete type integrity after roundtrip
        assert len(recreated_shots) == len(original_shots)
        for original, recreated in zip(original_shots, recreated_shots):
            assert isinstance(recreated, Shot)
            assert isinstance(recreated.show, str)
            assert isinstance(recreated.sequence, str)
            assert isinstance(recreated.shot, str)
            assert isinstance(recreated.workspace_path, str)

            # Verify data integrity
            assert recreated.show == original.show
            assert recreated.sequence == original.sequence
            assert recreated.shot == original.shot
            assert recreated.workspace_path == original.workspace_path

            # Verify properties work correctly
            assert isinstance(recreated.full_name, str)
            assert isinstance(recreated.thumbnail_dir, Path)
            assert recreated.full_name == original.full_name

    def test_concurrent_operations_type_safety(self, qtbot, tmp_path):
        """Test that concurrent operations maintain type safety."""
        cache = CacheManager(cache_dir=tmp_path)
        # CacheManager is QObject, not QWidget

        # Create multiple shot models sharing the cache
        model1 = ShotModel(cache_manager=cache, load_cache=False)
        model2 = ShotModel(cache_manager=cache, load_cache=False)

        # Simulate concurrent operations
        shots1 = [Shot("show1", "seq1", f"shot{i}", f"/path1/{i}") for i in range(5)]
        shots2 = [Shot("show2", "seq2", f"shot{i}", f"/path2/{i}") for i in range(3)]

        # Cache from both models
        cache.cache_shots(shots1)
        model1.shots = shots1

        cache.cache_shots(shots2)
        model2.shots = shots2

        # Verify both models maintain type safety
        for model in [model1, model2]:
            assert isinstance(model.shots, list)
            for shot in model.shots:
                assert isinstance(shot, Shot)
                assert isinstance(shot.show, str)
                assert isinstance(shot.sequence, str)
                assert isinstance(shot.shot, str)
                assert isinstance(shot.workspace_path, str)

        # Test cache retrieval maintains types
        cached_shots = cache.get_cached_shots()
        assert cached_shots is not None
        assert isinstance(cached_shots, list)

        for shot_data in cached_shots:
            assert isinstance(shot_data, dict)
            for key, value in shot_data.items():
                assert isinstance(key, str)
                assert isinstance(value, str)

        # Memory usage should still be typed correctly
        memory_stats = cache.get_memory_usage()
        assert isinstance(memory_stats, dict)
        assert isinstance(memory_stats["total_bytes"], int)
        assert isinstance(memory_stats["total_mb"], float)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
