"""Comprehensive type safety tests for ShotBot."""

# pyright: basic
# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import Signal

from cache_manager import CacheManager
from shot_model import RefreshResult, Shot, ShotModel
from utils import (
    FileUtils,
    PathUtils,
    ValidationUtils,
    VersionUtils,
    get_cache_stats,
)


class TypeSafetyTests:
    """Base class for type safety testing patterns."""

    @staticmethod
    def assert_type_match(value: Any, expected_type: type, message: str = "") -> None:
        """Assert that a value matches the expected type at runtime."""
        if not isinstance(value, expected_type):
            raise AssertionError(
                f"{message}: Expected {expected_type.__name__}, got {type(value).__name__}: {value}"
            )

    @staticmethod
    def assert_optional_type(
        value: Any, expected_type: type, allow_none: bool = True
    ) -> None:
        """Assert that an Optional type is handled correctly."""
        if value is None:
            if not allow_none:
                raise AssertionError(
                    f"None value not allowed, expected {expected_type.__name__}"
                )
        else:
            TypeSafetyTests.assert_type_match(value, expected_type)


class TestRefreshResultTypeAnnotations:
    """Test RefreshResult NamedTuple type annotations and behavior."""

    def test_refresh_result_creation(self):
        """Test that RefreshResult NamedTuple works correctly with type annotations."""
        # Test basic creation
        result = RefreshResult(success=True, has_changes=False)

        # Runtime type checks
        TypeSafetyTests.assert_type_match(result.success, bool, "success field")
        TypeSafetyTests.assert_type_match(result.has_changes, bool, "has_changes field")

        # Test access patterns
        assert result.success is True
        assert result.has_changes is False

        # Test tuple unpacking (NamedTuple should support this)
        success, has_changes = result
        assert success is True
        assert has_changes is False

    def test_refresh_result_field_types(self):
        """Test RefreshResult field types are enforced at creation."""
        # Valid types
        result1 = RefreshResult(True, True)
        result2 = RefreshResult(False, False)

        assert isinstance(result1.success, bool)
        assert isinstance(result1.has_changes, bool)
        assert isinstance(result2.success, bool)
        assert isinstance(result2.has_changes, bool)

    def test_refresh_result_immutability(self):
        """Test that RefreshResult is immutable like other NamedTuples."""
        result = RefreshResult(True, False)

        # NamedTuple should be immutable
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]

    def test_refresh_result_serialization(self):
        """Test RefreshResult can be serialized/deserialized correctly."""
        original = RefreshResult(success=True, has_changes=True)

        # Convert to dict (NamedTuple has _asdict method)
        as_dict = original._asdict()
        TypeSafetyTests.assert_type_match(as_dict, dict)

        # Verify dict contents
        assert as_dict["success"] is True
        assert as_dict["has_changes"] is True

        # Reconstruct from dict
        reconstructed = RefreshResult(**as_dict)
        assert reconstructed == original


