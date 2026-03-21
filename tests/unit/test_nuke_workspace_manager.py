"""Comprehensive tests for nuke_workspace_manager module.

Tests the NukeWorkspaceManager class for file system operations, version
management, and script discovery following UNIFIED_TESTING_GUIDE patterns.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from nuke.workspace_manager import NukeWorkspaceManager


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def workspace_path(tmp_path: Path) -> str:
    """Create temporary workspace path."""
    return str(tmp_path / "workspace")


@pytest.fixture
def shot_name() -> str:
    """Standard shot name for testing."""
    return "BRX_166_0010"


@pytest.fixture
def script_dir_with_scripts(tmp_path: Path, shot_name: str) -> Path:
    """Create directory with multiple versioned scripts."""
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()

    # Create multiple versions
    versions = [1, 2, 5, 10, 15]
    for version in versions:
        script_file = (
            script_dir / f"{shot_name}_mm-default_PL01_scene_v{version:03d}.nk"
        )
        script_file.write_text(f"# Nuke script version {version}")

    return script_dir


# =============================================================================
# Workspace Script Directory Tests
# =============================================================================


class TestWorkspaceScriptDirectory:
    """Test workspace script directory creation and management."""

    def test_get_workspace_script_directory_default_user(
        self, workspace_path: str
    ) -> None:
        """Test getting script directory with default user from environment."""
        with patch.dict(os.environ, {"USER": "testuser"}):
            script_dir = NukeWorkspaceManager.get_workspace_script_directory(
                workspace_path
            )

        expected = (
            Path(workspace_path)
            / "user"
            / "testuser"
            / "mm"
            / "nuke"
            / "scripts"
            / "mm-default"
            / "scene"
            / "PL01"
        )
        assert script_dir == expected
        assert script_dir.exists()

    def test_get_workspace_script_directory_explicit_user(
        self, workspace_path: str
    ) -> None:
        """Test getting script directory with explicit user."""
        script_dir = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path, user="customuser"
        )

        expected = (
            Path(workspace_path)
            / "user"
            / "customuser"
            / "mm"
            / "nuke"
            / "scripts"
            / "mm-default"
            / "scene"
            / "PL01"
        )
        assert script_dir == expected
        assert script_dir.exists()

    def test_get_workspace_script_directory_custom_params(
        self, workspace_path: str
    ) -> None:
        """Test getting script directory with custom plate and pass names."""
        script_dir = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path,
            user="testuser",
            plate="custom-plate",
            pass_name="PL02",
        )

        expected = (
            Path(workspace_path)
            / "user"
            / "testuser"
            / "mm"
            / "nuke"
            / "scripts"
            / "custom-plate"
            / "scene"
            / "PL02"
        )
        assert script_dir == expected
        assert script_dir.exists()

    def test_get_workspace_script_directory_creates_parents(
        self, workspace_path: str
    ) -> None:
        """Test directory creation with multiple parent levels."""
        script_dir = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path, user="testuser"
        )

        # Verify entire path structure was created
        assert script_dir.exists()
        assert script_dir.parent.exists()  # scene/
        assert script_dir.parent.parent.exists()  # mm-default/
        assert script_dir.parent.parent.parent.exists()  # scripts/
        assert script_dir.parent.parent.parent.parent.exists()  # nuke/

    def test_get_workspace_script_directory_idempotent(
        self, workspace_path: str
    ) -> None:
        """Test calling get_workspace_script_directory multiple times is safe."""
        script_dir1 = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path, user="testuser"
        )
        script_dir2 = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path, user="testuser"
        )

        assert script_dir1 == script_dir2
        assert script_dir1.exists()

    def test_get_workspace_script_directory_permission_error(
        self, tmp_path: Path
    ) -> None:
        """Test handling of permission errors during directory creation."""
        workspace_path = str(tmp_path / "readonly_workspace")
        readonly_dir = tmp_path / "readonly_workspace"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)  # Read-only

        try:
            with pytest.raises((OSError, PermissionError)):
                NukeWorkspaceManager.get_workspace_script_directory(
                    workspace_path, user="testuser"
                )
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)


# =============================================================================
# Find Latest Nuke Script Tests
# =============================================================================


class TestFindLatestNukeScript:
    """Test finding latest versioned Nuke scripts."""

    def test_find_latest_script_single_version(
        self, tmp_path: Path, shot_name: str
    ) -> None:
        """Test finding latest script with single version."""
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()

        # Create single script
        script = script_dir / f"{shot_name}_mm-default_PL01_scene_v001.nk"
        script.write_text("# Nuke script v1")

        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, shot_name)

        assert latest == script

    def test_find_latest_script_multiple_versions(
        self, script_dir_with_scripts: Path, shot_name: str
    ) -> None:
        """Test finding latest script among multiple versions."""
        latest = NukeWorkspaceManager.find_latest_nuke_script(
            script_dir_with_scripts, shot_name
        )

        assert latest is not None
        assert latest.name == f"{shot_name}_mm-default_PL01_scene_v015.nk"

    def test_find_latest_script_non_sequential_versions(
        self, tmp_path: Path, shot_name: str
    ) -> None:
        """Test finding latest with non-sequential version numbers."""
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()

        # Create non-sequential versions
        for version in [1, 3, 7, 12]:
            script = script_dir / f"{shot_name}_mm-default_PL01_scene_v{version:03d}.nk"
            script.write_text(f"# Version {version}")

        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, shot_name)

        assert latest is not None
        assert latest.name.endswith("v012.nk")

    def test_find_latest_script_custom_plate_and_pass(
        self, tmp_path: Path, shot_name: str
    ) -> None:
        """Test finding latest with custom plate and pass names."""
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()

        # Create scripts with custom plate/pass
        for version in [1, 2, 3]:
            script = (
                script_dir / f"{shot_name}_custom-plate_PL02_scene_v{version:03d}.nk"
            )
            script.write_text(f"# Version {version}")

        latest = NukeWorkspaceManager.find_latest_nuke_script(
            script_dir, shot_name, plate="custom-plate", pass_name="PL02"
        )

        assert latest is not None
        assert latest.name == f"{shot_name}_custom-plate_PL02_scene_v003.nk"

    def test_find_latest_script_ignores_other_files(
        self, tmp_path: Path, shot_name: str
    ) -> None:
        """Test that search ignores non-matching files."""
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()

        # Create matching script
        (script_dir / f"{shot_name}_mm-default_PL01_scene_v003.nk").write_text("# v3")

        # Create non-matching files
        (script_dir / "other_file.nk").write_text("# other")
        (script_dir / f"{shot_name}_mm-default_PL01_scene_v002.txt").write_text("# txt")
        (script_dir / "README.md").write_text("# docs")

        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, shot_name)

        assert latest is not None
        assert latest.name.endswith("v003.nk")

    def test_find_latest_script_handles_invalid_version_format(
        self, tmp_path: Path, shot_name: str
    ) -> None:
        """Test finding latest handles files with invalid version formats."""
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()

        # Create script with valid version
        valid_script = script_dir / f"{shot_name}_mm-default_PL01_scene_v005.nk"
        valid_script.write_text("# v5")

        # Create files with invalid version formats
        (script_dir / f"{shot_name}_mm-default_PL01_scene_vXXX.nk").write_text(
            "# invalid"
        )
        (script_dir / f"{shot_name}_mm-default_PL01_scene_v1.nk").write_text(
            "# wrong padding"
        )

        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, shot_name)

        # Should find the valid one and ignore invalid ones
        assert latest == valid_script


# =============================================================================
# Get Next Script Path Tests
# =============================================================================


class TestGetNextScriptPath:
    """Test next version path generation."""

    def test_get_next_script_path_first_version(
        self, tmp_path: Path, shot_name: str
    ) -> None:
        """Test getting next path when no scripts exist."""
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()

        next_path, version = NukeWorkspaceManager.get_next_script_path(
            script_dir, shot_name
        )

        assert version == 1
        assert next_path.name == f"{shot_name}_mm-default_PL01_scene_v001.nk"
        assert next_path.parent == script_dir

    def test_get_next_script_path_after_existing(
        self, script_dir_with_scripts: Path, shot_name: str
    ) -> None:
        """Test getting next path after existing versions."""
        next_path, version = NukeWorkspaceManager.get_next_script_path(
            script_dir_with_scripts, shot_name
        )

        # Latest was v015, next should be v016
        assert version == 16
        assert next_path.name == f"{shot_name}_mm-default_PL01_scene_v016.nk"

    def test_get_next_script_path_custom_plate_and_pass(
        self, tmp_path: Path, shot_name: str
    ) -> None:
        """Test getting next path with custom plate and pass names."""
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()

        # Create existing script with custom params
        (script_dir / f"{shot_name}_custom-plate_PL02_scene_v003.nk").write_text("# v3")

        next_path, version = NukeWorkspaceManager.get_next_script_path(
            script_dir, shot_name, plate="custom-plate", pass_name="PL02"
        )

        assert version == 4
        assert next_path.name == f"{shot_name}_custom-plate_PL02_scene_v004.nk"

    def test_get_next_script_path_formatting(
        self, tmp_path: Path, shot_name: str
    ) -> None:
        """Test version number formatting with padding."""
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()

        next_path, _version = NukeWorkspaceManager.get_next_script_path(
            script_dir, shot_name
        )

        # Check version is zero-padded to 3 digits
        assert "v001.nk" in next_path.name


# =============================================================================
# List All Nuke Scripts Tests
# =============================================================================


class TestListAllNukeScripts:
    """Test listing all Nuke script versions."""

    def test_list_all_scripts_multiple_versions(
        self, workspace_path: str, shot_name: str
    ) -> None:
        """Test listing all scripts returns sorted list."""
        # Create workspace with scripts
        script_dir = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path, user="testuser"
        )

        # Create multiple versions (out of order)
        for version in [5, 1, 10, 3, 7]:
            script = script_dir / f"{shot_name}_mm-default_PL01_scene_v{version:03d}.nk"
            script.write_text(f"# v{version}")

        scripts = NukeWorkspaceManager.list_all_nuke_scripts(
            workspace_path, user="testuser"
        )

        # Should return sorted by version
        assert len(scripts) == 5
        versions = [version for _, version in scripts]
        assert versions == [1, 3, 5, 7, 10]

    def test_list_all_scripts_returns_paths_and_versions(
        self, workspace_path: str, shot_name: str
    ) -> None:
        """Test that list returns tuples of (path, version)."""
        script_dir = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path, user="testuser"
        )

        # Create a few scripts
        for version in [1, 2, 3]:
            script = script_dir / f"{shot_name}_mm-default_PL01_scene_v{version:03d}.nk"
            script.write_text(f"# v{version}")

        scripts = NukeWorkspaceManager.list_all_nuke_scripts(
            workspace_path, user="testuser"
        )

        # Verify structure
        for path, version in scripts:
            assert isinstance(path, Path)
            assert isinstance(version, int)
            assert path.exists()
            assert path.suffix == ".nk"

    def test_list_all_scripts_ignores_non_nuke_files(
        self, workspace_path: str, shot_name: str
    ) -> None:
        """Test listing ignores non-Nuke files."""
        script_dir = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path, user="testuser"
        )

        # Create Nuke scripts
        (script_dir / f"{shot_name}_mm-default_PL01_scene_v001.nk").write_text("# v1")
        (script_dir / f"{shot_name}_mm-default_PL01_scene_v002.nk").write_text("# v2")

        # Create non-Nuke files
        (script_dir / "README.txt").write_text("# docs")
        (script_dir / "backup.bak").write_text("# backup")

        scripts = NukeWorkspaceManager.list_all_nuke_scripts(
            workspace_path, user="testuser"
        )

        # Should only include .nk files
        assert len(scripts) == 2

    def test_list_all_scripts_ignores_invalid_version_format(
        self, workspace_path: str, shot_name: str
    ) -> None:
        """Test listing ignores files without valid version numbers."""
        script_dir = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path, user="testuser"
        )

        # Create valid versioned script
        (script_dir / f"{shot_name}_mm-default_PL01_scene_v001.nk").write_text("# v1")

        # Create files with invalid version formats
        (script_dir / "script_without_version.nk").write_text("# no version")
        (script_dir / "script_vXXX.nk").write_text("# invalid")

        scripts = NukeWorkspaceManager.list_all_nuke_scripts(
            workspace_path, user="testuser"
        )

        # Should only include validly versioned files
        assert len(scripts) == 1
        assert scripts[0][1] == 1

    def test_list_all_scripts_custom_plate_and_pass(
        self, workspace_path: str, shot_name: str
    ) -> None:
        """Test listing scripts with custom plate and pass names."""
        script_dir = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path,
            user="testuser",
            plate="custom-plate",
            pass_name="PL02",
        )

        # Create scripts with custom params
        for version in [1, 2]:
            script = (
                script_dir / f"{shot_name}_custom-plate_PL02_scene_v{version:03d}.nk"
            )
            script.write_text(f"# v{version}")

        scripts = NukeWorkspaceManager.list_all_nuke_scripts(
            workspace_path,
            user="testuser",
            plate="custom-plate",
            pass_name="PL02",
        )

        assert len(scripts) == 2


# =============================================================================
# Edge Cases and Integration Tests
# =============================================================================


class TestEdgeCasesAndIntegration:
    """Test edge cases and integration scenarios."""

    def test_full_workflow_first_script(
        self, workspace_path: str, shot_name: str
    ) -> None:
        """Test complete workflow for creating first script."""
        # Get directory (should create it)
        script_dir = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path, user="testuser"
        )
        assert script_dir.exists()

        # No scripts should exist yet
        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, shot_name)
        assert latest is None

        # Get next version path
        next_path, version = NukeWorkspaceManager.get_next_script_path(
            script_dir, shot_name
        )
        assert version == 1

        # Create the script
        next_path.write_text("# First script")

        # Verify it's found as latest
        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, shot_name)
        assert latest == next_path

    def test_full_workflow_next_version(
        self, workspace_path: str, shot_name: str
    ) -> None:
        """Test complete workflow for creating next version."""
        # Setup: create workspace with existing script
        script_dir = NukeWorkspaceManager.get_workspace_script_directory(
            workspace_path, user="testuser"
        )
        existing_script = script_dir / f"{shot_name}_mm-default_PL01_scene_v005.nk"
        existing_script.write_text("# v5")

        # Find latest
        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, shot_name)
        assert latest == existing_script

        # Get next version
        next_path, version = NukeWorkspaceManager.get_next_script_path(
            script_dir, shot_name
        )
        assert version == 6

        # Create next version
        next_path.write_text("# v6")

        # Verify new latest
        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, shot_name)
        assert latest == next_path

        # List all should show both
        scripts = NukeWorkspaceManager.list_all_nuke_scripts(
            workspace_path, user="testuser"
        )
        assert len(scripts) == 2
        assert [v for _, v in scripts] == [5, 6]

    def test_empty_shot_name_handling(self, tmp_path: Path) -> None:
        """Test behavior with empty shot name."""
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()

        # Should handle empty shot name gracefully
        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, "")
        assert latest is None

    def test_shot_name_with_special_characters(self, tmp_path: Path) -> None:
        """Test shot names with special regex characters."""
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()

        shot_name = "SHOT.TEST_001"  # Contains dots
        script = script_dir / f"{shot_name}_mm-default_PL01_scene_v001.nk"
        script.write_text("# test")

        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, shot_name)

        assert latest == script

    def test_very_high_version_numbers(self, tmp_path: Path, shot_name: str) -> None:
        """Test handling of high version numbers."""
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()

        # Create scripts with high version numbers
        high_version = 999
        script = (
            script_dir / f"{shot_name}_mm-default_PL01_scene_v{high_version:03d}.nk"
        )
        script.write_text(f"# v{high_version}")

        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, shot_name)

        assert latest == script

        # Get next version
        _next_path, version = NukeWorkspaceManager.get_next_script_path(
            script_dir, shot_name
        )
        assert version == 1000

    @pytest.mark.parametrize(
        "use_nonexistent_dir",
        [
            pytest.param(False, id="empty_directory"),
            pytest.param(True, id="nonexistent_directory"),
        ],
    )
    def test_empty_or_nonexistent_dir_returns_no_results(
        self, tmp_path: Path, shot_name: str, use_nonexistent_dir: bool
    ) -> None:
        """Test that empty and nonexistent dirs both return no results."""
        if use_nonexistent_dir:
            script_dir = tmp_path / "nonexistent"
            workspace_path = str(tmp_path / "nonexistent_workspace")
        else:
            script_dir = tmp_path / "scripts"
            script_dir.mkdir()
            workspace_path = str(tmp_path / "workspace")

        # find_latest_nuke_script returns None
        latest = NukeWorkspaceManager.find_latest_nuke_script(script_dir, shot_name)
        assert latest is None

        # list_all_nuke_scripts returns empty list
        scripts = NukeWorkspaceManager.list_all_nuke_scripts(
            workspace_path, user="testuser"
        )
        assert scripts == []
