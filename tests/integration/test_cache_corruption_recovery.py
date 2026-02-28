"""Integration tests for cache corruption recovery.

This module tests:
1. Malformed JSON recovery - corrupted files, truncated writes
2. Invalid data structure recovery - missing fields, wrong types
3. Permission errors - read/write access issues
4. Disk space errors - write failures
5. Atomic write guarantees - crash safety

These are integration tests because they test:
- Real file I/O operations
- Error recovery mechanisms
- CacheManager state consistency after errors
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cache_manager import CacheManager


if TYPE_CHECKING:
    from type_definitions import ShotDict, ThreeDESceneDict


# ==============================================================================
# Test Data Factories
# ==============================================================================


def make_shot_dict(
    show: str = "testshow",
    sequence: str = "sq010",
    shot: str = "0010",
) -> ShotDict:
    """Create a valid ShotDict for testing."""
    return {
        "show": show,
        "sequence": sequence,
        "shot": shot,
        "workspace_path": f"/shows/{show}/shots/{sequence}/{sequence}_{shot}",
        "discovered_at": 0.0,
    }


def make_scene_dict(
    show: str = "testshow",
    sequence: str = "sq010",
    shot: str = "0010",
) -> ThreeDESceneDict:
    """Create a valid ThreeDESceneDict for testing."""
    return {
        "filepath": f"/shows/{show}/shots/{sequence}/{sequence}_{shot}/scene.3de",
        "show": show,
        "sequence": sequence,
        "shot": shot,
        "user": "artist",
        "filename": "scene.3de",
        "modified_time": 1700000000.0,
        "workspace_path": f"/shows/{show}/shots/{sequence}/{sequence}_{shot}",
    }


# ==============================================================================
# Malformed JSON Recovery Tests
# ==============================================================================


@pytest.mark.integration
class TestMalformedJsonRecovery:
    """Tests for recovery from corrupted/malformed JSON cache files."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_recover_from_malformed_content(self, cache_manager: CacheManager) -> None:
        """Malformed cache payloads return None without crashing."""
        cache_file = cache_manager.shots_cache_file
        malformed_cases = [
            ("empty_file", ""),
            ("truncated_json", '{"data": [{"show": "test", "sequence": "sq01"'),
            ("invalid_json_syntax", '[{"show": "test",}]'),
            ("binary_garbage", b"\x00\x01\x02\xff\xfe\xfd"),
        ]

        for case_name, payload in malformed_cases:
            if isinstance(payload, bytes):
                cache_file.write_bytes(payload)
            else:
                cache_file.write_text(payload)

            result = cache_manager._read_json_cache(cache_file, check_ttl=False)
            assert result is None, f"Expected None for malformed case: {case_name}"

    def test_recover_from_wrong_encoding(self, cache_manager: CacheManager) -> None:
        """Non-UTF8 encoded file returns None gracefully."""
        cache_file = cache_manager.shots_cache_file
        # Write with Latin-1 encoding (non-UTF8)
        with cache_file.open("w", encoding="latin-1") as f:
            f.write('[{"show": "tëst"}]')

        # Read should either succeed or fail gracefully
        result = cache_manager._read_json_cache(cache_file, check_ttl=False)

        # Result is either the data (if Python's UTF-8 is lenient) or None
        assert result is None or isinstance(result, list)


# ==============================================================================
# Invalid Data Structure Recovery Tests
# ==============================================================================


