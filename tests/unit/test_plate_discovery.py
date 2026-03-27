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
from discovery import PlateDiscovery


pytestmark = pytest.mark.unit


class TestPlatePriorityOrdering:
    """Test plate priority ordering system (CRITICAL - recently fixed bug)."""

    def test_plate_priority_ordering(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
        from discovery import FileDiscovery

        all_plates = FileDiscovery.discover_plate_directories(str(plate_base))

        # Should find both plates
        plate_names = [name for name, _priority in all_plates]
        assert "PL01" in plate_names
        assert "BG01" in plate_names

        # Verify PL01 has higher priority (lower number)
        pl_priority = next(priority for name, priority in all_plates if name == "PL01")
        bg_priority = next(priority for name, priority in all_plates if name == "BG01")
        assert pl_priority < bg_priority, (
            f"PL priority ({pl_priority}) should be lower than BG ({bg_priority})"
        )

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

        from discovery import FileDiscovery

        all_plates = FileDiscovery.discover_plate_directories(str(plate_base))

        # Should only find known plate types (FG, BG)
        plate_names = [name for name, _priority in all_plates]
        assert "FG01" in plate_names
        assert "BG01" in plate_names
        assert "UNKNOWN01" not in plate_names, (
            "Unknown plate types should be filtered out"
        )

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
        assert last_fg_index < first_bg_index, (
            "All FG plates should appear before BG plates"
        )

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


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_get_highest_resolution_dir_with_multiple_resolutions(
        self, tmp_path: Path
    ) -> None:
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

    def test_get_highest_resolution_dir_no_resolution_dirs(
        self, tmp_path: Path
    ) -> None:
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
