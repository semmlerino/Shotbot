"""Unit tests for TargetedShotsFinder."""

from __future__ import annotations

# Standard library imports
import logging
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from unittest.mock import MagicMock, Mock

# Third-party imports
import pytest

from config import Config

# Local application imports
from shots.targeted_shot_finder import TargetedShotsFinder
from type_definitions import Shot


class TestTargetedShotsFinderInitialization:
    """Test TargetedShotsFinder initialization."""

    def test_initialization_defaults(self) -> None:
        """Test initialization sets username and max_workers correctly."""
        finder = TargetedShotsFinder(username="test_user", max_workers=4)
        assert finder.username == "test_user"
        assert finder.max_workers == 4


class TestExtractShowsFromActiveShots:
    """Test extract_shows_from_active_shots method."""

    def test_extract_unique_shows(self) -> None:
        """Test extracting unique show names from active shots."""
        finder = TargetedShotsFinder()

        # Create test shots from different shows
        active_shots = [
            Shot(show="show1", sequence="seq1", shot="0010", workspace_path="/path1"),
            Shot(show="show2", sequence="seq1", shot="0020", workspace_path="/path2"),
            Shot(
                show="show1", sequence="seq2", shot="0030", workspace_path="/path3"
            ),  # Duplicate show
            Shot(show="show3", sequence="seq1", shot="0040", workspace_path="/path4"),
        ]

        shows = finder.extract_shows_from_active_shots(active_shots)

        assert len(shows) == 3
        assert shows == {"show1", "show2", "show3"}

    def test_extract_from_empty_list(self) -> None:
        """Test extracting from empty shot list."""
        finder = TargetedShotsFinder()
        shows = finder.extract_shows_from_active_shots([])

        assert shows == set()


class TestScanShowForUser:
    """Test _scan_show_for_user method."""

    def test_scan_existing_show(self, tmp_path: Path, mocker) -> None:
        """Test scanning a show with user directories."""
        finder = TargetedShotsFinder(username="john")

        # Create show structure
        shows_root = tmp_path / "shows"
        show_path = shows_root / "test_show" / "shots" / "010" / "0010"
        user_path = show_path / "user" / "john"
        user_path.mkdir(parents=True)

        # Mock CancellableSubprocess to return user path
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = str(user_path)
        mock_result.status = "ok"

        mock_proc = MagicMock()
        mock_proc.run.return_value = mock_result

        mocker.patch(
            "shots.shot_finder_base.CancellableSubprocess", return_value=mock_proc
        )
        shots = finder._scan_show_for_user("test_show", shows_root)

        assert len(shots) > 0
        mock_proc.run.assert_called_once()

    def test_scan_nonexistent_show(self, tmp_path: Path) -> None:
        """Test scanning a show that doesn't exist returns empty list."""
        finder = TargetedShotsFinder()
        shows_root = tmp_path / "shows"
        shows_root.mkdir()

        shots = finder._scan_show_for_user("nonexistent_show", shows_root)
        assert shots == []

    def test_scan_with_stop_requested(self, tmp_path: Path) -> None:
        """Test scanning stops when stop is requested."""
        finder = TargetedShotsFinder()
        finder._stop_requested = True

        shots = finder._scan_show_for_user("any_show", tmp_path)

        assert shots == []

    @pytest.mark.parametrize(
        "proc_setup",
        [
            "timeout",
            "error",
        ],
    )
    def test_scan_with_subprocess_failure(
        self, tmp_path: Path, proc_setup: str, mocker
    ) -> None:
        """Test that subprocess timeout and error both return empty shot list."""
        finder = TargetedShotsFinder()

        shows_root = tmp_path / "shows"
        show_path = shows_root / "test_show" / "shots"
        show_path.mkdir(parents=True)

        mock_proc = MagicMock()
        if proc_setup == "timeout":
            mock_result = MagicMock()
            mock_result.returncode = None
            mock_result.stdout = ""
            mock_result.status = "timeout"
            mock_proc.run.return_value = mock_result
        else:
            mock_proc.run.side_effect = Exception("Process failed")

        mocker.patch(
            "shots.shot_finder_base.CancellableSubprocess", return_value=mock_proc
        )
        shots = finder._scan_show_for_user("test_show", shows_root)

        assert shots == []

    def test_scan_with_multiple_shots(self, tmp_path: Path, monkeypatch, mocker) -> None:
        """Test scanning show with multiple shots."""
        # Set SHOWS_ROOT to tmp_path for this test
        shows_root = tmp_path / "shows"
        shows_root.mkdir()
        monkeypatch.setenv("SHOWS_ROOT", str(shows_root))

        # Create the show directory structure
        show_path = shows_root / "myshow" / "shots"
        show_path.mkdir(parents=True)

        finder = TargetedShotsFinder(username="artist")

        # Mock CancellableSubprocess to return multiple paths
        user_paths = [
            f"{shows_root}/myshow/shots/010/010_0010/user/artist",
            f"{shows_root}/myshow/shots/010/010_0020/user/artist",
            f"{shows_root}/myshow/shots/020/020_0010/user/artist",
        ]

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n".join(user_paths)
        mock_result.status = "ok"

        mock_proc = MagicMock()
        mock_proc.run.return_value = mock_result

        mocker.patch(
            "shots.shot_finder_base.CancellableSubprocess", return_value=mock_proc
        )
        shots = finder._scan_show_for_user("myshow", shows_root)

        assert len(shots) == 3
        # Check that shots are unique
        shot_ids = [(s.sequence, s.shot) for s in shots]
        assert len(shot_ids) == len(set(shot_ids))