@pytest.mark.integration
class TestInvalidDataStructureRecovery:
    """Tests for recovery from structurally invalid cache data."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_rejects_invalid_data_structures(self, cache_manager: CacheManager) -> None:
        """Invalid decoded JSON structures are rejected consistently."""
        cache_file = cache_manager.shots_cache_file
        invalid_cases = [
            ("json_null", "null"),
            ("json_string", '"just a string"'),
            ("json_number", "42"),
            ("list_of_non_dicts", '["string1", "string2"]'),
            ("mixed_list", '[{"show": "test"}, "not a dict"]'),
        ]

        for case_name, payload in invalid_cases:
            cache_file.write_text(payload)
            result = cache_manager._read_json_cache(cache_file, check_ttl=False)
            assert result is None, f"Expected None for invalid case: {case_name}"

    def test_accepts_valid_data_structures(self, cache_manager: CacheManager) -> None:
        """Valid list and wrapped-list cache formats are accepted."""
        cache_file = cache_manager.shots_cache_file
        valid_cases = [
            ("valid_list_format", [make_shot_dict(shot="0010"), make_shot_dict(shot="0020")], 2),
            (
                "valid_wrapped_format",
                {"data": [make_shot_dict(shot="0010")], "cached_at": "2024-01-01T00:00:00"},
                1,
            ),
            ("empty_list", [], 0),
            ("wrapped_empty_data", {"data": [], "cached_at": "2024-01-01"}, 0),
        ]

        for case_name, payload, expected_len in valid_cases:
            cache_file.write_text(json.dumps(payload))
            result = cache_manager._read_json_cache(cache_file, check_ttl=False)
            assert result is not None, f"Expected data for valid case: {case_name}"
            assert len(result) == expected_len, (
                f"Unexpected result length for case: {case_name}"
            )


# ==============================================================================
# Permission Error Recovery Tests
# ==============================================================================


@pytest.mark.integration
class TestPermissionErrorRecovery:
    """Tests for recovery from permission errors."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_recover_from_unreadable_file(
        self, cache_manager: CacheManager, tmp_path: Path
    ) -> None:
        """Unreadable cache file returns None gracefully."""
        cache_file = cache_manager.shots_cache_file
        cache_file.write_text('[{"show": "test"}]')

        # Make file unreadable (Unix only)
        try:
            cache_file.chmod(0o000)

            result = cache_manager._read_json_cache(cache_file, check_ttl=False)

            # Should return None due to permission error
            assert result is None

        finally:
            # Restore permissions for cleanup
            cache_file.chmod(0o644)

    def test_recover_from_unwritable_directory(
        self, cache_manager: CacheManager, tmp_path: Path
    ) -> None:
        """Unwritable cache directory causes write to fail gracefully."""
        cache_file = cache_manager.shots_cache_file
        shots = [make_shot_dict()]

        # Make directory unwritable (Unix only)
        try:
            cache_manager.cache_dir.chmod(0o555)

            success = cache_manager._write_json_cache(cache_file, shots)

            # Should return False due to permission error
            assert success is False

        finally:
            # Restore permissions for cleanup
            cache_manager.cache_dir.chmod(0o755)

    def test_nonexistent_file_returns_none(
        self, cache_manager: CacheManager
    ) -> None:
        """Nonexistent cache file returns None (not an error)."""
        cache_file = cache_manager.cache_dir / "does_not_exist.json"

        result = cache_manager._read_json_cache(cache_file, check_ttl=False)

        assert result is None


# ==============================================================================
# Atomic Write Tests
# ==============================================================================


@pytest.mark.integration
class TestAtomicWriteGuarantees:
    """Tests for atomic write behavior."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_successful_write_creates_file(
        self, cache_manager: CacheManager
    ) -> None:
        """Successful write creates cache file."""
        cache_file = cache_manager.shots_cache_file
        shots = [make_shot_dict(shot="0010")]

        success = cache_manager._write_json_cache(cache_file, shots)

        assert success is True
        assert cache_file.exists()

    def test_successful_write_is_readable(
        self, cache_manager: CacheManager
    ) -> None:
        """Written cache file is valid and readable."""
        cache_file = cache_manager.shots_cache_file
        shots = [make_shot_dict(shot="0010")]

        cache_manager._write_json_cache(cache_file, shots)
        result = cache_manager._read_json_cache(cache_file, check_ttl=False)

        assert result is not None
        assert len(result) == 1
        assert result[0]["shot"] == "0010"

    def test_write_overwrites_existing(self, cache_manager: CacheManager) -> None:
        """Write overwrites existing cache file."""
        cache_file = cache_manager.shots_cache_file

        # Write first version
        shots_v1 = [make_shot_dict(shot="0010")]
        cache_manager._write_json_cache(cache_file, shots_v1)

        # Write second version
        shots_v2 = [make_shot_dict(shot="0020"), make_shot_dict(shot="0030")]
        cache_manager._write_json_cache(cache_file, shots_v2)

        result = cache_manager._read_json_cache(cache_file, check_ttl=False)

        assert result is not None
        assert len(result) == 2  # Second write succeeded

    def test_write_creates_parent_directories(
        self, cache_manager: CacheManager
    ) -> None:
        """Write creates parent directories if they don't exist."""
        cache_file = cache_manager.cache_dir / "subdir" / "nested" / "shots.json"
        shots = [make_shot_dict()]

        success = cache_manager._write_json_cache(cache_file, shots)

        assert success is True
        assert cache_file.exists()

    def test_no_temp_files_left_on_success(
        self, cache_manager: CacheManager
    ) -> None:
        """Successful write leaves no temp files."""
        cache_file = cache_manager.shots_cache_file
        shots = [make_shot_dict()]

        cache_manager._write_json_cache(cache_file, shots)

        # Check for temp files in cache directory
        temp_files = list(cache_manager.cache_dir.glob(".*"))
        # Should have no hidden temp files
        assert len([f for f in temp_files if ".tmp" in f.name]) == 0


# ==============================================================================
# Write Failure Recovery Tests
# ==============================================================================


