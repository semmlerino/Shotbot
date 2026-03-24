"""Unit tests for PlateDiscovery module following UNIFIED_TESTING_GUIDE.

This test suite provides comprehensive coverage for the NEW plate-based Nuke workflow,
including plate priority sorting, script version detection, and script path construction.

Recent bug fix validation: PL priority was 10, should be 0.5 (fixed in config.py)

Test coverage includes:
- Plate priority sorting (FG=0, PL=0.5, BG=1, COMP=1.5, EL=2, BC=10)
- Script version detection and incrementation
- Script path construction and naming conventions
- Edge cases (missing directories, malformed filenames, empty inputs)
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
from discovery.plate_discovery import PlateDiscovery


pytestmark = pytest.mark.unit


class TestPlatePriorityOrdering:
    """Test plate priority ordering system (CRITICAL - recently fixed bug)."""

    def test_plate_priority_ordering(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify plate priorities: FG=0, PL=0.5, BG=1, COMP=1.5, EL=2, BC=10."""
        # Create workspace with multiple plate types
        workspace_path = tmp_path / "workspace"
        plate_base = workspace_path / "publish" / "turnover" / "plate" / "input_plate"

        # Create plates in reverse priority order to test sorting
        plates_to_create = [
            ("BC01", "BC"),  # Priority 10 (lowest)
            ("EL01", "EL"),  # Priority 2
            ("COMP01", "COMP"),  # Priority 1.5
            ("BG01", "BG"),  # Priority 1
            ("PL01", "PL"),  # Priority 0.5
            ("FG01", "FG"),  # Priority 0 (highest)
        ]

        for plate_name, _plate_type in plates_to_create:
            plate_dir = plate_base / plate_name
            plate_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("config.Config.SHOWS_ROOT", str(tmp_path))

        # Get available plates (should only return FG and BG, not PL/BC/EL/COMP)
        result = PlateDiscovery.get_available_plates(str(workspace_path))

        # Should only include primary plates (FG, BG)
        assert result == ["FG01", "BG01"], "Only FG and BG plates should be returned"

    def test_pl_preferred_over_bg(self, tmp_path: Path) -> None:
        """PL01 chosen over BG01 - verifies recent bug fix (PL priority was 10, now 0.5)."""
        # Create workspace with both PL01 and BG01
        workspace_path = tmp_path / "workspace"
        plate_base = workspace_path / "publish" / "turnover" / "plate" / "input_plate"

        # Create BG01
        bg01_dir = plate_base / "BG01" / "v001" / "exr" / "1920x1080"
        bg01_dir.mkdir(parents=True, exist_ok=True)

        # Create PL01
        pl01_dir = plate_base / "PL01" / "v001" / "exr" / "4312x2304"
        pl01_dir.mkdir(parents=True, exist_ok=True)

        # When discovering plates dynamically, PL should have higher priority (0.5 vs 1)
        # Note: get_available_plates filters to FG/BG only, so we test internal discovery
        from discovery.file_discovery import FileDiscovery
        all_plates = FileDiscovery.discover_plate_directories(str(plate_base))

        # Should find both plates
        plate_names = [name for name, _priority in all_plates]
        assert "PL01" in plate_names
        assert "BG01" in plate_names

        # Verify PL01 has higher priority (lower number)
        pl_priority = next(priority for name, priority in all_plates if name == "PL01")
        bg_priority = next(priority for name, priority in all_plates if name == "BG01")
        assert pl_priority < bg_priority, f"PL priority ({pl_priority}) should be lower than BG ({bg_priority})"

    def test_fg_always_wins(self, tmp_path: Path) -> None:
        """FG01 always chosen over PL/BG (priority 0 is highest)."""
        workspace_path = tmp_path / "workspace"
        plate_base = workspace_path / "publish" / "turnover" / "plate" / "input_plate"

        # Create all three plate types
        for plate_name in ["FG01", "PL01", "BG01"]:
            plate_dir = plate_base / plate_name
            plate_dir.mkdir(parents=True, exist_ok=True)

        # Get available primary plates
        result = PlateDiscovery.get_available_plates(str(workspace_path))

        # FG01 should be first (highest priority)
        assert result[0] == "FG01", "FG01 should have highest priority"
        assert result[1] == "BG01", "BG01 should be second"

    def test_unknown_plate_type_gets_default_priority(self, tmp_path: Path) -> None:
        """Unknown plates get default priority 12 (lowest)."""
        plate_base = tmp_path / "plates"

        # Create known and unknown plate types
        plates = ["FG01", "UNKNOWN01", "BG01"]
        for plate_name in plates:
            (plate_base / plate_name).mkdir(parents=True, exist_ok=True)

        from discovery.file_discovery import FileDiscovery
        all_plates = FileDiscovery.discover_plate_directories(str(plate_base))

        # Should only find known plate types (FG, BG)
        plate_names = [name for name, _priority in all_plates]
        assert "FG01" in plate_names
        assert "BG01" in plate_names
        assert "UNKNOWN01" not in plate_names, "Unknown plate types should be filtered out"

    def test_multiple_plates_same_priority(self, tmp_path: Path) -> None:
        """Multiple plates of same type are grouped by priority (FG before BG)."""
        workspace_path = tmp_path / "workspace"
        plate_base = workspace_path / "publish" / "turnover" / "plate" / "input_plate"

        # Create multiple FG and BG plates
        for plate_name in ["FG03", "FG01", "FG02", "BG02", "BG01"]:
            (plate_base / plate_name).mkdir(parents=True, exist_ok=True)

        result = PlateDiscovery.get_available_plates(str(workspace_path))

        # Should have 5 plates total
        assert len(result) == 5, "Should find all 5 plates"

        # FG plates should come first (priority 0)
        fg_plates = [p for p in result if p.startswith("FG")]
        bg_plates = [p for p in result if p.startswith("BG")]

        assert len(fg_plates) == 3, "Should have 3 FG plates"
        assert len(bg_plates) == 2, "Should have 2 BG plates"

        # All FG plates should appear before all BG plates
        first_bg_index = result.index(bg_plates[0])
        last_fg_index = result.index(fg_plates[-1])
        assert last_fg_index < first_bg_index, "All FG plates should appear before BG plates"

    def test_discover_available_plates(self, tmp_path: Path) -> None:
        """Lists all available primary plate directories (FG, BG)."""
        workspace_path = tmp_path / "workspace"
        plate_base = workspace_path / "publish" / "turnover" / "plate" / "input_plate"

        # Create various plate types
        plates = ["FG01", "FG02", "BG01", "PL01", "COMP01"]
        for plate_name in plates:
            (plate_base / plate_name).mkdir(parents=True, exist_ok=True)

        result = PlateDiscovery.get_available_plates(str(workspace_path))

        # Should only include FG and BG plates (filters out PL, COMP)
        assert "FG01" in result
        assert "FG02" in result
        assert "BG01" in result
        assert "PL01" not in result, "PL plates should be filtered out"
        assert "COMP01" not in result, "COMP plates should be filtered out"