class TestParseShotFromPath:
    """Test _parse_shot_from_path method."""

    def test_parse_standard_path(self) -> None:
        """Test parsing standard VFX shot path."""
        finder = TargetedShotsFinder()

        path = f"{Config.Paths.SHOWS_ROOT}/test_show/shots/010/010_0010/user/john"
        shot = finder._parse_shot_from_path(path)

        assert shot is not None
        assert shot.show == "test_show"
        assert shot.sequence == "010"
        assert shot.shot == "0010"  # Should extract shot number
        assert (
            shot.workspace_path == f"{Config.Paths.SHOWS_ROOT}/test_show/shots/010/010_0010"
        )

    def test_parse_path_without_underscore(self) -> None:
        """Test parsing path where shot dir has no underscore."""
        finder = TargetedShotsFinder()

        path = f"{Config.Paths.SHOWS_ROOT}/test_show/shots/010/0010/user/john"
        shot = finder._parse_shot_from_path(path)

        assert shot is not None
        assert shot.shot == "0010"  # Should use whole name

    def test_parse_path_with_complex_shot_name(self) -> None:
        """Test parsing path with complex shot name."""
        finder = TargetedShotsFinder()

        path = f"{Config.Paths.SHOWS_ROOT}/test_show/shots/010/010_0010_extra/user/john"
        shot = finder._parse_shot_from_path(path)

        assert shot is not None
        assert shot.shot == "0010_extra"  # Should handle extra parts

    def test_parse_invalid_path(self) -> None:
        """Test parsing invalid path returns None."""
        finder = TargetedShotsFinder()

        path = "/invalid/path/structure"
        shot = finder._parse_shot_from_path(path)

        assert shot is None


class TestFindUserShotsInShows:
    """Test find_user_shots_in_shows method."""

    def test_find_in_target_shows(self, tmp_path: Path, mocker) -> None:
        """Test finding shots in targeted shows."""
        finder = TargetedShotsFinder(username="john")

        target_shows = {"show1", "show2"}

        # Mock _scan_show_for_user to return shots
        def mock_scan(show_name, shows_root):
            if show_name == "show1":
                return [
                    Shot(
                        show="show1",
                        sequence="010",
                        shot="0010",
                        workspace_path="/path1",
                    ),
                ]
            if show_name == "show2":
                return [
                    Shot(
                        show="show2",
                        sequence="020",
                        shot="0020",
                        workspace_path="/path2",
                    ),
                ]
            return []

        mocker.patch.object(finder, "_scan_show_for_user", side_effect=mock_scan)
        shots = list(finder.find_user_shots_in_shows(target_shows, tmp_path))

        assert len(shots) == 2
        assert any(s.show == "show1" for s in shots)
        assert any(s.show == "show2" for s in shots)

    def test_find_with_empty_target_shows(self, caplog) -> None:
        """Test finding with no target shows."""
        finder = TargetedShotsFinder()

        with caplog.at_level(logging.WARNING, logger="shots.targeted_shot_finder"):
            shots = list(finder.find_user_shots_in_shows(set(), None))

        assert shots == []
        assert any("No target shows provided" in r.message for r in caplog.records)

    def test_find_with_nonexistent_shows_root(self) -> None:
        """Test finding with nonexistent shows root returns empty list."""
        finder = TargetedShotsFinder()

        shots = list(finder.find_user_shots_in_shows({"show1"}, Path("/nonexistent")))
        assert shots == []

    def test_find_with_stop_requested(self, mocker) -> None:
        """Test that finding stops when stop is requested."""
        finder = TargetedShotsFinder()

        # Mock scan to return shots
        mocker.patch.object(finder, "_scan_show_for_user", return_value=[Mock()])
        # Request stop during iteration
        finder._stop_requested = True
        shots = list(finder.find_user_shots_in_shows({"show1"}, Path("/")))

        assert shots == []  # Should stop early

    def test_parallel_execution(self, tmp_path: Path, mocker) -> None:
        """Test parallel execution with ThreadPoolExecutor."""
        finder = TargetedShotsFinder(max_workers=2)

        target_shows = {"show1", "show2", "show3"}

        # Track which shows were scanned
        scanned_shows = []

        def mock_scan(show_name, shows_root):
            scanned_shows.append(show_name)
            return []

        mocker.patch.object(finder, "_scan_show_for_user", side_effect=mock_scan)
        list(finder.find_user_shots_in_shows(target_shows, tmp_path))

        # All shows should have been scanned
        assert set(scanned_shows) == target_shows

    def test_progress_reporting(self, tmp_path: Path, mocker) -> None:
        """Test that progress is reported during search."""
        finder = TargetedShotsFinder()
        progress_callback = MagicMock()
        finder.set_progress_callback(progress_callback)

        target_shows = {"show1"}

        mocker.patch.object(finder, "_scan_show_for_user", return_value=[])
        list(finder.find_user_shots_in_shows(target_shows, tmp_path))

        # Should have reported progress
        progress_callback.assert_called()
        # Should have initial and final progress
        assert any(
            "Searching" in str(call) for call in progress_callback.call_args_list
        )


