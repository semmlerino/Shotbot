"""End-to-end tests using real components instead of test doubles.

These tests verify that the application works correctly with real:
- Filesystem operations (not mocked)
- Cache persistence (real JSON files)
- Settings persistence (real QSettings)
- Path validation (real filesystem checks)

The goal is to catch integration bugs that mocks might hide.

Run these tests serially for most reliable results:
    pytest tests/integration/test_e2e_real_components.py -n 0 -v
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest


# ==============================================================================
# E2E Cache Manager Tests
# ==============================================================================


class TestCacheManagerE2E:
    """End-to-end tests for ShotDataCache with real filesystem."""

    @pytest.fixture
    def real_cache_dir(self, tmp_path: Path) -> Path:
        """Create a real temporary cache directory."""
        cache_dir = tmp_path / "shotbot_e2e_cache"
        cache_dir.mkdir()
        return cache_dir

    @pytest.fixture
    def real_cache_manager(
        self, real_cache_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> ShotDataCache:
        """Create a ShotDataCache with real filesystem operations."""
        # Point to our test cache directory
        monkeypatch.setenv("SHOTBOT_TEST_CACHE_DIR", str(real_cache_dir))

        from cache.shot_cache import ShotDataCache

        return ShotDataCache(real_cache_dir)

    def test_shots_cache_persists_to_disk(self, real_cache_manager: ShotDataCache) -> None:
        """Verify shot data is actually written to disk."""
        # Create test shot data
        shots = [
            {"show": "TESTSHOW", "sequence": "SQ010", "shot": "SH0010"},
            {"show": "TESTSHOW", "sequence": "SQ010", "shot": "SH0020"},
        ]

        # Cache the shots
        real_cache_manager.cache_shots(shots)

        # Verify cache file exists on disk
        cache_file = real_cache_manager.shots_cache_file
        assert cache_file.exists(), "Cache file should be created on disk"

        # Verify file contains correct data
        with cache_file.open() as f:
            cached_data = json.load(f)

        # Cache format: {"data": [...], "cached_at": "..."}
        assert "data" in cached_data
        assert len(cached_data["data"]) == 2

    def test_shots_cache_survives_manager_recreation(
        self, real_cache_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify cached shots survive creating a new ShotDataCache instance."""
        monkeypatch.setenv("SHOTBOT_TEST_CACHE_DIR", str(real_cache_dir))

        from cache.shot_cache import ShotDataCache

        # First manager caches shots
        manager1 = ShotDataCache(real_cache_dir)
        shots = [{"show": "SURVIVALTEST", "sequence": "SQ001", "shot": "SH0001"}]
        manager1.cache_shots(shots)

        # Create new manager pointing to same directory
        manager2 = ShotDataCache(real_cache_dir)

        # New manager should find cached shots
        cached = manager2.get_shots_with_ttl()
        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["show"] == "SURVIVALTEST"

    def test_cache_ttl_expiration_real_time(
        self, real_cache_manager: ShotDataCache
    ) -> None:
        """Verify TTL expiration works with real time passage."""
        shots = [{"show": "TTLTEST", "sequence": "SQ001", "shot": "SH0001"}]
        real_cache_manager.cache_shots(shots)

        # TTL is checked via file mtime, not JSON content
        cache_file = real_cache_manager.shots_cache_file

        # Set file mtime to 1 hour ago (beyond default 30min TTL)
        old_time = time.time() - 3600
        os.utime(cache_file, (old_time, old_time))

        # Cache should now be expired
        cached = real_cache_manager.get_shots_with_ttl()
        assert cached is None, "Expired cache should return None"

    def test_previous_shots_cache_replacement(
        self, real_cache_manager: ShotDataCache
    ) -> None:
        """Verify previous shots cache replaces old data on write."""
        # First batch
        batch1 = [{"show": "SHOW1", "sequence": "SQ001", "shot": "SH0001"}]
        real_cache_manager.cache_previous_shots(batch1)

        # Verify first batch cached
        cached1 = real_cache_manager.get_cached_previous_shots()
        assert cached1 is not None
        assert len(cached1) == 1
        assert cached1[0]["show"] == "SHOW1"

        # Second batch replaces first
        batch2 = [{"show": "SHOW2", "sequence": "SQ002", "shot": "SH0002"}]
        real_cache_manager.cache_previous_shots(batch2)

        # Should only have second batch
        cached2 = real_cache_manager.get_cached_previous_shots()
        assert cached2 is not None
        assert len(cached2) == 1
        assert cached2[0]["show"] == "SHOW2"