class TestShotModelTypeAnnotations:
    """Test Shot and ShotModel type annotations."""

    def test_shot_dataclass_type_safety(self):
        """Test Shot dataclass field types are enforced."""
        shot = Shot(
            show="test_show",
            sequence="seq_001",
            shot="shot_001",
            workspace_path="/path/to/workspace",
        )

        # Test all fields are strings as annotated
        TypeSafetyTests.assert_type_match(shot.show, str, "show field")
        TypeSafetyTests.assert_type_match(shot.sequence, str, "sequence field")
        TypeSafetyTests.assert_type_match(shot.shot, str, "shot field")
        TypeSafetyTests.assert_type_match(
            shot.workspace_path, str, "workspace_path field"
        )

    def test_shot_property_return_types(self):
        """Test that Shot property methods return correct types."""
        shot = Shot("show", "seq", "shot", "/workspace")

        # full_name should return str
        full_name = shot.full_name
        TypeSafetyTests.assert_type_match(full_name, str, "full_name property")

        # thumbnail_dir should return Path
        thumb_dir = shot.thumbnail_dir
        TypeSafetyTests.assert_type_match(thumb_dir, Path, "thumbnail_dir property")

    def test_shot_get_thumbnail_path_return_type(self, monkeypatch):
        """Test get_thumbnail_path returns Optional[Path]."""
        shot = Shot("show", "seq", "shot", "/workspace")

        # Mock PathUtils.validate_path_exists to return False (no thumbnail dir)
        monkeypatch.setattr(PathUtils, "validate_path_exists", lambda *args: False)

        result = shot.get_thumbnail_path()
        TypeSafetyTests.assert_optional_type(result, Path, allow_none=True)
        assert result is None

    def test_shot_to_dict_return_type(self):
        """Test to_dict returns Dict[str, str] as annotated."""
        shot = Shot("show", "seq", "shot", "/workspace")
        result = shot.to_dict()

        # Check return type
        TypeSafetyTests.assert_type_match(result, dict, "to_dict return")

        # Check all values are strings
        for key, value in result.items():
            TypeSafetyTests.assert_type_match(key, str, f"dict key {key}")
            TypeSafetyTests.assert_type_match(value, str, f"dict value for {key}")

    def test_shot_from_dict_parameter_types(self):
        """Test from_dict accepts Dict[str, str] as annotated."""
        # Valid dict
        valid_dict = {
            "show": "test",
            "sequence": "seq",
            "shot": "shot",
            "workspace_path": "/path",
        }

        shot = Shot.from_dict(valid_dict)
        assert isinstance(shot, Shot)

        # Verify the created shot has correct types
        TypeSafetyTests.assert_type_match(shot.show, str)
        TypeSafetyTests.assert_type_match(shot.sequence, str)
        TypeSafetyTests.assert_type_match(shot.shot, str)
        TypeSafetyTests.assert_type_match(shot.workspace_path, str)


class TestCacheManagerTypeAnnotations:
    """Test CacheManager type annotations and Optional handling."""

    def test_cache_manager_init_optional_parameter(self, tmp_path):
        """Test CacheManager init with Optional[Path] parameter."""
        # Test with None (default)
        cache1 = CacheManager()
        assert isinstance(cache1.cache_dir, Path)

        # Test with explicit Path
        cache2 = CacheManager(cache_dir=tmp_path)
        TypeSafetyTests.assert_type_match(cache2.cache_dir, Path)
        assert cache2.cache_dir == tmp_path

    def test_get_cached_shots_return_type(self, tmp_path):
        """Test get_cached_shots returns Optional[List[Dict[str, Any]]]."""
        cache = CacheManager(cache_dir=tmp_path)

        # With no cache file, should return None
        result = cache.get_cached_shots()
        TypeSafetyTests.assert_optional_type(result, list, allow_none=True)
        assert result is None

        # Create a valid cache file
        shots_data = [
            {
                "show": "test",
                "sequence": "seq",
                "shot": "001",
                "workspace_path": "/path",
            },
            {
                "show": "test2",
                "sequence": "seq2",
                "shot": "002",
                "workspace_path": "/path2",
            },
        ]
        from datetime import datetime

        cache_data = {"timestamp": datetime.now().isoformat(), "shots": shots_data}

        cache.shots_cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache.shots_cache_file, "w") as f:
            json.dump(cache_data, f)

        # Now should return List[Dict[str, Any]]
        result = cache.get_cached_shots()
        # Result should be Optional[List[Dict[str, Any]]], so check for both None and list
        if result is not None:
            TypeSafetyTests.assert_type_match(result, list, "cached shots result")

            # Check list contents
            assert len(result) == 2
            for shot_dict in result:
                TypeSafetyTests.assert_type_match(shot_dict, dict, "shot dictionary")
                for key, value in shot_dict.items():
                    TypeSafetyTests.assert_type_match(key, str, "shot dict key")
                    # Values can be Any, but in this case should be strings
                    TypeSafetyTests.assert_type_match(value, str, "shot dict value")
        else:
            # None is also valid for Optional type, but in this test we expect data
            pytest.fail("Expected cached shots data but got None")

    def test_cache_shots_parameter_types(self, tmp_path):
        """Test cache_shots accepts Union[List[Shot], List[Dict[str, str]]]."""
        cache = CacheManager(cache_dir=tmp_path)

        # Test with List[Shot]
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq2", "shot2", "/path2"),
        ]
        cache.cache_shots(shots)

        # Test with List[Dict[str, str]]
        shot_dicts = [
            {
                "show": "show3",
                "sequence": "seq3",
                "shot": "shot3",
                "workspace_path": "/path3",
            },
            {
                "show": "show4",
                "sequence": "seq4",
                "shot": "shot4",
                "workspace_path": "/path4",
            },
        ]
        cache.cache_shots(shot_dicts)

        # Test with empty list
        cache.cache_shots([])

        # Test with None (should be handled gracefully)
        cache.cache_shots(None)  # type: ignore[arg-type] - testing runtime behavior

    def test_get_memory_usage_return_type(self, tmp_path):
        """Test get_memory_usage returns Dict[str, Any] as annotated."""
        cache = CacheManager(cache_dir=tmp_path)
        result = cache.get_memory_usage()

        TypeSafetyTests.assert_type_match(result, dict, "memory usage result")

        # Check expected keys exist and have correct types
        expected_keys = {
            "total_bytes": int,
            "total_mb": float,
            "max_mb": float,
            "usage_percent": float,
            "thumbnail_count": int,
        }

        for key, expected_type in expected_keys.items():
            assert key in result, f"Missing key: {key}"
            TypeSafetyTests.assert_type_match(
                result[key], expected_type, f"memory usage {key}"
            )


