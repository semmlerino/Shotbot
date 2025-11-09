"""Unit tests for 3DE crash file recovery manager."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from threede_recovery import CrashFileInfo, ThreeDERecoveryManager


class TestThreeDERecoveryManager:
    """Test suite for ThreeDERecoveryManager."""

    @pytest.fixture
    def recovery_manager(self) -> ThreeDERecoveryManager:
        """Create a recovery manager instance."""
        return ThreeDERecoveryManager()

    @pytest.fixture
    def temp_workspace(self, tmp_path: Path) -> Path:
        """Create a temporary workspace with crash files."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create a 3DE scene directory structure
        scene_dir = workspace / "user" / "testuser" / "mm" / "3de" / "mm-default" / "scenes" / "scene" / "plate01"
        scene_dir.mkdir(parents=True)

        # Create some regular scene files
        (scene_dir / "scene_v001.3de").write_text("3de scene v001")
        (scene_dir / "scene_v002.3de").write_text("3de scene v002")

        # Create crash files
        crash1 = scene_dir / "scene_v002_crashsave123456.3de"
        crash1.write_text("crash save 1")

        crash2 = scene_dir / "scene_v002_crashsave789012.3de"
        crash2.write_text("crash save 2")

        # Make crash2 newer with explicit mtime skew (filesystems can coalesce sub-ms writes)
        import time

        timestamp = time.time()
        os.utime(crash1, (timestamp, timestamp))
        crash2.write_text("crash save 2 newer")
        os.utime(crash2, (timestamp + 1, timestamp + 1))

        return workspace

    def test_crash_pattern_matching(self, recovery_manager: ThreeDERecoveryManager) -> None:
        """Test that crash file pattern correctly matches crash files."""
        pattern = recovery_manager.CRASH_PATTERN

        # Should match
        assert pattern.match("scene_v010_crashsave3750186.3de")
        assert pattern.match("DB_271_1760_mm_default_FG01_scene_v010_crashsave3750186.3de")
        assert pattern.match("shot_v001_crashsave12345.3de")

        # Should not match
        assert not pattern.match("scene_v010.3de")
        assert not pattern.match("scene_v010_backup.3de")
        assert not pattern.match("scene_v010_autosave.3de")
        assert not pattern.match("crashsave123.3de")

    def test_version_extraction_from_regular_scene(self, recovery_manager: ThreeDERecoveryManager) -> None:
        """Test extracting version from regular scene file names."""
        # Extract from regular scene files (not crash files)
        version = recovery_manager._extract_version(
            Path("scene_v010.3de")
        )
        assert version == 10

        version = recovery_manager._extract_version(
            Path("DB_271_1760_mm_default_FG01_scene_v042.3de")
        )
        assert version == 42

    def test_find_crash_files(self, recovery_manager: ThreeDERecoveryManager, temp_workspace: Path) -> None:
        """Test finding crash files in workspace."""
        crash_files = recovery_manager.find_crash_files(temp_workspace, recursive=True)

        assert len(crash_files) == 2
        assert all(isinstance(cf, CrashFileInfo) for cf in crash_files)

        # Files should be sorted by modification time (newest first)
        assert crash_files[0].crash_path.name == "scene_v002_crashsave789012.3de"
        assert crash_files[1].crash_path.name == "scene_v002_crashsave123456.3de"

    def test_find_crash_files_no_results(self, recovery_manager: ThreeDERecoveryManager, tmp_path: Path) -> None:
        """Test finding crash files when none exist."""
        empty_workspace = tmp_path / "empty"
        empty_workspace.mkdir()

        crash_files = recovery_manager.find_crash_files(empty_workspace, recursive=True)
        assert len(crash_files) == 0

    def test_find_crash_files_nonexistent_workspace(self, recovery_manager: ThreeDERecoveryManager) -> None:
        """Test finding crash files in nonexistent workspace."""
        crash_files = recovery_manager.find_crash_files("/nonexistent/path", recursive=True)
        assert len(crash_files) == 0

    def test_crash_file_info_structure(self, recovery_manager: ThreeDERecoveryManager, temp_workspace: Path) -> None:
        """Test that CrashFileInfo contains correct information."""
        crash_files = recovery_manager.find_crash_files(temp_workspace, recursive=True)
        assert len(crash_files) > 0

        crash_info = crash_files[0]

        # Check structure
        assert crash_info.crash_path.exists()
        assert crash_info.base_name == "scene_v002"
        assert crash_info.current_version == 2
        assert crash_info.recovery_name == "scene_v003.3de"  # Next available version
        assert isinstance(crash_info.modification_time, datetime)
        assert crash_info.file_size > 0

    def test_recovery_name_calculation(self, recovery_manager: ThreeDERecoveryManager, temp_workspace: Path) -> None:
        """Test that recovery name is calculated correctly."""
        crash_files = recovery_manager.find_crash_files(temp_workspace, recursive=True)
        assert len(crash_files) > 0

        # v002 crashes should recover to v003 (next available)
        for crash_info in crash_files:
            if "v002" in crash_info.base_name:
                assert crash_info.recovery_name == "scene_v003.3de"

    def test_get_latest_crash_file(self, recovery_manager: ThreeDERecoveryManager, temp_workspace: Path) -> None:
        """Test getting the latest crash file from a list."""
        crash_files = recovery_manager.find_crash_files(temp_workspace, recursive=True)
        assert len(crash_files) > 0

        latest = recovery_manager.get_latest_crash_file(crash_files)
        assert latest is not None
        assert latest.crash_path.name == "scene_v002_crashsave789012.3de"

    def test_get_latest_crash_file_empty_list(self, recovery_manager: ThreeDERecoveryManager) -> None:
        """Test getting latest crash file from empty list."""
        latest = recovery_manager.get_latest_crash_file([])
        assert latest is None

    def test_recover_crash_file(self, recovery_manager: ThreeDERecoveryManager, temp_workspace: Path) -> None:
        """Test recovering a crash file to next version."""
        crash_files = recovery_manager.find_crash_files(temp_workspace, recursive=True)
        assert len(crash_files) > 0

        crash_info = crash_files[0]
        original_path = crash_info.crash_path

        # Recover the file
        recovered_path = recovery_manager.recover_crash_file(crash_info)

        # Check that recovered file was created
        assert recovered_path.exists()
        assert recovered_path.name == crash_info.recovery_name

        # Check that original crash file was renamed (not deleted)
        assert not original_path.exists()

    def test_recover_crash_file_not_found(self, recovery_manager: ThreeDERecoveryManager, tmp_path: Path) -> None:
        """Test recovering a nonexistent crash file."""
        fake_crash = CrashFileInfo(
            crash_path=tmp_path / "nonexistent_crashsave123.3de",
            base_name="nonexistent_v001",
            current_version=1,
            recovery_name="nonexistent_v002.3de",
            modification_time=datetime.now(tz=UTC),
            file_size=0,
        )

        with pytest.raises(FileNotFoundError):
            recovery_manager.recover_crash_file(fake_crash)

    def test_recover_crash_file_target_exists(self, recovery_manager: ThreeDERecoveryManager, temp_workspace: Path) -> None:
        """Test recovering when target file already exists."""
        crash_files = recovery_manager.find_crash_files(temp_workspace, recursive=True)
        assert len(crash_files) > 0

        crash_info = crash_files[0]

        # Create the target file
        target_path = crash_info.crash_path.parent / crash_info.recovery_name
        target_path.write_text("existing file")

        with pytest.raises(FileExistsError):
            recovery_manager.recover_crash_file(crash_info)

    def test_archive_crash_file(self, recovery_manager: ThreeDERecoveryManager, temp_workspace: Path) -> None:
        """Test archiving a crash file with timestamp."""
        crash_files = recovery_manager.find_crash_files(temp_workspace, recursive=True)
        assert len(crash_files) > 0

        crash_info = crash_files[0]
        original_path = crash_info.crash_path

        # Archive the file
        archived_path = recovery_manager.archive_crash_file(crash_info)

        # Check that archived file was created
        assert archived_path.exists()
        assert "_crashsave_recovered_" in archived_path.name
        assert archived_path.suffix == ".3de"

        # Check that original crash file no longer exists
        assert not original_path.exists()

    def test_archive_crash_file_not_found(self, recovery_manager: ThreeDERecoveryManager, tmp_path: Path) -> None:
        """Test archiving a nonexistent crash file."""
        fake_crash = CrashFileInfo(
            crash_path=tmp_path / "nonexistent_crashsave123.3de",
            base_name="nonexistent_v001",
            current_version=1,
            recovery_name="nonexistent_v002.3de",
            modification_time=datetime.now(tz=UTC),
            file_size=0,
        )

        with pytest.raises(FileNotFoundError):
            recovery_manager.archive_crash_file(fake_crash)

    def test_recover_and_archive(self, recovery_manager: ThreeDERecoveryManager, temp_workspace: Path) -> None:
        """Test combined recover and archive operation."""
        crash_files = recovery_manager.find_crash_files(temp_workspace, recursive=True)
        assert len(crash_files) > 0

        crash_info = crash_files[0]
        original_content = crash_info.crash_path.read_text()

        # Perform recovery and archiving
        recovered_path, archived_path = recovery_manager.recover_and_archive(crash_info)

        # Check recovered file
        assert recovered_path.exists()
        assert recovered_path.name == crash_info.recovery_name
        assert recovered_path.read_text() == original_content

        # Check archived file
        assert archived_path.exists()
        assert "_crashsave_recovered_" in archived_path.name
        assert archived_path.read_text() == original_content

        # Check original crash file is gone
        assert not crash_info.crash_path.exists()

    def test_recover_and_archive_target_exists(self, recovery_manager: ThreeDERecoveryManager, temp_workspace: Path) -> None:
        """Test recover_and_archive when target file already exists."""
        crash_files = recovery_manager.find_crash_files(temp_workspace, recursive=True)
        assert len(crash_files) > 0

        crash_info = crash_files[0]

        # Create the target file
        target_path = crash_info.crash_path.parent / crash_info.recovery_name
        target_path.write_text("existing file")

        with pytest.raises(FileExistsError):
            recovery_manager.recover_and_archive(crash_info)

    def test_multiple_crash_files_same_scene(self, recovery_manager: ThreeDERecoveryManager, tmp_path: Path) -> None:
        """Test handling multiple crash files for the same scene."""
        scene_dir = tmp_path / "scene_dir"
        scene_dir.mkdir()

        # Create regular file
        (scene_dir / "scene_v010.3de").write_text("regular scene")

        # Create multiple crash files
        (scene_dir / "scene_v010_crashsave111111.3de").write_text("crash 1")
        (scene_dir / "scene_v010_crashsave222222.3de").write_text("crash 2")
        (scene_dir / "scene_v010_crashsave333333.3de").write_text("crash 3")

        crash_files = recovery_manager.find_crash_files(scene_dir, recursive=False)
        assert len(crash_files) == 3

        # All should have same base name and current version
        for crash_info in crash_files:
            assert crash_info.base_name == "scene_v010"
            assert crash_info.current_version == 10
            assert crash_info.recovery_name == "scene_v011.3de"

    def test_crash_file_with_complex_name(self, recovery_manager: ThreeDERecoveryManager, tmp_path: Path) -> None:
        """Test crash file with complex VFX-style naming."""
        scene_dir = tmp_path / "complex"
        scene_dir.mkdir()

        # Create regular scene files first (v001-v010)
        for i in range(1, 11):
            regular_file = scene_dir / f"DB_271_1760_mm_default_FG01_scene_v{i:03d}.3de"
            regular_file.write_text(f"scene v{i:03d}")

        # Create complex named crash file
        crash_file = scene_dir / "DB_271_1760_mm_default_FG01_scene_v010_crashsave3750186.3de"
        crash_file.write_text("complex crash")

        crash_files = recovery_manager.find_crash_files(scene_dir, recursive=False)
        assert len(crash_files) == 1

        crash_info = crash_files[0]
        assert crash_info.current_version == 10
        assert crash_info.recovery_name == "DB_271_1760_mm_default_FG01_scene_v011.3de"

    def test_version_pattern_override(self, recovery_manager: ThreeDERecoveryManager) -> None:
        """Test that VERSION_PATTERN correctly matches 3DE files."""
        pattern = recovery_manager.VERSION_PATTERN

        # Should match
        assert pattern.search("scene_v001.3de")
        assert pattern.search("scene_v010.3de")
        assert pattern.search("scene_v999.3de")

        # Should not match
        assert not pattern.search("scene_v001.ma")
        assert not pattern.search("scene_v001.nk")
        assert not pattern.search("scene_001.3de")
