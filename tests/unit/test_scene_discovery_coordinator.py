"""Unit tests for scene_discovery_coordinator.py.

Tests for SceneDiscoveryCoordinator which orchestrates scene discovery
using the Template Method pattern.

Following UNIFIED_TESTING_V2.md best practices:
- Test behavior using injected test doubles
- Mock lazy imports to isolate tests
- Test validation and discovery workflow
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from type_definitions import ThreeDEScene


pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ============================================================================
# Test Doubles
# ============================================================================


class FileSystemScannerDouble:
    """Test double for FileSystemScanner."""

    __test__ = False

    def __init__(self) -> None:
        self._valid_paths: set[str] = set()

    def verify_scene_exists(self, path: str | Path) -> bool:
        """Verify scene file exists."""
        return str(path) in self._valid_paths

    def set_valid_paths(self, *paths: str) -> None:
        """Set which paths should be considered valid."""
        self._valid_paths = set(paths)


class SceneParserDouble:
    """Test double for SceneParser."""

    __test__ = False

    def __init__(self) -> None:
        pass


class SceneDiscoveryStrategyDouble:
    """Test double for scene discovery strategy."""

    __test__ = False

    def __init__(self, name: str = "test") -> None:
        self._name = name
        self._scenes_for_shot: dict[tuple[str, str, str], list[ThreeDEScene]] = {}
        self._scenes_for_show: dict[str, list[ThreeDEScene]] = {}
        self._should_raise = False

    def find_scenes_for_shot(
        self,
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find scenes for a specific shot."""
        if self._should_raise:
            raise RuntimeError("Strategy error")
        key = (show, sequence, shot)
        return self._scenes_for_shot.get(key, [])

    def find_all_scenes_in_show(
        self,
        show_root: str,
        show: str,
        excluded_users: set[str] | None = None,
    ) -> list[ThreeDEScene]:
        """Find all scenes in a show."""
        if self._should_raise:
            raise RuntimeError("Strategy error")
        return self._scenes_for_show.get(show, [])

    def set_scenes_for_shot(
        self, show: str, sequence: str, shot: str, scenes: list[ThreeDEScene]
    ) -> None:
        """Configure scenes to return for a shot."""
        key = (show, sequence, shot)
        self._scenes_for_shot[key] = scenes

    def set_scenes_for_show(self, show: str, scenes: list[ThreeDEScene]) -> None:
        """Configure scenes to return for a show."""
        self._scenes_for_show[show] = scenes

    def set_failure_mode(self, should_raise: bool) -> None:
        """Configure strategy to raise exceptions."""
        self._should_raise = should_raise


# ============================================================================
# Fixtures
# ============================================================================


def create_test_scene(
    show: str = "SHOW",
    sequence: str = "SEQ",
    shot: str = "0010",
    user: str = "testuser",
    plate: str = "main",
    scene_path: str = "/path/to/scene.3de",
) -> ThreeDEScene:
    """Create a test ThreeDEScene."""
    return ThreeDEScene(
        show=show,
        sequence=sequence,
        shot=shot,
        workspace_path=f"/shows/{show}/shots/{sequence}/{shot}",
        user=user,
        plate=plate,
        scene_path=Path(scene_path),
    )


@pytest.fixture
def scanner_double() -> FileSystemScannerDouble:
    """Create a FileSystemScanner test double."""
    return FileSystemScannerDouble()


@pytest.fixture
def strategy_double() -> SceneDiscoveryStrategyDouble:
    """Create a SceneDiscoveryStrategy test double."""
    return SceneDiscoveryStrategyDouble()


@pytest.fixture
def coordinator(
    scanner_double: FileSystemScannerDouble,
):
    """Create a SceneDiscoveryCoordinator with test doubles injected."""
    with patch.dict(
        "sys.modules",
        {
            "filesystem_scanner": MagicMock(FileSystemScanner=lambda: scanner_double),
            "scene_parser": MagicMock(SceneParser=lambda: MagicMock()),
        },
    ):
        from discovery.scene_discovery_coordinator import SceneDiscoveryCoordinator

        coord = SceneDiscoveryCoordinator(strategy_type="local")
        # Inject test doubles
        coord.scanner = scanner_double
        return coord


# ============================================================================
# Test Initialization
# ============================================================================


class TestSceneDiscoveryCoordinatorInitialization:
    """Test SceneDiscoveryCoordinator initialization."""

    def test_init_sets_up_statistics(
        self,
        coordinator,
    ) -> None:
        """Test that initialization sets up statistics dictionary."""
        assert "scenes_discovered" in coordinator.stats
        assert "errors" in coordinator.stats
        assert coordinator.stats["scenes_discovered"] == 0


