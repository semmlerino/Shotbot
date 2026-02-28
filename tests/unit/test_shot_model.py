"""Unit tests for ShotModel class following UNIFIED_TESTING_GUIDE best practices.

This refactored version:
- Uses real components with test doubles only at system boundaries
- Tests behavior, not implementation (no assert_called)
- Uses real files with tmp_path instead of mocking PathUtils/FileUtils
- Follows the principle of minimal mocking
"""

from __future__ import annotations

# Standard library imports
import json
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, Protocol

# Third-party imports
import pytest
from PySide6.QtTest import QSignalSpy


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

# Local application imports
from cache_manager import CacheManager, ShotMergeResult
from config import Config
from shot_model import RefreshResult, Shot, ShotModel
from tests.fixtures.test_doubles import TestProcessPool


if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

    class TestShotFactory(Protocol):
        """Protocol for shot factory fixtures."""

        __test__ = False

        def __call__(
            self,
            show: str = "test",
            sequence: str = "seq01",
            shot: str = "0010",
            with_thumbnail: bool = True,
        ) -> Shot: ...


@pytest.mark.unit
class TestShot:
    """Test cases for Shot dataclass using real files."""

    def test_shot_thumbnail_dir_property(self, make_test_shot: TestShotFactory) -> None:
        """Test Shot thumbnail_dir property."""
        shot = make_test_shot("testshow", "101_ABC", "0010")
        thumbnail_dir = shot.thumbnail_dir

        assert isinstance(thumbnail_dir, Path)
        assert "testshow" in str(thumbnail_dir)
        assert "101_ABC" in str(thumbnail_dir)
        assert "0010" in str(thumbnail_dir)

    def test_get_thumbnail_path_editorial_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_thumbnail_path finds editorial thumbnail with real files."""
        # Create real shot directory structure
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "test" / "shots" / "seq01" / "seq01_0010"
        shot_path.mkdir(parents=True, exist_ok=True)

        # Create real editorial thumbnail following exact Config.THUMBNAIL_SEGMENTS path
        editorial_path = (
            shot_path
            / "publish"
            / "editorial"
            / "cutref"
            / "v001"
            / "jpg"
            / "1920x1080"
        )
        editorial_path.mkdir(parents=True, exist_ok=True)
        thumb_file = editorial_path / "frame.1001.jpg"
        thumb_file.write_bytes(
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
        )  # Minimal JPEG

        # Temporarily override Config.SHOWS_ROOT to use our test directory
        monkeypatch.setattr("config.Config.SHOWS_ROOT", str(shows_root))

        # Create shot with real path
        shot = Shot("test", "seq01", "0010", str(shot_path))

        # Test actual behavior - finds real thumbnail
        thumbnail_path = shot.get_thumbnail_path()
        assert thumbnail_path is not None
        assert thumbnail_path.exists()
        assert thumbnail_path.name == "frame.1001.jpg"

        # Test caching behavior - second call returns same result
        thumbnail_path_cached = shot.get_thumbnail_path()
        assert thumbnail_path_cached == thumbnail_path

    def test_get_thumbnail_path_turnover_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_thumbnail_path falls back to turnover plates with real files."""
        # Create shot without editorial thumbnail
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "test" / "shots" / "seq01" / "seq01_0010"
        shot_path.mkdir(parents=True, exist_ok=True)

        # Create turnover thumbnail following actual structure from find_turnover_plate_thumbnail
        # Path: publish/turnover/plate/input_plate/{PLATE}/v001/exr/{resolution}/
        turnover_path = (
            shot_path
            / "publish"
            / "turnover"
            / "plate"
            / "input_plate"
            / "FG01"
            / "v001"
            / "exr"
            / "3840x2160"
        )
        turnover_path.mkdir(parents=True, exist_ok=True)
        turnover_file = turnover_path / "seq01_0010_FG01.1001.exr"
        turnover_file.write_bytes(b"EXR_DATA")

        # Temporarily override Config.SHOWS_ROOT
        monkeypatch.setattr("config.Config.SHOWS_ROOT", str(shows_root))

        shot = Shot("test", "seq01", "0010", str(shot_path))

        # Test actual fallback behavior
        thumbnail_path = shot.get_thumbnail_path()
        assert thumbnail_path is not None
        assert thumbnail_path.exists()
        assert thumbnail_path.suffix == ".exr"

    def test_get_thumbnail_path_publish_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test get_thumbnail_path falls back to publish thumbnails with real files."""
        # Create shot without editorial or turnover thumbnails
        shows_root = tmp_path / "shows"
        shot_path = shows_root / "test" / "shots" / "seq01" / "seq01_0010"
        shot_path.mkdir(parents=True, exist_ok=True)

        # Create only publish thumbnail with '1001' in the name
        publish_path = shot_path / "publish" / "comp" / "v001" / "exr"
        publish_path.mkdir(parents=True, exist_ok=True)
        publish_file = publish_path / "comp.1001.exr"
        publish_file.write_bytes(b"EXR_DATA")

        # Temporarily override Config.SHOWS_ROOT
        monkeypatch.setattr("config.Config.SHOWS_ROOT", str(shows_root))

        shot = Shot("test", "seq01", "0010", str(shot_path))

        # Test actual fallback behavior
        thumbnail_path = shot.get_thumbnail_path()
        assert thumbnail_path is not None
        assert thumbnail_path.exists()
        assert thumbnail_path.suffix == ".exr"
        assert "1001" in thumbnail_path.name

    def test_get_thumbnail_path_no_thumbnails_found(self, tmp_path: Path) -> None:
        """Test get_thumbnail_path returns None when no thumbnails found."""
        # Create empty shot directory
        shot_path = tmp_path / "shows" / "test" / "shots" / "seq01" / "seq01_0010"
        shot_path.mkdir(parents=True, exist_ok=True)

        shot = Shot("test", "seq01", "0010", str(shot_path))

        # Test behavior with no thumbnails
        thumbnail_path = shot.get_thumbnail_path()
        assert thumbnail_path is None

        # Test that None result is cached
        thumbnail_path_cached = shot.get_thumbnail_path()
        assert thumbnail_path_cached is None

@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestShotModel:
    """Test cases for ShotModel class using real components."""

    def test_shot_model_initialization(self, real_shot_model) -> None:
        """Test ShotModel initialization with real components."""
        assert real_shot_model is not None
        assert hasattr(real_shot_model, "shots")
        assert isinstance(real_shot_model.shots, list)

    def test_get_shots(self, real_shot_model, make_test_shot: TestShotFactory) -> None:
        """Test getting shots list with real shots."""
        # Add real shots to the model
        real_shot_model.shots = [
            make_test_shot("show1", "seq1", "0010"),
            make_test_shot("show1", "seq1", "0020"),
            make_test_shot("show2", "seq2", "0030"),
        ]

        shots = real_shot_model.get_shots()
        assert len(shots) == 3
        assert all(isinstance(shot, Shot) for shot in shots)

    def test_get_shot_by_name(
        self, real_shot_model, make_test_shot: TestShotFactory
    ) -> None:
        """Test getting specific shot by name."""
        # Add real shots
        real_shot_model.shots = [
            make_test_shot("show1", "seq1", "0010"),
            make_test_shot("show1", "seq1", "0020"),
        ]

        shot = real_shot_model.find_shot_by_name("seq1_0010")
        assert shot is not None
        assert shot.show == "show1"
        assert shot.sequence == "seq1"
        assert shot.shot == "0010"

    def test_get_shot_by_name_not_found(
        self, real_shot_model, make_test_shot: TestShotFactory
    ) -> None:
        """Test getting non-existent shot."""
        real_shot_model.shots = [make_test_shot("show1", "seq1", "0010")]

        shot = real_shot_model.find_shot_by_name("nonexistent")
        assert shot is None

    def test_refresh_shots_success(self, real_shot_model, test_process_pool) -> None:
        """Test successful shot refresh with test double at boundary."""
        # Set up test double with expected output
        test_process_pool.set_outputs(
            f"workspace {Config.SHOWS_ROOT}/test/shots/seq1/seq1_0010\n"
            f"workspace {Config.SHOWS_ROOT}/test/shots/seq1/seq1_0020\n"
        )
        real_shot_model._process_pool = test_process_pool

        # Test actual behavior
        result = real_shot_model.refresh_shots()

        assert isinstance(result, RefreshResult)
        assert result.success is True
        assert len(real_shot_model.shots) == 2
        # The parser now correctly extracts shot from shot_dir (e.g., seq1_0010 -> 0010)
        assert real_shot_model.shots[0].shot == "0010"
        assert real_shot_model.shots[1].shot == "0020"

    def test_refresh_shots_failure(self, real_shot_model, test_process_pool) -> None:
        """Test failed shot refresh with test double."""
        # Configure test double to fail
        test_process_pool.should_fail = True
        real_shot_model._process_pool = test_process_pool

        result = real_shot_model.refresh_shots()

        assert isinstance(result, RefreshResult)
        assert result.success is False

    def test_refresh_result_tuple_unpacking(
        self, real_shot_model, test_process_pool
    ) -> None:
        """Test RefreshResult supports tuple unpacking for backwards compatibility."""
        test_process_pool.set_outputs(f"workspace {Config.SHOWS_ROOT}/test/shots/seq1/seq1_0010\n")
        real_shot_model._process_pool = test_process_pool

        # Test tuple unpacking
        success, has_changes = real_shot_model.refresh_shots()
        assert isinstance(success, bool)
        assert isinstance(has_changes, bool)

    def test_get_shots_method(
        self, real_shot_model, make_test_shot: TestShotFactory
    ) -> None:
        """Test get_shots method returns shot list."""
        real_shot_model.shots = [
            make_test_shot("show1", "seq1", "0010"),
            make_test_shot("show1", "seq1", "0020"),
            make_test_shot("show2", "seq2", "0030"),
        ]

        shots = real_shot_model.get_shots()
        assert len(shots) == 3
        assert all(isinstance(shot, Shot) for shot in shots)

    def test_get_shot_by_index_valid(
        self, real_shot_model, make_test_shot: TestShotFactory
    ) -> None:
        """Test get_shot_by_index with valid index."""
        real_shot_model.shots = [
            make_test_shot("show1", "seq1", "0010"),
            make_test_shot("show1", "seq1", "0020"),
            make_test_shot("show2", "seq2", "0030"),
        ]

        shot = real_shot_model.get_shot_by_index(0)
        assert shot is not None
        assert shot.shot == "0010"

        shot = real_shot_model.get_shot_by_index(2)
        assert shot is not None
        assert shot.show == "show2"

    def test_get_shot_by_index_invalid(
        self, real_shot_model, make_test_shot: TestShotFactory
    ) -> None:
        """Test get_shot_by_index with invalid indices."""
        real_shot_model.shots = [
            make_test_shot("show1", "seq1", "0010"),
        ]

        # Negative index
        shot = real_shot_model.get_shot_by_index(-1)
        assert shot is None

        # Index too large
        shot = real_shot_model.get_shot_by_index(10)
        assert shot is None

        # Boundary case - exactly at length
        shot = real_shot_model.get_shot_by_index(1)
        assert shot is None

    def test_load_from_cache_success(self, real_shot_model, cache_manager) -> None:
        """Test successful cache loading with real cache."""
        # Prepare real cache data
        cache_data = [
            {
                "show": "test",
                "sequence": "seq1",
                "shot": "0010",
                "workspace_path": "/test/path1",
            },
            {
                "show": "test",
                "sequence": "seq1",
                "shot": "0020",
                "workspace_path": "/test/path2",
            },
        ]

        # Store data in real cache
        cache_manager.cache_shots(cache_data)

        # Test actual loading behavior
        result = real_shot_model.test_load_from_cache()

        assert result is True
        assert len(real_shot_model.shots) == 2
        assert real_shot_model.shots[0].show == "test"
        assert real_shot_model.shots[1].shot == "0020"

    def test_load_from_cache_no_data(self, real_shot_model) -> None:
        """Test cache loading when no data available."""
        # Cache is empty by default in cache_manager
        result = real_shot_model.test_load_from_cache()

        assert result is False
        assert len(real_shot_model.shots) == 0


@pytest.mark.allow_main_thread  # Tests call refresh_shots() synchronously from main thread
class TestShotModelErrorHandling:
    """Test error handling scenarios in ShotModel using test doubles."""

    def test_refresh_shots_timeout_error(
        self, real_shot_model, test_process_pool
    ) -> None:
        """Test refresh_shots handles TimeoutError properly."""
        # Configure test double to simulate timeout
        test_process_pool.fail_with_timeout = True
        real_shot_model._process_pool = test_process_pool

        result = real_shot_model.refresh_shots()

        assert isinstance(result, RefreshResult)
        assert result.success is False
        assert result.has_changes is False

    def test_refresh_shots_change_detection(
        self, real_shot_model, test_process_pool, make_test_shot: TestShotFactory
    ) -> None:
        """Test change detection logic in refresh_shots."""
        # Set initial shots
        real_shot_model.shots = [
            make_test_shot("show1", "seq1", "0010"),
            make_test_shot("show1", "seq1", "0020"),
        ]

        # Return same shots
        test_process_pool.set_outputs(
            f"workspace {Config.SHOWS_ROOT}/show1/shots/seq1/seq1_0010\n"
            f"workspace {Config.SHOWS_ROOT}/show1/shots/seq1/seq1_0020"
        )
        real_shot_model._process_pool = test_process_pool

        result = real_shot_model.refresh_shots()
        assert result.success is True
        # Note: has_changes may be True due to workspace_path differences

        # Now return different shots
        test_process_pool.set_outputs(f"workspace {Config.SHOWS_ROOT}/newshow/shots/seq1/seq1_0010")

        result = real_shot_model.refresh_shots()
        assert result.success is True
        assert len(real_shot_model.shots) == 1  # Different shot count = changes


class TestShotModelMergeErrorHandling:
    """Test error handling in _process_shot_merge method."""

    def test_process_shot_merge_cache_corruption_recovery(
        self,
        real_shot_model: ShotModel,
        cache_manager: CacheManager,
        mocker: MockerFixture,
    ) -> None:
        """Test recovery when cache merge fails due to corruption.

        This validates that cache corruption (KeyError, TypeError, ValueError)
        is handled gracefully by falling back to fresh data instead of crashing.
        """
        fresh_shots = [
            Shot("show1", "seq1", "0010", "/path/0010"),
            Shot("show1", "seq1", "0020", "/path/0020"),
        ]

        # Mock: Cache merge throws corruption error
        mock_merge = mocker.patch.object(cache_manager, "update_shots_cache")
        mock_merge.side_effect = KeyError("corrupted_field")

        # Action: Process merge should recover
        result = real_shot_model._process_shot_merge(fresh_shots, "test")

        # Verify: Returns fresh data as fallback
        assert len(result.updated_shots) == 2, (
            "Merge should fall back to fresh data when cache is corrupted"
        )
        assert result.new_shots == [s.to_dict() for s in fresh_shots]
        assert result.has_changes is True, (
            "Corruption recovery should indicate changes occurred"
        )

    def test_process_shot_merge_migration_failure_continues(
        self,
        real_shot_model: ShotModel,
        cache_manager: CacheManager,
        mocker: MockerFixture,
    ) -> None:
        """Test that migration failures don't halt the refresh operation.

        This validates that OSErrors during migration (disk full, permissions)
        are handled gracefully with a warning, allowing the refresh to complete.
        """
        cached_shots = [Shot("show1", "seq1", "0010", "/path/0010")]
        fresh_shots = [Shot("show1", "seq1", "0020", "/path/0020")]

        # Mock: Valid merge result with removed shot
        mock_merge_result = ShotMergeResult(
            updated_shots=[fresh_shots[0].to_dict()],
            new_shots=[fresh_shots[0].to_dict()],
            removed_shots=[cached_shots[0].to_dict()],
            has_changes=True,
        )
        mocker.patch.object(
            cache_manager, "update_shots_cache", return_value=mock_merge_result
        )

        # Mock: Migration returns False (disk full, permissions, etc.)
        mock_migrate = mocker.patch.object(
            cache_manager, "archive_shots_as_previous", return_value=False
        )

        # Action: Should complete despite migration failure
        result = real_shot_model._process_shot_merge(fresh_shots, "test")

        # Verify: Merge still succeeded
        assert len(result.updated_shots) == 1, (
            "Merge should complete even if migration fails"
        )
        assert result.has_changes is True

        # Verify: Migration was attempted
        mock_migrate.assert_called_once()

    def test_on_shots_loaded_async_merge_path(
        self,
        real_shot_model: ShotModel,
        cache_manager: CacheManager,
        mocker: MockerFixture,
        qtbot: QtBot,
    ) -> None:
        """Test async loading path calls merge and emits signals correctly.

        This validates that background shot loading uses the same merge logic
        and emits appropriate signals (shots_loaded, shots_changed).
        """
        fresh_shots = [
            Shot("show1", "seq1", "0010", "/path/0010"),
            Shot("show1", "seq1", "0020", "/path/0020"),
        ]

        # Mock: Valid merge with changes
        mock_merge_result = ShotMergeResult(
            updated_shots=[s.to_dict() for s in fresh_shots],
            new_shots=[s.to_dict() for s in fresh_shots],
            removed_shots=[],
            has_changes=True,
        )
        mocker.patch.object(
            cache_manager, "update_shots_cache", return_value=mock_merge_result
        )

        # Setup signal spies - shots_changed fires when there are new shots added
        with qtbot.waitSignal(real_shot_model.shots_loaded, timeout=1000) as blocker:
            # Action: Trigger async load (first load: 0 -> 2 shots)
            real_shot_model._on_shots_loaded(fresh_shots)

        # Verify: Signal was emitted
        assert blocker.signal_triggered, "shots_loaded signal should have been emitted for first load"

        # Verify: Shots were updated
        assert len(real_shot_model.shots) == 2, (
            "Model should have 2 shots after async load"
        )


class TestShotModelParser:
    """Test workspace output parsing edge cases with real model."""

    def test_parse_ws_output_invalid_input_type(self, real_shot_model) -> None:
        """Test parser with invalid input types.

        Note: The function expects a string type as per its type annotation.
        Invalid types will raise AttributeError, not WorkspaceError.
        """
        # The function has type annotation for str, so passing non-string
        # will raise AttributeError when trying to call string methods
        with pytest.raises(AttributeError):
            real_shot_model.test_parse_ws_output(123)  # type: ignore

        with pytest.raises(AttributeError):
            real_shot_model.test_parse_ws_output(None)  # type: ignore

    def test_parse_ws_output_empty_string(self, real_shot_model) -> None:
        """Test parser handles empty output."""
        shots = real_shot_model.test_parse_ws_output("")
        assert shots == []

        shots = real_shot_model.test_parse_ws_output("   ")  # Whitespace only
        assert shots == []

    def test_parse_ws_output_no_matches(self, real_shot_model) -> None:
        """Test parser with lines that don't match workspace pattern."""
        output = """Invalid line 1
Another invalid line
Not a workspace line"""

        shots = real_shot_model.test_parse_ws_output(output)
        assert shots == []

    def test_parse_ws_output_mixed_valid_invalid(self, real_shot_model) -> None:
        """Test parser with mix of valid and invalid lines."""
        shows_root = Config.SHOWS_ROOT
        output = f"""Invalid line
workspace {shows_root}/test1/shots/seq1/seq1_0010
Another invalid line
workspace {shows_root}/test2/shots/seq2/seq2_0020
Yet another invalid"""

        shots = real_shot_model.test_parse_ws_output(output)
        assert len(shots) == 2
        assert shots[0].show == "test1"
        assert shots[1].show == "test2"

    def test_parse_ws_output_empty_lines(self, real_shot_model) -> None:
        """Test parser skips empty lines."""
        shows_root = Config.SHOWS_ROOT
        output = f"""workspace {shows_root}/test1/shots/seq1/seq1_0010

workspace {shows_root}/test2/shots/seq2/seq2_0020

"""

        shots = real_shot_model.test_parse_ws_output(output)
        assert len(shots) == 2

    def test_parse_ws_output_complex_shot_names(self, real_shot_model) -> None:
        """Test parser handles complex shot name parsing."""
        shows_root = Config.SHOWS_ROOT
        output = f"""workspace {shows_root}/test/shots/seq1/001_ABC_0010
workspace {shows_root}/test/shots/seq2/simple_name
workspace {shows_root}/test/shots/seq3/very_long_complex_shot_name_0050"""

        shots = real_shot_model.test_parse_ws_output(output)
        assert len(shots) == 3

        # Test shot name extraction logic with new parsing:
        # For shot_dir that doesn't start with sequence_, it uses the last part after underscore
        assert shots[0].shot == "0010"  # 001_ABC_0010 -> last part after underscore
        assert shots[1].shot == "name"  # simple_name -> last part after underscore
        assert shots[2].shot == "0050"  # very_long_complex_shot_name_0050 -> last part


