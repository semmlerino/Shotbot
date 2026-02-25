"""Tests for SceneDiscoveryStrategy module.

Tests cover:
- create_discovery_strategy(): Factory function for creating strategies
- Strategy names and initialization
- Strategy-specific parameters (num_workers, network_timeout)
- Error handling for invalid strategy types
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from scene_discovery_strategy import (
    LocalFileSystemStrategy,
    NetworkAwareStrategy,
    ParallelFileSystemStrategy,
    ProgressiveDiscoveryStrategy,
    create_discovery_strategy,
)


if TYPE_CHECKING:
    from threede_scene_model import ThreeDEScene


# ==============================================================================
# Factory Function Tests
# ==============================================================================


class TestCreateDiscoveryStrategy:
    """Tests for create_discovery_strategy() factory function."""

    def test_creates_local_strategy_by_default(self) -> None:
        """Default strategy type is 'local'."""
        strategy = create_discovery_strategy()

        assert isinstance(strategy, LocalFileSystemStrategy)

    def test_creates_local_strategy_explicitly(self) -> None:
        """Explicitly creates LocalFileSystemStrategy."""
        strategy = create_discovery_strategy("local")

        assert isinstance(strategy, LocalFileSystemStrategy)
        assert strategy.get_strategy_name() == "LocalFileSystemStrategy"

    def test_creates_parallel_strategy(self) -> None:
        """Creates ParallelFileSystemStrategy."""
        strategy = create_discovery_strategy("parallel")

        assert isinstance(strategy, ParallelFileSystemStrategy)
        assert strategy.get_strategy_name() == "ParallelFileSystemStrategy"

    def test_creates_progressive_strategy(self) -> None:
        """Creates ProgressiveDiscoveryStrategy."""
        strategy = create_discovery_strategy("progressive")

        assert isinstance(strategy, ProgressiveDiscoveryStrategy)
        assert strategy.get_strategy_name() == "ProgressiveDiscoveryStrategy"

    def test_creates_network_strategy(self) -> None:
        """Creates NetworkAwareStrategy."""
        strategy = create_discovery_strategy("network")

        assert isinstance(strategy, NetworkAwareStrategy)
        assert strategy.get_strategy_name() == "NetworkAwareStrategy"

    def test_raises_on_invalid_strategy_type(self) -> None:
        """Raises ValueError for unknown strategy type."""
        with pytest.raises(ValueError, match="Unknown strategy type"):
            create_discovery_strategy("invalid_type")

    def test_error_message_lists_available_strategies(self) -> None:
        """Error message includes available strategy types."""
        with pytest.raises(ValueError, match="Unknown strategy type") as exc_info:
            create_discovery_strategy("bad_strategy")

        error_msg = str(exc_info.value)
        assert "local" in error_msg
        assert "parallel" in error_msg
        assert "progressive" in error_msg
        assert "network" in error_msg


# ==============================================================================
# Strategy Initialization Tests
# ==============================================================================


# ==============================================================================
# Strategy Name Tests
# ==============================================================================


class TestStrategyNames:
    """Tests for get_strategy_name() method."""

    @pytest.mark.parametrize(
        ("strategy_type", "expected_name"),
        [
            ("local", "LocalFileSystemStrategy"),
            ("parallel", "ParallelFileSystemStrategy"),
            ("progressive", "ProgressiveDiscoveryStrategy"),
            ("network", "NetworkAwareStrategy"),
        ],
    )
    def test_strategy_name_matches_class(
        self, strategy_type: str, expected_name: str
    ) -> None:
        """Strategy name matches the class name."""
        strategy = create_discovery_strategy(strategy_type)

        assert strategy.get_strategy_name() == expected_name


# ==============================================================================
# Strategy Base Class Tests
# ==============================================================================


class TestSceneDiscoveryStrategyBase:
    """Tests for SceneDiscoveryStrategy base class behavior."""

# ==============================================================================
# LocalFileSystemStrategy Behavior Tests
# ==============================================================================


class TestLocalFileSystemStrategyBehavior:
    """Tests for LocalFileSystemStrategy behavior."""

    def test_returns_empty_list_for_invalid_shot_components(self) -> None:
        """Returns empty list when shot components are invalid."""
        strategy = LocalFileSystemStrategy()

        # Empty shot should be invalid
        result = strategy.find_scenes_for_shot(
            shot_workspace_path="/shows/test/shots/seq01/seq01_0010",
            show="",  # Invalid: empty show
            sequence="seq01",
            shot="0010",
        )

        assert result == []

    def test_returns_empty_list_for_empty_workspace_path(self) -> None:
        """Returns empty list when workspace path is empty."""
        strategy = LocalFileSystemStrategy()

        result = strategy.find_scenes_for_shot(
            shot_workspace_path="",  # Invalid: empty path
            show="testshow",
            sequence="seq01",
            shot="0010",
        )

        assert result == []

    def test_returns_cached_scenes_when_available(self) -> None:
        """Returns cached scenes without rescanning."""
        strategy = LocalFileSystemStrategy()

        # Mock the cache to return cached data
        mock_scenes: list[ThreeDEScene] = []  # Empty list simulating cached data
        strategy.cache.get_scenes_for_shot = MagicMock(return_value=mock_scenes)

        result = strategy.find_scenes_for_shot(
            shot_workspace_path="/shows/test/shots/seq01/seq01_0010",
            show="testshow",
            sequence="seq01",
            shot="0010",
        )

        assert result == mock_scenes
        strategy.cache.get_scenes_for_shot.assert_called_once_with(
            "testshow", "seq01", "0010"
        )

    def test_returns_empty_for_nonexistent_show_path(self) -> None:
        """Returns empty list when show path doesn't exist."""
        strategy = LocalFileSystemStrategy()

        result = strategy.find_all_scenes_in_show(
            show_root="/nonexistent/path",
            show="testshow",
        )

        assert result == []