# ==============================================================================
# E2E Filesystem Discovery Tests
# ==============================================================================


class TestFilesystemDiscoveryE2E:
    """End-to-end tests for filesystem discovery operations."""

    @pytest.fixture
    def mock_vfx_structure(self, tmp_path: Path) -> Path:
        """Create a realistic VFX directory structure."""
        base = tmp_path / "shotbot_e2e_vfx"
        base.mkdir()

        # Create show/sequence/shot structure
        shows_dir = base / "shows"
        shows_dir.mkdir()

        for show in ["TESTSHOW", "ANOTHERSHOW"]:
            show_dir = shows_dir / show / "shots"
            for seq in ["SQ010", "SQ020"]:
                for shot_num in range(10, 50, 10):
                    shot_dir = show_dir / seq / f"SH{shot_num:04d}"
                    shot_dir.mkdir(parents=True)

                    # Create some files
                    (shot_dir / "plate").mkdir()
                    (shot_dir / "plate" / "turnover.exr").touch()

        return base

    def test_discover_shots_in_real_directory(
        self, mock_vfx_structure: Path
    ) -> None:
        """Verify shot discovery works with real filesystem."""
        from path_validators import PathValidators

        shows_dir = mock_vfx_structure / "shows" / "TESTSHOW" / "shots"

        # Use PathValidators to check paths exist
        assert PathValidators.validate_path_exists(shows_dir, "shows dir")

        # Count actual sequences
        sequences = list(shows_dir.iterdir())
        assert len(sequences) == 2

        # Count shots per sequence
        for seq in sequences:
            shots = list(seq.iterdir())
            assert len(shots) == 4  # SH0010, SH0020, SH0030, SH0040


# ==============================================================================
# E2E Settings Persistence Tests
# ==============================================================================


class TestSettingsPersistenceE2E:
    """End-to-end tests for settings persistence."""

    @pytest.fixture
    def isolated_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Isolate QSettings to test directory."""
        from PySide6.QtCore import QSettings, QStandardPaths

        QStandardPaths.setTestModeEnabled(True)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            str(tmp_path),
        )

    def test_settings_roundtrip(self, isolated_settings: None) -> None:
        """Verify settings can be saved and loaded."""
        from PySide6.QtCore import QSettings

        settings = QSettings("ShotBot", "E2ETest")

        # Write settings
        settings.setValue("test/string_value", "hello world")
        settings.setValue("test/int_value", 42)
        settings.setValue("test/bool_value", True)
        settings.setValue("test/list_value", ["a", "b", "c"])
        settings.sync()

        # Create new settings instance
        settings2 = QSettings("ShotBot", "E2ETest")

        # Read back and verify
        assert settings2.value("test/string_value") == "hello world"
        assert settings2.value("test/int_value", type=int) == 42
        assert settings2.value("test/bool_value", type=bool) is True


# ==============================================================================
# E2E Path Validation Tests
# ==============================================================================


class TestPathValidationE2E:
    """End-to-end tests for path validation."""

    def test_validate_nonexistent_path(self) -> None:
        """Verify validation correctly identifies non-existent paths."""
        from path_validators import PathValidators

        nonexistent = Path("/this/path/definitely/does/not/exist/12345")
        result = PathValidators.validate_path_exists(nonexistent, "test")
        assert result is False

    def test_validate_existing_path(self, tmp_path: Path) -> None:
        """Verify validation correctly identifies existing paths."""
        from path_validators import PathValidators

        existing = tmp_path / "real_dir"
        existing.mkdir()

        result = PathValidators.validate_path_exists(existing, "test")
        assert result is True

    def test_validate_symlink(self, tmp_path: Path) -> None:
        """Verify validation works with symlinks."""
        from path_validators import PathValidators

        # Create real directory
        real_dir = tmp_path / "real"
        real_dir.mkdir()

        # Create symlink
        link = tmp_path / "link"
        link.symlink_to(real_dir)

        # Both should validate as existing
        assert PathValidators.validate_path_exists(real_dir, "real")
        assert PathValidators.validate_path_exists(link, "link")