class TestShotModelPerformance:
    """Test performance-related functionality."""

    def test_invalidate_workspace_cache(
        self, real_shot_model, test_process_pool
    ) -> None:
        """Test cache invalidation with test double."""
        real_shot_model._process_pool = test_process_pool

        # Add some commands to verify reset
        test_process_pool.commands.append("previous_command")

        real_shot_model.invalidate_workspace_cache()

        # Test double should handle cache invalidation
        # In a real implementation, this would clear subprocess cache

    def test_get_performance_metrics(self, real_shot_model, test_process_pool) -> None:
        """Test performance metrics retrieval."""
        # Simulate some activity
        test_process_pool.call_count = 5
        test_process_pool.commands = ["cmd1", "cmd2", "cmd3", "cmd4", "cmd5"]
        real_shot_model._process_pool = test_process_pool

        # In real implementation, this would return actual metrics
        # Here we test that the method exists and can be called
        metrics = real_shot_model.get_performance_metrics()
        assert metrics is not None


@pytest.mark.allow_main_thread
class TestShotModelRefreshSignals:
    """Tests for refresh signal emission and cache integration (ported from integration suite)."""

    def test_signal_emission_order(self, real_shot_model, test_process_pool, qtbot: QtBot) -> None:
        """Test that signals are emitted in correct order during refresh."""
        test_process_pool.set_outputs(
            f"workspace {Config.SHOWS_ROOT}/test/shots/seq1/seq1_0010"
        )
        real_shot_model._process_pool = test_process_pool

        signal_order: list[str] = []

        def started_handler() -> None:
            signal_order.append("started")

        def changed_handler(_: object) -> None:
            signal_order.append("changed")

        def cache_handler() -> None:
            signal_order.append("cache")

        def finished_handler(*_: object) -> None:
            signal_order.append("finished")

        real_shot_model.refresh_started.connect(started_handler)
        real_shot_model.shots_changed.connect(changed_handler)
        real_shot_model.cache_updated.connect(cache_handler)
        real_shot_model.refresh_finished.connect(finished_handler)

        try:
            real_shot_model.refresh_shots()

            assert signal_order[0] == "started"
            assert signal_order[-1] == "finished"
            assert "changed" in signal_order
            assert "cache" in signal_order
        finally:
            real_shot_model.refresh_started.disconnect(started_handler)
            real_shot_model.shots_changed.disconnect(changed_handler)
            real_shot_model.cache_updated.disconnect(cache_handler)
            real_shot_model.refresh_finished.disconnect(finished_handler)

    def test_error_signal_on_failure(self, real_shot_model, qtbot: QtBot) -> None:
        """Test that error_occurred signal is emitted on failures."""
        def raise_error(*args: object, **kwargs: object) -> NoReturn:
            raise RuntimeError("Test error")

        real_shot_model._process_pool.execute_workspace_command = raise_error

        error_spy = QSignalSpy(real_shot_model.error_occurred)

        result = real_shot_model.refresh_shots()

        assert result.success is False
        assert error_spy.count() == 1
        assert "Test error" in error_spy.at(0)[0]

    def test_refresh_with_cache_updates_json_file(
        self, real_shot_model, cache_manager: CacheManager, test_process_pool
    ) -> None:
        """Test that refresh properly updates the on-disk cache JSON file."""
        cache_dir = cache_manager.cache_dir
        test_process_pool.set_outputs(
            f"workspace {Config.SHOWS_ROOT}/show1/shots/seq01/seq01_0010"
        )
        real_shot_model._process_pool = test_process_pool

        result = real_shot_model.refresh_shots()
        assert result.success is True

        cache_file = cache_dir / "shots.json"
        assert cache_file.exists()

        with cache_file.open() as f:
            cache_data = json.load(f)

        assert "data" in cache_data
        assert len(cache_data["data"]) == 1
        assert cache_data["data"][0]["show"] == "show1"

        # Update to a different show and verify the cache is overwritten
        test_process_pool.set_outputs(
            f"workspace {Config.SHOWS_ROOT}/show2/shots/seq01/seq01_0010"
        )
        real_shot_model.refresh_shots()

        with cache_file.open() as f:
            updated = json.load(f)

        assert updated["data"][0]["show"] == "show2"

    def test_shot_data_persistence_through_cache(
        self, cache_manager: CacheManager
    ) -> None:
        """Test shot data loaded from pre-seeded raw-dict cache at model init."""
        test_shots_data = [
            {
                "show": "test_show",
                "sequence": "seq01",
                "shot": "seq01_0010",
                "workspace_path": f"{Config.SHOWS_ROOT}/test_show/shots/seq01/seq01_0010",
                "name": "seq01_0010",
            },
            {
                "show": "test_show",
                "sequence": "seq01",
                "shot": "seq01_0020",
                "workspace_path": f"{Config.SHOWS_ROOT}/test_show/shots/seq01/seq01_0020",
                "name": "seq01_0020",
            },
        ]

        cache_manager.cache_shots(test_shots_data)

        pool = TestProcessPool(allow_main_thread=True)
        model = ShotModel(
            cache_manager=cache_manager,
            process_pool=pool,
        )

        shots = model.get_shots()
        assert len(shots) == 2
        assert shots[0].show == "test_show"
        assert shots[0].sequence == "seq01"
        assert shots[0].shot == "seq01_0010"
        assert shots[1].shot == "seq01_0020"
