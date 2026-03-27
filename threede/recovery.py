"""Recovery manager for 3DE crash files.

This module provides functionality to detect, recover, and archive
3DE crash files that are created when 3D Equalizer crashes during
editing. Crash files follow the pattern: {basename}_crashsave{numbers}.3de

Example:
    Original: scene_v010.3de
    Crash file: scene_v010_crashsave3750186.3de
    Recovery: scene_v011.3de (promoted to next version)
    Archive: scene_v010_crashsave_recovered_20250102_143022.3de

"""

from __future__ import annotations

# Standard library imports
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, NamedTuple

# Local application imports
from threede.latest_finder import ThreeDELatestFinder
from version_mixin import VersionHandlingMixin


class CrashFileInfo(NamedTuple):
    """Information about a detected crash file.

    Attributes:
        crash_path: Full path to the crash file
        base_name: Original scene name without crash suffix
        current_version: Version number of the crashed scene
        recovery_name: Suggested name for recovered file (next version)
        modification_time: File modification timestamp
        file_size: File size in bytes

    """

    crash_path: Path
    base_name: str
    current_version: int
    recovery_name: str
    modification_time: datetime
    file_size: int


class ThreeDERecoveryManager(VersionHandlingMixin):
    """Manager for recovering crashed 3DE scene files.

    This class handles:
    - Detection of crash files matching pattern *_v{N}_crashsave{numbers}.3de
    - Promotion of crash files to next version (v{N} → v{N+1})
    - Archiving of crash files with timestamp suffix
    - Finding latest crash file when multiple exist

    Usage:
        manager = ThreeDERecoveryManager()

        # Find crash files in workspace
        crash_files = manager.find_crash_files(workspace_path)

        # Recover a crash file
        if crash_files:
            info = crash_files[0]
            recovered_path = manager.recover_crash_file(info)
            print(f"Recovered to: {recovered_path}")
    """

    # Pattern to match crash files: scene_v010_crashsave3750186.3de
    # Captures: (base_name)(version)(crashsave_suffix)
    CRASH_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(.+_v(\d{3}))_crashsave\d+\.3de$"
    )

    # Pattern to match regular 3DE scene files for version checking.
    # Imported from ThreeDELatestFinder — single canonical definition.
    VERSION_PATTERN: ClassVar[re.Pattern[str]] = ThreeDELatestFinder.VERSION_PATTERN

    def find_crash_files(
        self,
        workspace_path: str | Path,
        recursive: bool = True,
    ) -> list[CrashFileInfo]:
        """Find all crash files in a workspace.

        Searches for files matching the pattern *_v{N}_crashsave{numbers}.3de
        in the given workspace directory.

        Args:
            workspace_path: Path to the shot workspace
            recursive: If True, search subdirectories recursively

        Returns:
            List of CrashFileInfo objects for detected crash files,
            sorted by modification time (newest first)

        """
        workspace = Path(workspace_path)
        if not workspace.exists():
            self.logger.debug(f"Workspace does not exist: {workspace_path}")
            return []

        crash_files: list[CrashFileInfo] = []

        # Search pattern
        pattern = "**/*_crashsave*.3de" if recursive else "*_crashsave*.3de"

        for crash_file in workspace.glob(pattern):
            if not crash_file.is_file():
                continue

            # Check if filename matches crash pattern
            match = self.CRASH_PATTERN.match(crash_file.name)
            if not match:
                continue

            base_name = match.group(1)  # e.g., "scene_v010"
            version_str = match.group(2)  # e.g., "010"
            current_version = int(version_str)

            # Extract scene base without version for building recovery name
            # e.g., "scene_v010" -> "scene"
            scene_base = base_name.rsplit("_v", 1)[0]

            # Get all existing scene files in same directory to find next version
            scene_dir = crash_file.parent
            existing_files = list(scene_dir.glob(f"{scene_base}_v*.3de"))

            # Filter out crash files from version calculation
            regular_files = [
                f for f in existing_files if not self.CRASH_PATTERN.match(f.name)
            ]

            # Calculate next available version
            next_version = self._find_next_version(regular_files)
            next_version_str = self._format_version_string(next_version)

            # Build recovery name using scene_base
            recovery_name = f"{scene_base}_v{next_version_str}.3de"

            # Get file metadata
            stat = crash_file.stat()
            mod_time = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

            info = CrashFileInfo(
                crash_path=crash_file,
                base_name=base_name,
                current_version=current_version,
                recovery_name=recovery_name,
                modification_time=mod_time,
                file_size=stat.st_size,
            )

            crash_files.append(info)
            self.logger.debug(
                f"Found crash file: {crash_file.name} (v{current_version:03d} → v{next_version:03d})"
            )

        # Sort by modification time (newest first)
        crash_files.sort(key=lambda x: x.modification_time, reverse=True)

        self.logger.info(f"Found {len(crash_files)} crash file(s) in {workspace_path}")
        return crash_files

    def get_latest_crash_file(
        self,
        crash_files: list[CrashFileInfo],
    ) -> CrashFileInfo | None:
        """Get the most recent crash file from a list.

        Args:
            crash_files: List of CrashFileInfo objects

        Returns:
            The most recent crash file info, or None if list is empty

        """
        if not crash_files:
            return None

        # List should already be sorted by modification_time (newest first)
        # but we'll sort again to be safe
        sorted_files = sorted(
            crash_files,
            key=lambda x: x.modification_time,
            reverse=True,
        )

        latest = sorted_files[0]
        self.logger.info(
            f"Latest crash file: {latest.crash_path.name} (modified: {latest.modification_time})"
        )
        return latest

    def recover_crash_file(
        self,
        crash_info: CrashFileInfo,
    ) -> Path:
        """Recover a crash file by promoting it to the next version.

        This performs two operations:
        1. Rename crash file to next version (e.g., v010_crashsave → v011.3de)
        2. Archive original crash file with timestamp

        Args:
            crash_info: Information about the crash file to recover

        Returns:
            Path to the recovered file (new version)

        Raises:
            FileNotFoundError: If crash file doesn't exist
            FileExistsError: If target recovery file already exists

        """
        crash_path = crash_info.crash_path

        if not crash_path.exists():
            msg = f"Crash file not found: {crash_path}"
            raise FileNotFoundError(msg)

        # Target recovery path
        recovery_path = crash_path.parent / crash_info.recovery_name

        if recovery_path.exists():
            msg = f"Recovery target already exists: {recovery_path}\nPlease remove or rename the existing file first."
            raise FileExistsError(msg)

        # Rename crash file to recovery version
        self.logger.info(
            f"Recovering crash file: {crash_path.name} → {recovery_path.name}"
        )
        _ = crash_path.rename(recovery_path)

        # Archive notification (actual archiving happens separately)
        self.logger.info(f"Successfully recovered to: {recovery_path}")

        return recovery_path

    def archive_crash_file(
        self,
        crash_info: CrashFileInfo,
    ) -> Path:
        """Archive a crash file with timestamp suffix.

        Renames the crash file to indicate it was recovered:
        scene_v010_crashsave3750186.3de →
        scene_v010_crashsave_recovered_20250102_143022.3de

        Args:
            crash_info: Information about the crash file to archive

        Returns:
            Path to the archived file

        Raises:
            FileNotFoundError: If crash file doesn't exist

        """
        crash_path = crash_info.crash_path

        if not crash_path.exists():
            msg = f"Crash file not found: {crash_path}"
            raise FileNotFoundError(msg)

        # Generate timestamp suffix
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")

        # Build archive name
        # From: scene_v010_crashsave3750186.3de
        # To:   scene_v010_crashsave_recovered_20250102_143022.3de
        stem = crash_path.stem  # scene_v010_crashsave3750186

        # Remove the random numbers from crashsave suffix
        if "_crashsave" in stem:
            base_stem = stem.split("_crashsave")[0]  # scene_v010
            archive_name = f"{base_stem}_crashsave_recovered_{timestamp}.3de"
        else:
            # Fallback if pattern doesn't match
            archive_name = f"{stem}_recovered_{timestamp}.3de"

        archive_path = crash_path.parent / archive_name

        self.logger.info(f"Archiving crash file: {crash_path.name} → {archive_name}")
        _ = crash_path.rename(archive_path)

        return archive_path

    def recover_and_archive(
        self,
        crash_info: CrashFileInfo,
    ) -> tuple[Path, Path]:
        """Recover a crash file and archive the original in one operation.

        This is a convenience method that combines:
        1. Copy crash file to next version
        2. Archive original crash file with timestamp

        Args:
            crash_info: Information about the crash file to recover

        Returns:
            Tuple of (recovered_path, archived_path)

        Raises:
            FileNotFoundError: If crash file doesn't exist
            FileExistsError: If target recovery file already exists

        """
        import shutil

        crash_path = crash_info.crash_path

        if not crash_path.exists():
            msg = f"Crash file not found: {crash_path}"
            raise FileNotFoundError(msg)

        recovery_path = crash_path.parent / crash_info.recovery_name

        if recovery_path.exists():
            msg = f"Recovery target already exists: {recovery_path}\nPlease remove or rename the existing file first."
            raise FileExistsError(msg)

        # Step 1: Copy crash file to recovery version
        self.logger.info(
            f"Recovering crash file: {crash_path.name} → {recovery_path.name}"
        )
        _ = shutil.copy2(crash_path, recovery_path)

        # Update mtime to current time so recovered file is detected as "latest"
        # (copy2 preserves old mtime from crash file, which may be days/weeks old)
        os.utime(recovery_path, None)

        # Step 2: Archive the original crash file
        archived_path = self.archive_crash_file(crash_info)

        self.logger.info(
            f"Recovery complete: {recovery_path.name}\nArchived: {archived_path.name}"
        )

        return (recovery_path, archived_path)
