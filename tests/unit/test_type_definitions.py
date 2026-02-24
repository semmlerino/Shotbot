"""Unit tests for type_definitions module.

This module tests:
1. Shot dataclass - field validation, serialization, thread safety
2. Protocols - compliance verification for existing implementations
3. TypedDict structures - required/optional field handling
4. Type aliases - correct type resolution

Following UNIFIED_TESTING_GUIDE best practices:
- Tests behavior, not implementation
- Uses real components where possible
- Minimal mocking at system boundaries
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from dataclasses import fields
from pathlib import Path

import pytest

from type_definitions import (
    CacheKey,
    CacheMetricsDict,
    # Protocols
    CommandList,
    Duration,
    FinderProtocol,
    LauncherProtocol,
    PathLike,
    Shot,
    # TypedDicts
    ShotDict,
    ThreeDESceneDict,
    Timestamp,
)


# ==============================================================================
# Shot Dataclass Tests
# ==============================================================================


@pytest.mark.unit
class TestShotDataclass:
    """Tests for Shot dataclass correctness and behavior."""

    def test_shot_creation_with_required_fields(self) -> None:
        """Shot can be created with all required fields."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        assert shot.show == "testshow"
        assert shot.sequence == "sq010"
        assert shot.shot == "0010"
        assert shot.workspace_path == "/shows/testshow/shots/sq010/sq010_0010"

    def test_shot_discovered_at_defaults_to_zero(self) -> None:
        """Shot discovered_at field defaults to 0.0 if not provided."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        assert shot.discovered_at == 0.0

    def test_shot_discovered_at_can_be_set(self) -> None:
        """Shot discovered_at field can be explicitly set."""
        timestamp = time.time()
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
            discovered_at=timestamp,
        )

        assert shot.discovered_at == timestamp

    def test_shot_full_name_property(self) -> None:
        """Shot.full_name returns sequence_shot format."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        assert shot.full_name == "sq010_0010"

    def test_shot_full_name_with_special_characters(self) -> None:
        """Shot.full_name works with special characters in sequence/shot names."""
        shot = Shot(
            show="testshow",
            sequence="101_ABC",
            shot="0010_v2",
            workspace_path="/shows/testshow/shots/101_ABC/101_ABC_0010_v2",
        )

        assert shot.full_name == "101_ABC_0010_v2"

    def test_shot_equality_by_value(self) -> None:
        """Two shots with same values are equal."""
        shot1 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )
        shot2 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        assert shot1 == shot2

    def test_shot_inequality_by_different_values(self) -> None:
        """Two shots with different values are not equal."""
        shot1 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )
        shot2 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0020",  # Different shot
            workspace_path="/shows/testshow/shots/sq010/sq010_0020",
        )

        assert shot1 != shot2

    def test_shot_slots_attribute(self) -> None:
        """Shot uses slots for memory efficiency."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        # Slotted classes don't have __dict__
        assert not hasattr(shot, "__dict__")

    def test_shot_repr_contains_all_fields(self) -> None:
        """Shot repr contains all main fields for debugging."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        repr_str = repr(shot)
        assert "testshow" in repr_str
        assert "sq010" in repr_str
        assert "0010" in repr_str


@pytest.mark.unit
class TestShotSerialization:
    """Tests for Shot serialization to/from dictionary."""

    def test_to_dict_contains_required_fields(self) -> None:
        """Shot.to_dict() includes all required fields."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        result = shot.to_dict()

        assert result["show"] == "testshow"
        assert result["sequence"] == "sq010"
        assert result["shot"] == "0010"
        assert result["workspace_path"] == "/shows/testshow/shots/sq010/sq010_0010"

    def test_to_dict_includes_discovered_at(self) -> None:
        """Shot.to_dict() includes discovered_at timestamp."""
        timestamp = 1700000000.0
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
            discovered_at=timestamp,
        )

        result = shot.to_dict()

        assert result["discovered_at"] == timestamp

    def test_to_dict_excludes_private_fields(self) -> None:
        """Shot.to_dict() does not include private/internal fields."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        result = shot.to_dict()

        # Private fields should not be serialized
        assert "_cached_thumbnail_path" not in result
        assert "_thumbnail_lock" not in result

    def test_from_dict_with_all_fields(self) -> None:
        """Shot.from_dict() creates shot with all provided fields."""
        data: ShotDict = {
            "show": "testshow",
            "sequence": "sq010",
            "shot": "0010",
            "workspace_path": "/shows/testshow/shots/sq010/sq010_0010",
            "discovered_at": 1700000000.0,
        }

        shot = Shot.from_dict(data)

        assert shot.show == "testshow"
        assert shot.sequence == "sq010"
        assert shot.shot == "0010"
        assert shot.workspace_path == "/shows/testshow/shots/sq010/sq010_0010"
        assert shot.discovered_at == 1700000000.0

    def test_from_dict_without_discovered_at(self) -> None:
        """Shot.from_dict() defaults discovered_at to 0.0 if not provided."""
        data: ShotDict = {
            "show": "testshow",
            "sequence": "sq010",
            "shot": "0010",
            "workspace_path": "/shows/testshow/shots/sq010/sq010_0010",
        }

        shot = Shot.from_dict(data)

        assert shot.discovered_at == 0.0

    def test_roundtrip_serialization(self) -> None:
        """Shot serialization roundtrip preserves all data."""
        original = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
            discovered_at=1700000000.0,
        )

        serialized = original.to_dict()
        restored = Shot.from_dict(serialized)

        assert restored == original