@pytest.mark.integration
class TestWriteFailureRecovery:
    """Tests for recovery from write failures."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_invalid_data_type_fails_gracefully(
        self, cache_manager: CacheManager
    ) -> None:
        """Non-serializable data causes write to fail gracefully."""
        cache_file = cache_manager.shots_cache_file

        # Create non-JSON-serializable data
        class NotSerializable:
            pass

        invalid_data = [{"obj": NotSerializable()}]

        success = cache_manager._write_json_cache(cache_file, invalid_data)

        assert success is False

    def test_write_failure_preserves_existing_cache(
        self, cache_manager: CacheManager
    ) -> None:
        """Failed write preserves existing cache file."""
        cache_file = cache_manager.shots_cache_file

        # Write valid data first
        shots_v1 = [make_shot_dict(shot="0010")]
        cache_manager._write_json_cache(cache_file, shots_v1)

        # Attempt to write invalid data
        class NotSerializable:
            pass

        invalid_data = [{"obj": NotSerializable()}]
        cache_manager._write_json_cache(cache_file, invalid_data)

        # Original data should still be readable
        result = cache_manager._read_json_cache(cache_file, check_ttl=False)
        assert result is not None
        assert len(result) == 1
        assert result[0]["shot"] == "0010"


# ==============================================================================
# Public API Recovery Tests
# ==============================================================================


@pytest.mark.integration
class TestPublicAPIRecovery:
    """Tests that public API methods handle errors gracefully."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_get_cached_data_with_corrupted_file(
        self, cache_manager: CacheManager
    ) -> None:
        """Public cache getters return None when their backing file is corrupted."""
        corruption_cases = [
            (
                "shots",
                cache_manager.shots_cache_file,
                cache_manager.get_shots_with_ttl,
                "invalid json {{{",
            ),
            (
                "previous_shots",
                cache_manager.previous_shots_cache_file,
                cache_manager.get_cached_previous_shots,
                "not valid json",
            ),
        ]

        for case_name, file_path, getter, corrupted_payload in corruption_cases:
            file_path.write_text(corrupted_payload)
            result = getter()
            assert result is None, f"Expected None for corrupted {case_name} cache"

    def test_cache_shots_success_after_corruption(
        self, cache_manager: CacheManager
    ) -> None:
        """cache_shots can overwrite corrupted file."""
        # Start with corrupted file
        cache_manager.shots_cache_file.write_text("corrupted")

        # Cache new valid data
        shots = [make_shot_dict(shot="0010")]
        cache_manager.cache_shots(shots)

        # Should be readable now
        result = cache_manager.get_shots_with_ttl()
        assert result is not None
        assert len(result) == 1

    def test_get_shots_with_ttl_accepts_legacy_shots_wrapper(
        self, cache_manager: CacheManager
    ) -> None:
        """Legacy {'shots': [...]} payloads are still readable for compatibility."""
        legacy_payload = {
            "shots": [make_shot_dict(shot="0010")],
            "timestamp": 9999999999.0,
        }
        cache_manager.shots_cache_file.write_text(json.dumps(legacy_payload))

        result = cache_manager.get_shots_with_ttl()
        assert result is not None
        assert len(result) == 1
        assert result[0]["shot"] == "0010"

    def test_clear_cache_removes_files(self, cache_manager: CacheManager) -> None:
        """clear_cache removes all cache files."""
        # Create some cache files
        cache_manager.cache_shots([make_shot_dict()])
        cache_manager.cache_previous_shots([make_shot_dict()])

        cache_manager.clear_cache()

        # Files should not exist or be empty
        assert (
            not cache_manager.shots_cache_file.exists()
            or cache_manager.shots_cache_file.stat().st_size == 0
            or cache_manager.get_shots_with_ttl() is None
        )


# ==============================================================================
# Concurrent Error Recovery Tests
# ==============================================================================


@pytest.mark.integration
class TestConcurrentErrorRecovery:
    """Tests for error recovery under concurrent access."""

    @pytest.fixture
    def cache_manager(self, tmp_path: Path) -> CacheManager:
        """Create CacheManager with isolated cache directory."""
        cache_path = tmp_path / "cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        return CacheManager(cache_dir=cache_path)

    def test_concurrent_reads_of_valid_cache(
        self, cache_manager: CacheManager
    ) -> None:
        """Multiple threads can read cache concurrently."""
        import concurrent.futures
        import threading

        # Write valid cache
        shots = [make_shot_dict(shot=f"{i:04d}") for i in range(100)]
        cache_manager._write_json_cache(cache_manager.shots_cache_file, shots)

        errors: list[Exception] = []
        results: list[int] = []
        lock = threading.Lock()

        def read_cache() -> None:
            try:
                result = cache_manager._read_json_cache(
                    cache_manager.shots_cache_file, check_ttl=False
                )
                with lock:
                    results.append(len(result) if result else 0)
            except Exception as e:
                with lock:
                    errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(read_cache) for _ in range(50)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Errors: {errors}"
        assert all(r == 100 for r in results)  # All reads returned 100 shots

    def test_concurrent_writes_no_corruption(
        self, cache_manager: CacheManager
    ) -> None:
        """Concurrent writes don't produce corrupted files."""
        import concurrent.futures
        import threading

        errors: list[Exception] = []
        lock = threading.Lock()

        def write_cache(thread_id: int) -> None:
            try:
                shots = [make_shot_dict(shot=f"{thread_id:04d}")]
                cache_manager._write_json_cache(cache_manager.shots_cache_file, shots)
            except Exception as e:
                with lock:
                    errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(write_cache, i) for i in range(20)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Errors: {errors}"

        # Final file should be valid (one of the writes won)
        result = cache_manager._read_json_cache(
            cache_manager.shots_cache_file, check_ttl=False
        )
        assert result is not None
        assert len(result) == 1  # One shot from one of the writers