# ============================================================================
# Test Find Scenes For Shot
# ============================================================================


class TestFindScenesForShot:
    """Test find_scenes_for_shot method."""

    def test_find_scenes_returns_scenes_for_valid_shot(
        self,
        coordinator,
        scanner_double: FileSystemScannerDouble,
    ) -> None:
        """Test that find_scenes_for_shot returns discovered scenes."""
        scene = create_test_scene(show="SHOW", sequence="SEQ", shot="0010")
        scanner_double.set_valid_paths(str(scene.scene_path))

        # Patch validation to always pass and the local discovery method to return our scene
        with patch(
            "utils.ValidationUtils.validate_shot_components",
            return_value=True,
        ), patch.object(
            coordinator, "_find_scenes_for_shot_local", return_value=[scene]
        ):
            result = coordinator.find_scenes_for_shot(
                "/shows/SHOW/shots/SEQ/0010", "SHOW", "SEQ", "0010"
            )

        assert len(result) == 1
        assert result[0].show == "SHOW"
        assert result[0].shot == "0010"

    def test_find_scenes_returns_empty_for_invalid_path(
        self,
        coordinator,
    ) -> None:
        """Test that find_scenes_for_shot returns empty for invalid input."""
        # Patch validation to fail
        with patch(
            "utils.ValidationUtils.validate_shot_components",
            return_value=False,
        ):
            result = coordinator.find_scenes_for_shot("", "SHOW", "SEQ", "0010")

        assert result == []

    def test_find_scenes_filters_invalid_scenes(
        self,
        coordinator,
        scanner_double: FileSystemScannerDouble,
    ) -> None:
        """Test that find_scenes_for_shot filters out invalid scenes."""
        valid_scene = create_test_scene(
            scene_path="/valid/scene.3de", show="SHOW", sequence="SEQ", shot="0010"
        )
        invalid_scene = create_test_scene(
            scene_path="/invalid/scene.3de", show="SHOW", sequence="SEQ", shot="0010"
        )
        # Only the valid scene exists
        scanner_double.set_valid_paths("/valid/scene.3de")

        with patch(
            "utils.ValidationUtils.validate_shot_components",
            return_value=True,
        ), patch.object(
            coordinator,
            "_find_scenes_for_shot_local",
            return_value=[valid_scene, invalid_scene],
        ):
            result = coordinator.find_scenes_for_shot(
                "/shows/SHOW/shots/SEQ/0010", "SHOW", "SEQ", "0010"
            )

        # Only valid scene should be returned
        assert len(result) == 1
        assert str(result[0].scene_path) == "/valid/scene.3de"

    def test_find_scenes_handles_strategy_exception(
        self,
        coordinator,
    ) -> None:
        """Test that find_scenes_for_shot handles discovery errors."""
        with patch(
            "utils.ValidationUtils.validate_shot_components",
            return_value=True,
        ), patch.object(
            coordinator,
            "_find_scenes_for_shot_local",
            side_effect=RuntimeError("Discovery error"),
        ):
            result = coordinator.find_scenes_for_shot(
                "/shows/SHOW/shots/SEQ/0010", "SHOW", "SEQ", "0010"
            )

        assert result == []
        assert coordinator.stats["errors"] == 1


# ============================================================================
# Test Statistics
# ============================================================================


class TestStatistics:
    """Test statistics methods."""

    def test_get_statistics_returns_stats(
        self,
        coordinator,
    ) -> None:
        """Test that get_statistics returns the stats dictionary."""
        stats = coordinator.get_statistics()

        assert "scenes_discovered" in stats
        assert "errors" in stats

    def test_statistics_track_discovered_scenes(
        self,
        coordinator,
        scanner_double: FileSystemScannerDouble,
    ) -> None:
        """Test that statistics track discovered scenes."""
        scene = create_test_scene()
        scanner_double.set_valid_paths(str(scene.scene_path))

        with patch(
            "utils.ValidationUtils.validate_shot_components",
            return_value=True,
        ), patch.object(
            coordinator, "_find_scenes_for_shot_local", return_value=[scene]
        ):
            coordinator.find_scenes_for_shot(
                "/shows/SHOW/shots/SEQ/0010", "SHOW", "SEQ", "0010"
            )

        assert coordinator.stats["scenes_discovered"] == 1


# ============================================================================
# Test Strategy Management
# ============================================================================