class TestUtilsTypeAnnotations:
    """Test utils module type annotations."""

    def test_get_cache_stats_return_type(self):
        """Test get_cache_stats returns Dict[str, Any]."""
        result = get_cache_stats()
        TypeSafetyTests.assert_type_match(result, dict, "cache stats result")

        # Check expected structure
        expected_keys = [
            "path_cache_size",
            "version_cache_size",
            "extract_version_cache_info",
        ]
        for key in expected_keys:
            assert key in result, f"Missing cache stats key: {key}"

    def test_path_utils_build_path_types(self):
        """Test PathUtils.build_path parameter and return types."""
        # Test with string base
        result1 = PathUtils.build_path("/base", "seg1", "seg2")
        TypeSafetyTests.assert_type_match(result1, Path, "build_path with string base")

        # Test with Path base
        result2 = PathUtils.build_path(Path("/base"), "seg1", "seg2")
        TypeSafetyTests.assert_type_match(result2, Path, "build_path with Path base")

    def test_path_utils_validate_path_exists_types(self):
        """Test PathUtils.validate_path_exists parameter and return types."""
        # Test with string path
        result1 = PathUtils.validate_path_exists("/nonexistent", "Test path")
        TypeSafetyTests.assert_type_match(
            result1, bool, "validate_path_exists with string"
        )

        # Test with Path object
        result2 = PathUtils.validate_path_exists(Path("/nonexistent"), "Test path")
        TypeSafetyTests.assert_type_match(
            result2, bool, "validate_path_exists with Path"
        )

    def test_version_utils_extract_version_return_type(self):
        """Test VersionUtils.extract_version_from_path returns Optional[str]."""
        # With version in path
        result1 = VersionUtils.extract_version_from_path("/path/to/v001/file.ext")
        TypeSafetyTests.assert_optional_type(result1, str, allow_none=True)
        assert result1 == "v001"

        # Without version in path
        result2 = VersionUtils.extract_version_from_path("/path/without/version")
        TypeSafetyTests.assert_optional_type(result2, str, allow_none=True)
        assert result2 is None

    def test_file_utils_find_files_return_type(self, tmp_path):
        """Test FileUtils.find_files_by_extension returns List[Path]."""
        # Create test files
        (tmp_path / "test1.txt").touch()
        (tmp_path / "test2.txt").touch()
        (tmp_path / "test.jpg").touch()

        result = FileUtils.find_files_by_extension(tmp_path, "txt")
        TypeSafetyTests.assert_type_match(result, list, "find_files result")

        # Check list contents
        for path_item in result:
            TypeSafetyTests.assert_type_match(path_item, Path, "file path item")

    def test_file_utils_get_first_image_file_return_type(self, tmp_path):
        """Test FileUtils.get_first_image_file returns Optional[Path]."""
        # Empty directory - should return None
        result1 = FileUtils.get_first_image_file(tmp_path)
        TypeSafetyTests.assert_optional_type(result1, Path, allow_none=True)
        assert result1 is None

        # With image file - should return Path
        (tmp_path / "image.jpg").touch()
        result2 = FileUtils.get_first_image_file(tmp_path)
        TypeSafetyTests.assert_optional_type(result2, Path, allow_none=True)
        assert result2 is not None
        TypeSafetyTests.assert_type_match(result2, Path)

    def test_validation_utils_validate_not_empty_types(self):
        """Test ValidationUtils.validate_not_empty handles Optional strings."""
        # All valid strings
        result1 = ValidationUtils.validate_not_empty("test1", "test2", "test3")
        TypeSafetyTests.assert_type_match(result1, bool)
        assert result1 is True

        # With None values
        result2 = ValidationUtils.validate_not_empty("test", None, "test")
        TypeSafetyTests.assert_type_match(result2, bool)
        assert result2 is False

        # With empty strings
        result3 = ValidationUtils.validate_not_empty("test", "", "test")
        TypeSafetyTests.assert_type_match(result3, bool)
        assert result3 is False


