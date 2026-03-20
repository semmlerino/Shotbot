"""Tests for LatestFileFinderWorker async file search.

Tests cover:
- Signal emission: search_complete
- Search execution: Maya only, 3DE only, both
- Properties: maya_result, threede_result
- Cancellation: should_stop() behavior
- Error handling: Finder exceptions
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from discovery.latest_file_finder_worker import LatestFileFinderWorker
from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace structure matching VFX conventions."""
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    # Create Maya scene structure:
    # user/{user}/mm/maya/scenes/*.ma
    maya_dir = workspace_path / "user" / "artist" / "mm" / "maya" / "scenes"
    maya_dir.mkdir(parents=True)
    (maya_dir / "scene_v001.ma").touch()
    (maya_dir / "scene_v002.ma").touch()

    # Create 3DE scene structure matching ThreeDELatestFinder expectations:
    # user/{user}/mm/3de/mm-default/scenes/scene/{plate}/*.3de
    threede_dir = (
        workspace_path
        / "user"
        / "artist"
        / "mm"
        / "3de"
        / "mm-default"
        / "scenes"
        / "scene"
        / "FG01"
    )
    threede_dir.mkdir(parents=True)
    (threede_dir / "track_v001.3de").touch()
    (threede_dir / "track_v002.3de").touch()

    return workspace_path


@pytest.fixture
def empty_workspace(tmp_path: Path) -> Path:
    """Create an empty workspace."""
    workspace_path = tmp_path / "empty_workspace"
    workspace_path.mkdir()
    return workspace_path


# ==============================================================================
# Initialization Tests
# ==============================================================================


class TestLatestFileFinderWorkerInit:
    """Tests for worker initialization."""

    def test_results_initially_none(self, workspace: Path) -> None:
        """Results are None before search."""
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=True,
            find_threede=True,
        )

        assert worker.maya_result is None
        assert worker.threede_result is None


# ==============================================================================
# Signal Emission Tests
# ==============================================================================


class TestLatestFileFinderWorkerSignals:
    """Tests for signal emission."""

    def test_search_complete_signal_emitted(
        self,
        qtbot: QtBot,
        workspace: Path,
    ) -> None:
        """search_complete signal is emitted when search finishes."""
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=True,
            find_threede=False,
        )

        received_complete: list[bool] = []
        worker.search_complete.connect(lambda s: received_complete.append(s))

        worker.do_work()
        process_qt_events()

        assert len(received_complete) == 1
        assert received_complete[0] is True


# ==============================================================================
# Search Execution Tests
# ==============================================================================


class TestLatestFileFinderWorkerSearch:
    """Tests for search execution."""

    def test_finds_latest_maya_file(
        self,
        qtbot: QtBot,
        workspace: Path,
    ) -> None:
        """Worker finds the latest versioned Maya file."""
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=True,
            find_threede=False,
        )

        worker.do_work()
        process_qt_events()

        assert worker.maya_result is not None
        assert worker.maya_result.name == "scene_v002.ma"

    def test_finds_latest_threede_file(
        self,
        qtbot: QtBot,
        workspace: Path,
    ) -> None:
        """Worker finds the latest versioned 3DE file."""
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=False,
            find_threede=True,
        )

        worker.do_work()
        process_qt_events()

        assert worker.threede_result is not None
        assert worker.threede_result.name == "track_v002.3de"

    def test_empty_workspace_result_is_none(
        self,
        qtbot: QtBot,
        empty_workspace: Path,
    ) -> None:
        """Returns None result properties when no files found."""
        worker = LatestFileFinderWorker(
            workspace_path=str(empty_workspace),
            shot_name="test_shot",
            find_maya=True,
            find_threede=True,
        )

        worker.do_work()
        process_qt_events()

        assert worker.maya_result is None
        assert worker.threede_result is None

    def test_no_search_when_disabled(
        self,
        qtbot: QtBot,
        workspace: Path,
    ) -> None:
        """Results remain None when search is disabled."""
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=False,
            find_threede=False,
        )

        complete_results: list[bool] = []
        worker.search_complete.connect(lambda s: complete_results.append(s))

        worker.do_work()
        process_qt_events()

        # Results are None when search is disabled
        assert worker.maya_result is None
        assert worker.threede_result is None
        assert len(complete_results) == 1
        assert complete_results[0] is True


# ==============================================================================
# Cancellation Tests
# ==============================================================================