# ==============================================================================
# ParallelFileSystemStrategy Behavior Tests
# ==============================================================================


class TestParallelFileSystemStrategyBehavior:
    """Tests for ParallelFileSystemStrategy behavior."""

    def test_delegates_single_shot_to_local_strategy(self) -> None:
        """Single shot discovery delegates to LocalFileSystemStrategy."""
        strategy = ParallelFileSystemStrategy()

        # For single shots, parallel provides no benefit
        # Should internally use LocalFileSystemStrategy
        result = strategy.find_scenes_for_shot(
            shot_workspace_path="",  # Empty path should return empty
            show="testshow",
            sequence="seq01",
            shot="0010",
        )

        assert result == []


# ==============================================================================
# ProgressiveDiscoveryStrategy Behavior Tests
# ==============================================================================


class TestProgressiveDiscoveryStrategyBehavior:
    """Tests for ProgressiveDiscoveryStrategy behavior."""

    def test_delegates_single_shot_to_local_strategy(self) -> None:
        """Single shot discovery delegates to LocalFileSystemStrategy."""
        strategy = ProgressiveDiscoveryStrategy()

        result = strategy.find_scenes_for_shot(
            shot_workspace_path="",  # Empty path should return empty
            show="testshow",
            sequence="seq01",
            shot="0010",
        )

        assert result == []

    def test_find_scenes_progressive_yields_generator(self) -> None:
        """find_scenes_progressive returns a generator."""
        strategy = ProgressiveDiscoveryStrategy()

        # Mock scanner to return empty shots list
        strategy.scanner.discover_all_shots_in_show = MagicMock(return_value=[])

        result = strategy.find_scenes_progressive(
            show_root="/shows",
            show="testshow",
        )

        # Should be a generator
        assert hasattr(result, "__iter__")
        assert hasattr(result, "__next__")

    def test_find_scenes_progressive_yields_no_shots_message(self) -> None:
        """Yields 'No shots found' when no shots discovered."""
        strategy = ProgressiveDiscoveryStrategy()

        # Mock scanner to return empty shots list
        strategy.scanner.discover_all_shots_in_show = MagicMock(return_value=[])

        result = list(
            strategy.find_scenes_progressive(
                show_root="/shows",
                show="testshow",
            )
        )

        assert len(result) == 1
        scenes, current, total, status = result[0]
        assert scenes == []
        assert current == 0
        assert total == 0
        assert status == "No shots found"