class TestFindApprovedShotsTargeted:
    """Test find_approved_shots_targeted method."""

    def test_find_approved_with_no_target_shows(self, mocker, caplog) -> None:
        """Test when no target shows are found."""
        finder = TargetedShotsFinder()
        active_shots = []

        mocker.patch.object(finder, "extract_shows_from_active_shots", return_value=set())
        with caplog.at_level(logging.WARNING, logger="shots.targeted_shot_finder"):
            approved = finder.find_approved_shots_targeted(active_shots)

        assert approved == []
        assert any("No target shows found" in r.message for r in caplog.records)

    def test_find_approved_with_stop_request(self, caplog) -> None:
        """Test stopping during approved shot finding."""
        finder = TargetedShotsFinder()
        finder._stop_requested = True

        active_shots = [
            Shot(show="show1", sequence="010", shot="0010", workspace_path="/path1"),
        ]

        with caplog.at_level(logging.INFO, logger="shots.targeted_shot_finder"):
            approved = finder.find_approved_shots_targeted(active_shots)

        assert approved == []
        assert any("Targeted search stopped by user request" in r.message for r in caplog.records)

    def test_find_approved_with_progress(self, mocker) -> None:
        """Test progress reporting during approved shot finding."""
        finder = TargetedShotsFinder()
        progress_callback = MagicMock()
        finder.set_progress_callback(progress_callback)

        active_shots = [
            Shot(show="show1", sequence="010", shot="0010", workspace_path="/path1"),
        ]

        mocker.patch.object(
            finder, "extract_shows_from_active_shots", return_value={"show1"}
        )
        mocker.patch.object(finder, "find_user_shots_in_shows", return_value=iter([]))
        finder.find_approved_shots_targeted(active_shots)

        # Progress should be reported multiple times
        assert progress_callback.call_count > 2
        # Should reach 100%
        assert any(call[0][0] == 100 for call in progress_callback.call_args_list)

    def test_find_approved_filters_correctly(self, mocker) -> None:
        """Test that filtering works correctly for complex scenarios."""
        finder = TargetedShotsFinder()

        # Create shots with identical show/seq but different shot numbers
        active_shots = [
            Shot(show="show1", sequence="010", shot="0010", workspace_path="/path1"),
            Shot(show="show1", sequence="010", shot="0020", workspace_path="/path2"),
        ]

        all_shots = [
            # These should be filtered out (active)
            Shot(show="show1", sequence="010", shot="0010", workspace_path="/path1"),
            Shot(show="show1", sequence="010", shot="0020", workspace_path="/path2"),
            # These should be included (approved)
            Shot(show="show1", sequence="010", shot="0030", workspace_path="/path3"),
            Shot(show="show1", sequence="010", shot="0040", workspace_path="/path4"),
            Shot(show="show1", sequence="020", shot="0010", workspace_path="/path5"),
        ]

        mocker.patch.object(
            finder, "extract_shows_from_active_shots", return_value={"show1"}
        )
        mocker.patch.object(
            finder, "find_user_shots_in_shows", return_value=iter(all_shots)
        )
        approved = finder.find_approved_shots_targeted(active_shots)

        assert len(approved) == 3
        shot_numbers = [s.shot for s in approved]
        assert "0030" in shot_numbers
        assert "0040" in shot_numbers
        assert "0010" in shot_numbers  # From sequence 020