class TestLatestFileFinderWorkerCancellation:
    """Tests for cancellation behavior."""

    def test_respects_should_stop_before_maya_search(
        self,
        qtbot: QtBot,
        workspace: Path,
    ) -> None:
        """Worker respects should_stop() before Maya search."""
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=True,
            find_threede=True,
        )

        # Pre-stop the worker
        worker.request_stop()

        complete_results: list[bool] = []
        worker.search_complete.connect(lambda s: complete_results.append(s))

        worker.do_work()
        process_qt_events()

        # search_complete should emit False for cancellation
        assert len(complete_results) == 1
        assert complete_results[0] is False

    def test_respects_should_stop_between_searches(
        self,
        qtbot: QtBot,
        workspace: Path,
    ) -> None:
        """Worker skips Maya search when stopped after 3DE search."""
        # Use a mock 3DE finder that triggers stop mid-search
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=True,
            find_threede=True,
        )


        def stop_after_threede(*args, **kwargs):
            """Finder that also requests stop on the worker."""
            from threede import ThreeDELatestFinder
            finder = ThreeDELatestFinder()
            result = finder.find_latest_scene(*args, **kwargs)
            worker.request_stop()
            return result

        with patch("threede.ThreeDELatestFinder") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.find_latest_scene.side_effect = stop_after_threede
            mock_cls.return_value = mock_instance

            worker.do_work()
            process_qt_events()

        # Maya search should be skipped because stop was requested after 3DE
        assert worker.maya_result is None


# ==============================================================================
# Error Handling Tests
# ==============================================================================


class TestLatestFileFinderWorkerErrorHandling:
    """Tests for error handling."""

    def test_handles_maya_finder_exception(
        self,
        qtbot: QtBot,
        workspace: Path,
    ) -> None:
        """Worker handles exceptions from MayaLatestFinder."""
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=True,
            find_threede=False,
        )

        complete_results: list[bool] = []
        worker.search_complete.connect(lambda s: complete_results.append(s))

        # Mock the finder creation to raise an error
        with patch(
            "discovery.latest_file_finder_worker.MayaLatestFinder"
        ) as mock_finder_class:
            mock_finder = MagicMock()
            mock_finder.find_latest_scene.side_effect = RuntimeError(
                "Test error"
            )
            mock_finder_class.return_value = mock_finder

            worker.do_work()
            process_qt_events()

        # search_complete should emit False on error
        assert len(complete_results) == 1
        assert complete_results[0] is False

    def test_handles_threede_finder_exception(
        self,
        qtbot: QtBot,
        workspace: Path,
    ) -> None:
        """Worker handles exceptions from ThreeDELatestFinder."""
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=False,
            find_threede=True,
        )

        complete_results: list[bool] = []
        worker.search_complete.connect(lambda s: complete_results.append(s))

        with patch(
            "threede.ThreeDELatestFinder"
        ) as mock_finder_class:
            mock_finder = MagicMock()
            mock_finder.find_latest_scene.side_effect = RuntimeError(
                "Test error"
            )
            mock_finder_class.return_value = mock_finder

            worker.do_work()
            process_qt_events()

        # search_complete should emit False on error
        assert len(complete_results) == 1
        assert complete_results[0] is False


# ==============================================================================
# Property Access Tests
# ==============================================================================


class TestLatestFileFinderWorkerProperties:
    """Tests for result property access."""

    def test_maya_result_property_after_search(
        self,
        qtbot: QtBot,
        workspace: Path,
    ) -> None:
        """maya_result property returns the found file."""
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=True,
            find_threede=False,
        )

        worker.do_work()
        process_qt_events()

        result = worker.maya_result
        assert result is not None
        assert result.suffix == ".ma"

    def test_threede_result_property_after_search(
        self,
        qtbot: QtBot,
        workspace: Path,
    ) -> None:
        """threede_result property returns the found file."""
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=False,
            find_threede=True,
        )

        worker.do_work()
        process_qt_events()

        result = worker.threede_result
        assert result is not None
        assert result.suffix == ".3de"

    def test_results_none_when_not_searched(
        self,
        qtbot: QtBot,
        workspace: Path,
    ) -> None:
        """Results are None when that search type was disabled."""
        worker = LatestFileFinderWorker(
            workspace_path=str(workspace),
            shot_name="test_shot",
            find_maya=True,
            find_threede=False,  # 3DE disabled
        )

        worker.do_work()
        process_qt_events()

        # Maya was searched, should have result
        assert worker.maya_result is not None
        # 3DE was not searched, should be None
        assert worker.threede_result is None