class TestRuntimeTypeGuards:
    """Test type guards and runtime type checking."""

    def test_none_value_handling(self, monkeypatch):
        """Test that Optional types handle None values correctly."""
        # Test Shot.get_thumbnail_path with path that doesn't exist
        shot = Shot("test", "seq", "shot", "/nonexistent")

        # Mock validate_path_exists to return False
        monkeypatch.setattr(PathUtils, "validate_path_exists", lambda *args: False)

        result = shot.get_thumbnail_path()
        assert result is None

        # Type should be Optional[Path] - None is valid
        TypeSafetyTests.assert_optional_type(result, Path, allow_none=True)

    def test_empty_collection_handling(self):
        """Test that collection types handle empty collections correctly."""
        # Empty shot list
        model = ShotModel(cache_manager=None, load_cache=False)
        assert model.shots == []
        TypeSafetyTests.assert_type_match(model.shots, list)

        # Test get_shot_by_index with empty list
        result = model.get_shot_by_index(0)
        TypeSafetyTests.assert_optional_type(result, Shot, allow_none=True)
        assert result is None

    def test_dict_type_validation(self, tmp_path):
        """Test Dict[str, Any] types handle various value types."""
        cache = CacheManager(cache_dir=tmp_path)
        memory_stats = cache.get_memory_usage()

        # Should be Dict[str, Any] - values can be different types
        TypeSafetyTests.assert_type_match(memory_stats, dict)

        # Check that values are indeed of different types
        assert isinstance(memory_stats["total_bytes"], int)
        assert isinstance(memory_stats["total_mb"], float)
        assert isinstance(memory_stats["usage_percent"], float)
        assert isinstance(memory_stats["thumbnail_count"], int)

    def test_union_type_handling(self, tmp_path):
        """Test Union types accept multiple valid types."""
        cache = CacheManager(cache_dir=tmp_path)

        # cache_shots accepts Union[List[Shot], List[Dict[str, str]]]

        # Test with List[Shot]
        shots = [Shot("show", "seq", "shot", "/path")]
        cache.cache_shots(shots)  # Should not raise type error

        # Test with List[Dict[str, str]]
        shot_dicts = [
            {
                "show": "show",
                "sequence": "seq",
                "shot": "shot",
                "workspace_path": "/path",
            }
        ]
        cache.cache_shots(shot_dicts)  # Should not raise type error