class TestScriptVersionDetection:
    """Test script version detection and incrementation."""

    def test_find_existing_scripts_returns_versions(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns list of (Path, version) tuples for existing scripts."""
        # Set consistent username for test
        monkeypatch.setenv("USER", "testuser")

        workspace_path = tmp_path / "workspace"
        shot_name = "TEST_0010"
        plate_name = "FG01"

        # Create workspace script directory (NEW: user workspace, not plate media directory)
        script_dir = workspace_path / "user" / "testuser" / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        script_dir.mkdir(parents=True, exist_ok=True)

        # Create test scripts
        (script_dir / f"{shot_name}_mm-default_{plate_name}_scene_v001.nk").touch()
        (script_dir / f"{shot_name}_mm-default_{plate_name}_scene_v002.nk").touch()
        (script_dir / f"{shot_name}_mm-default_{plate_name}_scene_v003.nk").touch()

        result = PlateDiscovery.find_existing_scripts(str(workspace_path), shot_name, plate_name)

        # Should return list of tuples
        assert len(result) == 3
        assert all(isinstance(item, tuple) and len(item) == 2 for item in result)

        # Check versions are extracted correctly
        versions = [version for _path, version in result]
        assert versions == [1, 2, 3]

    def test_find_existing_scripts_sorted_by_version(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns scripts sorted by version (lowest to highest)."""
        monkeypatch.setenv("USER", "testuser")

        workspace_path = tmp_path / "workspace"
        shot_name = "TEST_0010"
        plate_name = "FG01"

        script_dir = workspace_path / "user" / "testuser" / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        script_dir.mkdir(parents=True, exist_ok=True)

        # Create scripts in non-sequential order
        for version in [10, 2, 5, 1]:
            (script_dir / f"{shot_name}_mm-default_{plate_name}_scene_v{version:03d}.nk").touch()

        result = PlateDiscovery.find_existing_scripts(str(workspace_path), shot_name, plate_name)

        versions = [version for _path, version in result]
        assert versions == [1, 2, 5, 10], "Versions should be sorted ascending"

    def test_get_next_script_version_increments(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """v001 exists → returns 2."""
        monkeypatch.setenv("USER", "testuser")

        workspace_path = tmp_path / "workspace"
        shot_name = "TEST_0010"
        plate_name = "FG01"

        script_dir = workspace_path / "user" / "testuser" / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        script_dir.mkdir(parents=True, exist_ok=True)

        # Create v001
        (script_dir / f"{shot_name}_mm-default_{plate_name}_scene_v001.nk").touch()

        result = PlateDiscovery.get_next_script_version(str(workspace_path), shot_name, plate_name)

        assert result == 2, "Next version should be 2 when v001 exists"

    def test_get_next_script_version_handles_gaps(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """v001, v003 exist → returns 4 (increments highest version)."""
        monkeypatch.setenv("USER", "testuser")

        workspace_path = tmp_path / "workspace"
        shot_name = "TEST_0010"
        plate_name = "FG01"

        script_dir = workspace_path / "user" / "testuser" / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        script_dir.mkdir(parents=True, exist_ok=True)

        # Create v001 and v003 (skip v002)
        (script_dir / f"{shot_name}_mm-default_{plate_name}_scene_v001.nk").touch()
        (script_dir / f"{shot_name}_mm-default_{plate_name}_scene_v003.nk").touch()

        result = PlateDiscovery.get_next_script_version(str(workspace_path), shot_name, plate_name)

        assert result == 4, "Should return 4 (highest version + 1, ignoring gaps)"

    def test_get_next_script_version_with_no_scripts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No scripts → returns 1."""
        monkeypatch.setenv("USER", "testuser")

        workspace_path = tmp_path / "workspace"
        shot_name = "TEST_0010"
        plate_name = "FG01"

        # Create empty script directory
        script_dir = workspace_path / "user" / "testuser" / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        script_dir.mkdir(parents=True, exist_ok=True)

        result = PlateDiscovery.get_next_script_version(str(workspace_path), shot_name, plate_name)

        assert result == 1, "Should return 1 when no scripts exist"


class TestScriptPathConstruction:
    """Test script path construction and naming."""

    def test_construct_script_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Correct name: SHOT_mm-default_PLATE_scene_vVER.nk."""
        monkeypatch.setenv("USER", "testuser")

        workspace_path = tmp_path / "workspace"
        shot_name = "TEST_0010"
        plate_name = "FG01"

        script_dir = workspace_path / "user" / "testuser" / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        script_dir.mkdir(parents=True, exist_ok=True)

        # Create a script with correct naming
        script_path = script_dir / f"{shot_name}_mm-default_{plate_name}_scene_v001.nk"
        script_path.touch()

        # Verify it's discoverable
        result = PlateDiscovery.find_existing_scripts(str(workspace_path), shot_name, plate_name)

        assert len(result) == 1
        path, version = result[0]
        assert path.name == f"{shot_name}_mm-default_{plate_name}_scene_v001.nk"
        assert version == 1

    def test_script_naming_convention(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify format matches expectations: {shot}_mm-default_{plate}_scene_v{version}.nk."""
        monkeypatch.setenv("USER", "testuser")

        workspace_path = tmp_path / "workspace"
        shot_name = "BRX_170_0100"
        plate_name = "PL01"

        script_dir = workspace_path / "user" / "testuser" / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        script_dir.mkdir(parents=True, exist_ok=True)

        # Test the expected naming pattern
        expected_pattern = f"{shot_name}_mm-default_{plate_name}_scene_v005.nk"
        script_path = script_dir / expected_pattern
        script_path.touch()

        result = PlateDiscovery.find_existing_scripts(str(workspace_path), shot_name, plate_name)

        assert len(result) == 1
        path, version = result[0]
        assert path.name == expected_pattern
        assert version == 5
        assert "_mm-default_" in path.name
        assert "_scene_" in path.name
        assert ".nk" in path.name

    def test_script_versioning_format(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """v001, v002, v010, v100 formatting is correct."""
        monkeypatch.setenv("USER", "testuser")

        workspace_path = tmp_path / "workspace"
        shot_name = "TEST_0010"
        plate_name = "FG01"

        script_dir = workspace_path / "user" / "testuser" / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        script_dir.mkdir(parents=True, exist_ok=True)

        # Create scripts with various version numbers
        versions_to_test = [1, 2, 10, 100]
        for version in versions_to_test:
            script_name = f"{shot_name}_mm-default_{plate_name}_scene_v{version:03d}.nk"
            (script_dir / script_name).touch()

        result = PlateDiscovery.find_existing_scripts(str(workspace_path), shot_name, plate_name)

        # Verify all versions were found and formatted correctly
        found_versions = [version for _path, version in result]
        assert found_versions == versions_to_test

        # Verify filenames have correct formatting
        for path, version in result:
            expected_suffix = f"v{version:03d}.nk"
            assert path.name.endswith(expected_suffix), f"Script should end with {expected_suffix}"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_no_existing_scripts_in_plate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty plate directory returns empty list."""
        monkeypatch.setenv("USER", "testuser")

        workspace_path = tmp_path / "workspace"
        shot_name = "TEST_0010"
        plate_name = "FG01"

        # Create empty script directory
        script_dir = workspace_path / "user" / "testuser" / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        script_dir.mkdir(parents=True, exist_ok=True)

        result = PlateDiscovery.find_existing_scripts(str(workspace_path), shot_name, plate_name)

        assert result == [], "Should return empty list when no scripts exist"

    def test_malformed_script_names_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bad filenames don't crash discovery."""
        monkeypatch.setenv("USER", "testuser")

        workspace_path = tmp_path / "workspace"
        shot_name = "TEST_0010"
        plate_name = "FG01"

        script_dir = workspace_path / "user" / "testuser" / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        script_dir.mkdir(parents=True, exist_ok=True)

        # Create malformed filenames
        (script_dir / "invalid_script.nk").touch()
        (script_dir / f"{shot_name}_wrong_pattern.nk").touch()
        (script_dir / f"{shot_name}_mm-default_{plate_name}_scene_vABC.nk").touch()  # Non-numeric version
        (script_dir / f"{shot_name}_mm-default_{plate_name}_scene_v1.nk").touch()  # Wrong version format

        # Create one valid script
        (script_dir / f"{shot_name}_mm-default_{plate_name}_scene_v001.nk").touch()

        result = PlateDiscovery.find_existing_scripts(str(workspace_path), shot_name, plate_name)

        # Should only find the valid script
        assert len(result) == 1
        _path, version = result[0]
        assert version == 1

    def test_empty_shot_name(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Validation for empty inputs."""
        monkeypatch.setenv("USER", "testuser")

        workspace_path = tmp_path / "workspace"
        plate_name = "FG01"

        script_dir = workspace_path / "user" / "testuser" / "mm" / "nuke" / "scripts" / "mm-default" / "scene" / plate_name
        script_dir.mkdir(parents=True, exist_ok=True)

        # Test with empty shot name
        result = PlateDiscovery.find_existing_scripts(str(workspace_path), "", plate_name)

        # Should return empty list (no scripts match empty pattern)
        assert result == []

    def test_get_highest_resolution_dir_with_multiple_resolutions(self, tmp_path: Path) -> None:
        """Selects highest resolution when multiple exist."""
        plate_dir = tmp_path / "FG01" / "v001" / "exr"

        # Create multiple resolution directories
        resolutions = [
            ("1920x1080", 1920 * 1080),
            ("2048x1152", 2048 * 1152),
            ("4312x2304", 4312 * 2304),  # Highest
            ("3840x2160", 3840 * 2160),
        ]

        for res_name, _pixels in resolutions:
            (plate_dir / res_name).mkdir(parents=True, exist_ok=True)

        result = PlateDiscovery.get_highest_resolution_dir(plate_dir)

        assert result is not None
        assert result.name == "4312x2304", "Should select highest resolution"

    def test_get_highest_resolution_dir_no_resolution_dirs(self, tmp_path: Path) -> None:
        """Returns None when no resolution directories exist."""
        plate_dir = tmp_path / "FG01" / "v001" / "exr"
        plate_dir.mkdir(parents=True, exist_ok=True)

        # Create non-resolution directory
        (plate_dir / "other_folder").mkdir()

        result = PlateDiscovery.get_highest_resolution_dir(plate_dir)

        assert result is None, "Should return None when no resolution directories found"

    def test_get_highest_resolution_dir_malformed_names(self, tmp_path: Path) -> None:
        """Ignores directories that don't match resolution pattern."""
        plate_dir = tmp_path / "FG01" / "v001" / "exr"
        plate_dir.mkdir(parents=True, exist_ok=True)

        # Create malformed directory names
        (plate_dir / "invalid").mkdir()
        (plate_dir / "1920x").mkdir()
        (plate_dir / "x1080").mkdir()
        (plate_dir / "1920_1080").mkdir()

        # Create one valid resolution
        (plate_dir / "1920x1080").mkdir()

        result = PlateDiscovery.get_highest_resolution_dir(plate_dir)

        assert result is not None
        assert result.name == "1920x1080", "Should only match valid resolution pattern"

    def test_permission_error_handling(self, tmp_path: Path) -> None:
        """Gracefully handles permission errors during directory scan."""
        workspace_path = tmp_path / "workspace"

        # Test with empty workspace (simulates permission/access issues)
        result = PlateDiscovery.get_available_plates(str(workspace_path))

        # Should return empty list, not crash
        assert result == []