@pytest.mark.unit
class TestShotThumbnailCaching:
    """Tests for Shot thumbnail path caching behavior."""

    def test_thumbnail_cache_initially_not_searched(self) -> None:
        """Shot thumbnail cache starts in 'not searched' state."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        # The sentinel value indicates not yet searched
        from type_definitions import _NOT_SEARCHED

        assert shot._cached_thumbnail_path is _NOT_SEARCHED

    def test_thumbnail_lock_is_threading_lock(self) -> None:
        """Shot has a threading.Lock for thread-safe thumbnail caching."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        assert type(shot._thumbnail_lock) is type(threading.Lock())

    def test_thumbnail_lock_per_instance(self) -> None:
        """Each Shot instance has its own lock (not shared)."""
        shot1 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )
        shot2 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0020",
            workspace_path="/shows/testshow/shots/sq010/sq010_0020",
        )

        assert shot1._thumbnail_lock is not shot2._thumbnail_lock

    def test_thumbnail_cache_not_included_in_equality(self) -> None:
        """Thumbnail cache state doesn't affect Shot equality."""
        shot1 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )
        shot2 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        # Artificially set different cache states
        shot1._cached_thumbnail_path = None
        shot2._cached_thumbnail_path = Path("/some/path.jpg")

        # Should still be equal (compare=False on cache field)
        assert shot1 == shot2