class TestSignalSlotTypeCompatibility:
    """Test that signal/slot type annotations are compatible."""

    def test_cache_manager_signals(self):
        """Test CacheManager signal type compatibility."""
        cache = CacheManager()

        # cache_updated signal should be Signal()
        assert hasattr(cache, "cache_updated")
        assert isinstance(cache.cache_updated, Signal)

        # Test signal emission (can't mock PySide6 signal emit, just verify it exists)
        # The emit method exists and is callable
        assert hasattr(cache.cache_updated, "emit")
        assert callable(cache.cache_updated.emit)

        # Test that we can emit the signal without errors
        try:
            cache.cache_updated.emit()
        except Exception as e:
            pytest.fail(f"Signal emit failed: {e}")


class TestJSONSerializationTypes:
    """Test that typed data works with JSON serialization."""

    def test_shot_dict_json_serialization(self):
        """Test that Shot.to_dict() result is JSON serializable."""
        shot = Shot("show", "sequence", "shot", "/workspace/path")
        shot_dict = shot.to_dict()

        # Should serialize to JSON without error
        json_str = json.dumps(shot_dict)
        assert isinstance(json_str, str)

        # Should deserialize back correctly
        deserialized = json.loads(json_str)
        TypeSafetyTests.assert_type_match(deserialized, dict)

        # Recreate shot from deserialized data
        recreated_shot = Shot.from_dict(deserialized)
        assert recreated_shot.show == shot.show
        assert recreated_shot.sequence == shot.sequence
        assert recreated_shot.shot == shot.shot
        assert recreated_shot.workspace_path == shot.workspace_path

    def test_cache_data_json_compatibility(self, tmp_path):
        """Test that cache data maintains type compatibility through JSON."""
        cache = CacheManager(cache_dir=tmp_path)

        # Create some shots and cache them
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq2", "shot2", "/path2"),
        ]

        cache.cache_shots(shots)

        # Read back from cache
        cached_shots = cache.get_cached_shots()
        assert cached_shots is not None
        TypeSafetyTests.assert_type_match(cached_shots, list)

        # Each cached shot should be a dict with string values
        for cached_shot in cached_shots:
            TypeSafetyTests.assert_type_match(cached_shot, dict)
            for key, value in cached_shot.items():
                TypeSafetyTests.assert_type_match(key, str)
                TypeSafetyTests.assert_type_match(value, str)


class TestSubprocessTypeIntegration:
    """Test that subprocess-related types work correctly."""

    def test_refresh_result_from_subprocess(self, monkeypatch):
        """Test RefreshResult type consistency from subprocess operations."""
        # Mock successful subprocess
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "workspace /shows/test/shots/seq/shot"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            model = ShotModel(cache_manager=None, load_cache=False)
            result = model.refresh_shots()

            # Should return RefreshResult NamedTuple
            assert isinstance(result, RefreshResult)
            TypeSafetyTests.assert_type_match(result.success, bool)
            TypeSafetyTests.assert_type_match(result.has_changes, bool)

    def test_error_handling_preserves_types(self, monkeypatch):
        """Test that error conditions still return correct types."""
        # Mock subprocess failure
        with patch(
            "subprocess.run", side_effect=FileNotFoundError("Command not found")
        ):
            model = ShotModel(cache_manager=None, load_cache=False)
            result = model.refresh_shots()

            # Should still return RefreshResult with correct types
            assert isinstance(result, RefreshResult)
            assert result.success is False
            assert result.has_changes is False
            TypeSafetyTests.assert_type_match(result.success, bool)
            TypeSafetyTests.assert_type_match(result.has_changes, bool)