class TestGetShotDetails:
    """Test get_shot_details method."""

    def test_get_basic_details(self) -> None:
        """Test getting basic shot details."""
        finder = TargetedShotsFinder(username="john")
        shot = Shot(
            show="test_show",
            sequence="010",
            shot="0010",
            workspace_path=f"{Config.Paths.SHOWS_ROOT}/test_show/shots/010/0010",
        )

        details = finder.get_shot_details(shot)

        assert details["show"] == "test_show"
        assert details["sequence"] == "010"
        assert details["shot"] == "0010"
        assert (
            details["workspace_path"] == f"{Config.Paths.SHOWS_ROOT}/test_show/shots/010/0010"
        )
        assert (
            details["user_path"]
            == f"{Config.Paths.SHOWS_ROOT}/test_show/shots/010/0010/user/john"
        )
        assert (
            details["status"] == "unknown"
        )  # no approved/user dirs → _get_shot_status returns unknown

    def test_get_details_with_existing_user_dir(self, tmp_path: Path) -> None:
        """Test details when user directory exists."""
        finder = TargetedShotsFinder(username="john")

        workspace = tmp_path / "workspace"
        user_dir = workspace / "user" / "john"
        user_dir.mkdir(parents=True)

        # Create some work files
        (user_dir / "test.3de").touch()
        (user_dir / "comp.nk").touch()
        (user_dir / "anim.ma").touch()

        shot = Shot(
            show="test", sequence="010", shot="0010", workspace_path=str(workspace)
        )

        details = finder.get_shot_details(shot)

        assert details["user_dir_exists"] == "True"
        assert details["has_3de"] == "True"
        assert details["has_nuke"] == "True"
        assert details["has_maya"] == "True"

    def test_get_details_with_nonexistent_user_dir(self) -> None:
        """Test details when user directory doesn't exist."""
        finder = TargetedShotsFinder(username="john")
        shot = Shot(
            show="test", sequence="010", shot="0010", workspace_path="/nonexistent/path"
        )

        details = finder.get_shot_details(shot)

        assert details["user_dir_exists"] == "False"
        # Should not have work file info
        assert "has_3de" not in details
        assert "has_nuke" not in details
        assert "has_maya" not in details


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_concurrent_future_timeout(self, tmp_path: Path, mocker, caplog) -> None:
        """Test handling of concurrent.futures timeout."""
        finder = TargetedShotsFinder()

        # Create a mock executor that sets up future_to_show properly
        mock_future = MagicMock(spec=Future)
        mock_future.result.side_effect = FuturesTimeoutError()

        mock_executor_class = mocker.patch("concurrent.futures.ThreadPoolExecutor")
        mock_executor = MagicMock()
        mock_executor_class.return_value.__enter__.return_value = mock_executor
        mock_executor.submit.return_value = mock_future
        mocker.patch("concurrent.futures.as_completed", return_value=[mock_future])
        with caplog.at_level(logging.WARNING, logger="shots.targeted_shot_finder"):
            list(finder.find_user_shots_in_shows({"show1"}, tmp_path))

        assert any("Timeout processing" in r.message for r in caplog.records)

    def test_concurrent_future_exception(self, tmp_path: Path, mocker, caplog) -> None:
        """Test handling of concurrent.futures exceptions."""
        finder = TargetedShotsFinder()

        mock_future = MagicMock(spec=Future)
        mock_future.result.side_effect = Exception("Future failed")

        mock_executor_class = mocker.patch("concurrent.futures.ThreadPoolExecutor")
        mock_executor = MagicMock()
        mock_executor_class.return_value.__enter__.return_value = mock_executor
        mock_executor.submit.return_value = mock_future
        mocker.patch("concurrent.futures.as_completed", return_value=[mock_future])
        with caplog.at_level(logging.ERROR, logger="shots.targeted_shot_finder"):
            list(finder.find_user_shots_in_shows({"show1"}, tmp_path))

        assert any("Error processing" in r.message for r in caplog.records)

    def test_mock_mode_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test username handling in mock mode."""
        monkeypatch.setenv("SHOTBOT_MOCK", "1")
        # In mock mode, should use gabriel-h
        finder = TargetedShotsFinder()
        assert finder.username == "gabriel-h"