# ==============================================================================
# NetworkAwareStrategy Behavior Tests
# ==============================================================================


class TestNetworkAwareStrategyBehavior:
    """Tests for NetworkAwareStrategy behavior."""

    def test_delegates_to_local_strategy_for_shots(self) -> None:
        """Shot discovery delegates to LocalFileSystemStrategy for now."""
        strategy = NetworkAwareStrategy()

        result = strategy.find_scenes_for_shot(
            shot_workspace_path="",  # Empty path should return empty
            show="testshow",
            sequence="seq01",
            shot="0010",
        )

        assert result == []

    def test_delegates_to_local_strategy_for_shows(self) -> None:
        """Show discovery delegates to LocalFileSystemStrategy for now."""
        strategy = NetworkAwareStrategy()

        result = strategy.find_all_scenes_in_show(
            show_root="/nonexistent/path",
            show="testshow",
        )

        assert result == []


# ==============================================================================
# Integration with VFX Directory Structure
# ==============================================================================


class TestVFXDirectoryIntegration:
    """Integration tests with VFX directory structure."""

    def test_local_strategy_scans_user_directory(self, tmp_path: Path) -> None:
        """LocalFileSystemStrategy scans user directory for .3de files."""
        strategy = LocalFileSystemStrategy()

        # Create VFX directory structure
        shot_workspace = tmp_path / "shows" / "testshow" / "shots" / "seq01" / "seq01_0010"
        user_dir = shot_workspace / "user" / "artist1" / "3de"
        user_dir.mkdir(parents=True)

        # Create a .3de file
        threede_file = user_dir / "scene_v001.3de"
        threede_file.write_text("# 3DE scene file")

        # Clear any cached data
        strategy.cache.get_scenes_for_shot = MagicMock(return_value=None)

        # Mock scanner to return file pairs
        strategy.scanner.find_3de_files_progressive = MagicMock(
            return_value=[("artist1", threede_file)]
        )
        strategy.scanner.verify_scene_exists = MagicMock(return_value=True)
        strategy.parser.extract_plate_from_path = MagicMock(return_value="BG01")

        # Mock scene creation
        mock_scene = MagicMock()
        strategy.parser.create_scene_from_file_info = MagicMock(return_value=mock_scene)

        result = strategy.find_scenes_for_shot(
            shot_workspace_path=str(shot_workspace),
            show="testshow",
            sequence="seq01",
            shot="0010",
        )

        assert len(result) == 1
        strategy.parser.create_scene_from_file_info.assert_called_once()

    def test_local_strategy_handles_excluded_users(self, tmp_path: Path) -> None:
        """LocalFileSystemStrategy respects excluded_users parameter."""
        strategy = LocalFileSystemStrategy()

        shot_workspace = tmp_path / "shows" / "testshow" / "shots" / "seq01" / "seq01_0010"
        user_dir = shot_workspace / "user"
        user_dir.mkdir(parents=True)

        # Clear cache
        strategy.cache.get_scenes_for_shot = MagicMock(return_value=None)

        # Mock scanner with excluded users
        strategy.scanner.find_3de_files_progressive = MagicMock(return_value=[])

        excluded = {"excluded_artist"}
        _ = strategy.find_scenes_for_shot(
            shot_workspace_path=str(shot_workspace),
            show="testshow",
            sequence="seq01",
            shot="0010",
            excluded_users=excluded,
        )

        # Should have been called with the excluded users
        strategy.scanner.find_3de_files_progressive.assert_called_once()
        call_args = strategy.scanner.find_3de_files_progressive.call_args
        assert call_args[0][1] == excluded  # Second positional arg is excluded_users