class TestPropertyReturnTypes:
    """Test that @property methods return correct types."""

    def test_shot_properties(self):
        """Test Shot property return types."""
        shot = Shot("show", "sequence", "shot", "/workspace")

        # full_name property
        full_name = shot.full_name
        TypeSafetyTests.assert_type_match(full_name, str)
        assert full_name == "sequence_shot"

        # thumbnail_dir property
        thumb_dir = shot.thumbnail_dir
        TypeSafetyTests.assert_type_match(thumb_dir, Path)
        assert isinstance(thumb_dir, Path)

    def test_cache_manager_properties(self, tmp_path):
        """Test CacheManager property return types."""
        cache = CacheManager(cache_dir=tmp_path)

        # CACHE_THUMBNAIL_SIZE property
        size = cache.CACHE_THUMBNAIL_SIZE
        TypeSafetyTests.assert_type_match(size, int)

        # CACHE_EXPIRY_MINUTES property
        expiry = cache.CACHE_EXPIRY_MINUTES
        TypeSafetyTests.assert_type_match(expiry, int)


class TestPython38Compatibility:
    """Test Python 3.8 type compatibility (tuple vs Tuple)."""

    def test_tuple_annotation_compatibility(self):
        """Test that tuple annotations work in Python 3.8+."""
        # This would test the fixes mentioned in the issue
        # where tuple was changed to Tuple for Python 3.8 compatibility

        # Test that function signatures using Tuple work
        from typing import Tuple

        def test_function() -> Tuple[bool, bool]:
            return (True, False)

        result = test_function()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(x, bool) for x in result)

    def test_list_dict_annotations(self):
        """Test List and Dict annotations for Python 3.8."""

        def test_list_func() -> List[str]:
            return ["a", "b", "c"]

        def test_dict_func() -> Dict[str, int]:
            return {"a": 1, "b": 2}

        list_result = test_list_func()
        dict_result = test_dict_func()

        TypeSafetyTests.assert_type_match(list_result, list)
        TypeSafetyTests.assert_type_match(dict_result, dict)


# Integration test to ensure all type annotations work together
class TestTypeSystemIntegration:
    """Integration tests for the entire type system."""

    def test_end_to_end_type_safety(self, tmp_path, monkeypatch):
        """Test complete workflow maintains type safety."""
        # Setup
        cache = CacheManager(cache_dir=tmp_path)
        model = ShotModel(cache_manager=cache, load_cache=False)

        # Mock subprocess to return valid data
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = """
        workspace /shows/test1/shots/seq1/shot1
        workspace /shows/test2/shots/seq2/shot2
        """
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            # Refresh shots
            refresh_result = model.refresh_shots()

            # Verify types throughout the pipeline
            assert isinstance(refresh_result, RefreshResult)
            assert isinstance(refresh_result.success, bool)
            assert isinstance(refresh_result.has_changes, bool)

            # Check shot list
            assert isinstance(model.shots, list)
            for shot in model.shots:
                assert isinstance(shot, Shot)
                assert isinstance(shot.show, str)
                assert isinstance(shot.sequence, str)
                assert isinstance(shot.shot, str)
                assert isinstance(shot.workspace_path, str)

                # Test properties
                assert isinstance(shot.full_name, str)
                assert isinstance(shot.thumbnail_dir, Path)

                # Test methods
                shot_dict = shot.to_dict()
                assert isinstance(shot_dict, dict)
                for key, value in shot_dict.items():
                    assert isinstance(key, str)
                    assert isinstance(value, str)

    def test_error_scenarios_maintain_types(self, monkeypatch):
        """Test that error scenarios maintain type safety."""
        model = ShotModel(cache_manager=None, load_cache=False)

        # Test various error conditions
        error_scenarios = [
            FileNotFoundError("Command not found"),
            PermissionError("Permission denied"),
            TimeoutError("Timeout"),
            RuntimeError("Generic error"),
        ]

        for error in error_scenarios:
            with patch("subprocess.run", side_effect=error):
                result = model.refresh_shots()

                # Should always return RefreshResult with correct types
                assert isinstance(result, RefreshResult)
                assert isinstance(result.success, bool)
                assert isinstance(result.has_changes, bool)
                assert result.success is False
                assert result.has_changes is False


if __name__ == "__main__":
    # Run specific type safety tests
    pytest.main([__file__, "-v"])