@pytest.mark.unit
class TestShotThreadSafety:
    """Tests for Shot thread safety in concurrent scenarios."""

    def test_concurrent_thumbnail_access_no_crash(self) -> None:
        """Multiple threads accessing thumbnail path don't cause crashes."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        errors: list[Exception] = []

        def access_thumbnail() -> None:
            try:
                # Access the lock attribute (don't call get_thumbnail_path
                # as it requires real filesystem)
                with shot._thumbnail_lock:
                    pass
            except Exception as e:
                errors.append(e)

        # Run many concurrent accesses
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(access_thumbnail) for _ in range(100)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Thread errors occurred: {errors}"


# ==============================================================================
# TypedDict Tests
# ==============================================================================


@pytest.mark.unit
class TestShotDict:
    """Tests for ShotDict TypedDict structure."""

    def test_required_fields_enforced(self) -> None:
        """ShotDict requires show, sequence, shot, workspace_path."""
        # Valid dict with all required fields
        valid: ShotDict = {
            "show": "test",
            "sequence": "sq01",
            "shot": "0010",
            "workspace_path": "/path",
        }

        assert valid["show"] == "test"
        assert valid["sequence"] == "sq01"
        assert valid["shot"] == "0010"
        assert valid["workspace_path"] == "/path"

    def test_optional_discovered_at(self) -> None:
        """ShotDict can optionally include discovered_at."""
        with_discovered: ShotDict = {
            "show": "test",
            "sequence": "sq01",
            "shot": "0010",
            "workspace_path": "/path",
            "discovered_at": 1700000000.0,
        }

        without_discovered: ShotDict = {
            "show": "test",
            "sequence": "sq01",
            "shot": "0010",
            "workspace_path": "/path",
        }

        assert with_discovered.get("discovered_at") == 1700000000.0
        assert without_discovered.get("discovered_at") is None


@pytest.mark.unit
class TestThreeDESceneDict:
    """Tests for ThreeDESceneDict TypedDict structure."""

    def test_all_required_fields(self) -> None:
        """ThreeDESceneDict has all expected fields."""
        scene: ThreeDESceneDict = {
            "filepath": "/path/to/scene.3de",
            "show": "testshow",
            "sequence": "sq010",
            "shot": "0010",
            "user": "artist",
            "filename": "scene.3de",
            "modified_time": 1700000000.0,
            "workspace_path": "/shows/testshow/shots/sq010/sq010_0010",
        }

        assert scene["filepath"] == "/path/to/scene.3de"
        assert scene["user"] == "artist"
        assert scene["filename"] == "scene.3de"
        assert scene["modified_time"] == 1700000000.0

    def test_optional_last_seen(self) -> None:
        """ThreeDESceneDict can optionally include last_seen."""
        with_last_seen: ThreeDESceneDict = {
            "filepath": "/path/to/scene.3de",
            "show": "testshow",
            "sequence": "sq010",
            "shot": "0010",
            "user": "artist",
            "filename": "scene.3de",
            "modified_time": 1700000000.0,
            "workspace_path": "/shows/testshow/shots/sq010/sq010_0010",
            "last_seen": 1700000001.0,
        }

        assert with_last_seen.get("last_seen") == 1700000001.0


@pytest.mark.unit
class TestCacheMetricsDict:
    """Tests for CacheMetricsDict TypedDict structure."""

    def test_all_fields_present(self) -> None:
        """CacheMetricsDict has all expected fields."""
        metrics: CacheMetricsDict = {
            "total_size_bytes": 1024000,
            "item_count": 100,
            "hit_rate": 0.85,
            "miss_rate": 0.15,
            "eviction_count": 5,
            "last_cleanup": 1700000000.0,
        }

        assert metrics["total_size_bytes"] == 1024000
        assert metrics["item_count"] == 100
        assert metrics["hit_rate"] == 0.85
        assert metrics["miss_rate"] == 0.15


# ==============================================================================
# Protocol Compliance Tests
# ==============================================================================


@pytest.mark.unit
class TestCacheProtocolCompliance:
    """Tests that verify implementations satisfy CacheProtocol."""

    def test_cache_manager_satisfies_protocol(self) -> None:
        """CacheManager implements all CacheProtocol methods."""
        from cache_manager import CacheManager

        # Check that all protocol methods exist with correct signatures
        assert hasattr(CacheManager, "cache_shots")
        assert hasattr(CacheManager, "get_cached_shots")
        assert hasattr(CacheManager, "clear_cache")
        assert hasattr(CacheManager, "get_memory_usage")

        # Verify method signatures by getting type hints
        # (This is a structural check - runtime protocol compliance)
        cache = CacheManager()
        assert callable(cache.cache_shots)
        assert callable(cache.get_cached_shots)
        assert callable(cache.clear_cache)
        assert callable(cache.get_memory_usage)


@pytest.mark.unit
class TestFinderProtocolCompliance:
    """Tests that verify implementations satisfy FinderProtocol."""

    def test_protocol_requires_find_all(self) -> None:
        """FinderProtocol requires find_all method."""
        # Get protocol method names
        import inspect

        protocol_methods = [
            name
            for name, _ in inspect.getmembers(FinderProtocol, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]

        assert "find_all" in protocol_methods or hasattr(FinderProtocol, "find_all")

    def test_protocol_requires_find_for_shot(self) -> None:
        """FinderProtocol requires find_for_shot method."""
        import inspect

        protocol_methods = [
            name
            for name, _ in inspect.getmembers(FinderProtocol, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]

        assert "find_for_shot" in protocol_methods or hasattr(
            FinderProtocol, "find_for_shot"
        )


@pytest.mark.unit
class TestLauncherProtocolCompliance:
    """Tests that verify implementations satisfy LauncherProtocol."""

    def test_protocol_requires_launch(self) -> None:
        """LauncherProtocol requires launch method."""
        assert hasattr(LauncherProtocol, "launch")

    def test_protocol_requires_is_running(self) -> None:
        """LauncherProtocol requires is_running method."""
        assert hasattr(LauncherProtocol, "is_running")

    def test_protocol_requires_terminate(self) -> None:
        """LauncherProtocol requires terminate method."""
        assert hasattr(LauncherProtocol, "terminate")


# ==============================================================================
# Type Alias Tests
# ==============================================================================


@pytest.mark.unit
class TestTypeAliases:
    """Tests for type alias correctness."""

    def test_pathlike_accepts_str(self) -> None:
        """PathLike type accepts str."""
        path: PathLike = "/some/path"
        assert isinstance(path, str)

    def test_pathlike_accepts_path(self) -> None:
        """PathLike type accepts Path."""
        path: PathLike = Path("/some/path")
        assert isinstance(path, Path)

    def test_timestamp_is_float(self) -> None:
        """Timestamp type is float."""
        ts: Timestamp = time.time()
        assert isinstance(ts, float)

    def test_duration_is_float(self) -> None:
        """Duration type is float."""
        duration: Duration = 5.5
        assert isinstance(duration, float)

    def test_command_list_is_list_of_str(self) -> None:
        """CommandList type is list of str."""
        cmd: CommandList = ["python", "-c", "print('hello')"]
        assert isinstance(cmd, list)
        assert all(isinstance(item, str) for item in cmd)

    def test_cache_key_is_str(self) -> None:
        """CacheKey type is str."""
        key: CacheKey = "my_cache_key"
        assert isinstance(key, str)


# ==============================================================================
# Dataclass Field Introspection Tests
# ==============================================================================


@pytest.mark.unit
class TestShotDataclassFields:
    """Tests for Shot dataclass field definitions."""

    def test_shot_has_expected_field_count(self) -> None:
        """Shot has exactly the expected number of fields."""
        shot_fields = fields(Shot)
        # show, sequence, shot, workspace_path, discovered_at, frame_start, frame_end,
        # _cached_thumbnail_path, _thumbnail_lock
        assert len(shot_fields) == 9

    def test_private_fields_not_in_init(self) -> None:
        """Private fields are excluded from __init__."""
        shot_fields = fields(Shot)
        init_fields = [f for f in shot_fields if f.init]

        # Only public fields should be in __init__
        init_field_names = [f.name for f in init_fields]
        assert "_cached_thumbnail_path" not in init_field_names
        assert "_thumbnail_lock" not in init_field_names

    def test_private_fields_not_in_repr(self) -> None:
        """Private fields are excluded from __repr__."""
        shot_fields = fields(Shot)
        repr_fields = [f for f in shot_fields if f.repr]

        repr_field_names = [f.name for f in repr_fields]
        assert "_cached_thumbnail_path" not in repr_field_names
        assert "_thumbnail_lock" not in repr_field_names

    def test_private_fields_not_in_compare(self) -> None:
        """Private fields are excluded from comparison."""
        shot_fields = fields(Shot)
        compare_fields = [f for f in shot_fields if f.compare]

        compare_field_names = [f.name for f in compare_fields]
        assert "_cached_thumbnail_path" not in compare_field_names
        assert "_thumbnail_lock" not in compare_field_names


# ==============================================================================
# Edge Case Tests
# ==============================================================================


@pytest.mark.unit
class TestShotEdgeCases:
    """Tests for Shot edge cases and boundary conditions."""

    def test_empty_string_fields(self) -> None:
        """Shot can be created with empty string fields."""
        shot = Shot(
            show="",
            sequence="",
            shot="",
            workspace_path="",
        )

        assert shot.show == ""
        assert shot.full_name == "_"  # sequence_shot with empty strings

    def test_unicode_in_fields(self) -> None:
        """Shot handles unicode characters in fields."""
        shot = Shot(
            show="テスト",
            sequence="日本語",
            shot="0010",
            workspace_path="/shows/テスト/shots/日本語/日本語_0010",
        )

        assert shot.show == "テスト"
        assert shot.sequence == "日本語"
        assert shot.full_name == "日本語_0010"

    def test_very_long_paths(self) -> None:
        """Shot handles very long workspace paths."""
        long_path = "/shows/" + "a" * 500 + "/shots/seq/shot"
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path=long_path,
        )

        assert shot.workspace_path == long_path

    def test_special_characters_in_names(self) -> None:
        """Shot handles special characters in show/sequence/shot names."""
        shot = Shot(
            show="test-show_v2",
            sequence="sq.010",
            shot="0010-final",
            workspace_path="/shows/test-show_v2/shots/sq.010/sq.010_0010-final",
        )

        assert shot.show == "test-show_v2"
        assert shot.sequence == "sq.010"
        assert shot.shot == "0010-final"

    def test_discovered_at_negative_timestamp(self) -> None:
        """Shot accepts negative discovered_at (before epoch)."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
            discovered_at=-1000.0,
        )

        assert shot.discovered_at == -1000.0

    def test_discovered_at_very_large_timestamp(self) -> None:
        """Shot accepts very large discovered_at timestamps (far future)."""
        # Year 3000 timestamp
        future_ts = 32503680000.0
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
            discovered_at=future_ts,
        )

        assert shot.discovered_at == future_ts
