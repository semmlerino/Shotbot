"""Comprehensive integration tests for key ShotBot features.

This module tests the end-to-end functionality of recently fixed features:
1. Raw Plate Finder with flexible patterns and priority ordering
2. File URL Generation for non-blocking folder opening
3. 3DE Scene Deduplication and display name simplification
4. 3DE Scene Caching Persistence across application restarts
"""

import tempfile
import time
from collections import defaultdict
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QThreadPool, QUrl

from cache_manager import CacheManager
from raw_plate_finder import RawPlateFinder
from shot_model import Shot
from threede_scene_model import ThreeDEScene, ThreeDESceneModel
from thumbnail_widget_base import FolderOpenerWorker
from utils import PathUtils


class TestRawPlateFinderIntegration:
    """Integration tests for Raw Plate Finder with flexible pattern discovery."""

    @pytest.fixture
    def plate_structure_setup(self):
        """Create a comprehensive raw plate directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)

            # Create shot workspace
            shot_workspace = base_path / "shows/testshow/shots/TST/TST_0010"
            plate_base = shot_workspace / "publish/turnover/plate/input_plate"

            # Create various plate patterns with different priorities
            plate_configs = [
                ("FG01", "v002", "aces", 2000.0),  # Newest FG01
                ("FG01", "v001", "aces", 1000.0),  # Older FG01
                (
                    "BG01",
                    "v001",
                    "lin_rec709",
                    1500.0,
                ),  # BG01 should be preferred over FG01
                ("bg01", "v001", "aces", 1200.0),  # Lowercase bg01
                ("FG02", "v003", "srgb", 1800.0),  # FG02
                ("plate", "v001", "aces", 800.0),  # Generic plate name
            ]

            shot_name = "TST_0010"
            created_plates = []

            for plate_name, version, color_space, mtime in plate_configs:
                plate_dir = plate_base / plate_name / version / "exr" / "2048x1152"
                plate_dir.mkdir(parents=True, exist_ok=True)

                # Create actual plate files
                for frame in [1001, 1002, 1003]:
                    plate_file = (
                        plate_dir
                        / f"{shot_name}_turnover-plate_{plate_name}_{color_space}_{version}.{frame}.exr"
                    )
                    plate_file.touch()
                    # Set mtime for proper version detection using os.utime
                    import os

                    os.utime(plate_file, (mtime, mtime))

                created_plates.append(
                    {
                        "name": plate_name,
                        "version": version,
                        "color_space": color_space,
                        "path": plate_dir,
                        "mtime": mtime,
                    }
                )

            yield {
                "shot_workspace": str(shot_workspace),
                "shot_name": shot_name,
                "plate_base": plate_base,
                "plates": created_plates,
            }

    def test_discover_plate_directories_priority_ordering(self, plate_structure_setup):
        """Test that plate directories are discovered in correct priority order."""
        plate_base = plate_structure_setup["plate_base"]

        # Test the new discover_plate_directories method
        plates = PathUtils.discover_plate_directories(plate_base)

        # Should find all plate types
        plate_names = [name for name, priority in plates]
        assert "BG01" in plate_names
        assert "bg01" in plate_names
        assert "FG01" in plate_names
        assert "FG02" in plate_names
        assert "plate" in plate_names

        # Verify priority ordering (BG01 should be first due to highest priority)
        assert plates[0][0] == "BG01"
        assert plates[0][1] == 10  # Priority from config

        # bg01 should be second (priority 9)
        bg01_entry = next((name, pri) for name, pri in plates if name == "bg01")
        assert bg01_entry[1] == 9

        # FG01 should have lower priority than BG variants
        fg01_entry = next((name, pri) for name, pri in plates if name == "FG01")
        assert fg01_entry[1] == 7
        assert fg01_entry[1] < bg01_entry[1]

    def test_raw_plate_finder_priority_selection(self, plate_structure_setup):
        """Test that raw plate finder selects plates based on priority, not just version."""
        shot_workspace = plate_structure_setup["shot_workspace"]
        shot_name = plate_structure_setup["shot_name"]

        # Find latest raw plate - should prefer BG01 over FG01 even if FG01 is newer
        latest_plate = RawPlateFinder.find_latest_raw_plate(shot_workspace, shot_name)

        assert latest_plate is not None
        # Should select BG01 due to higher priority (even though FG01 v002 is newer)
        assert "BG01" in latest_plate
        assert "v001" in latest_plate
        assert "lin_rec709" in latest_plate  # BG01's color space
        assert "####" in latest_plate  # Frame pattern

    def test_raw_plate_finder_version_selection_within_same_plate(
        self, plate_structure_setup
    ):
        """Test version selection within the same plate type."""
        # Remove BG01 and bg01 to test FG01 version selection
        plate_base = plate_structure_setup["plate_base"]

        # Remove higher priority plates
        import shutil

        if (plate_base / "BG01").exists():
            shutil.rmtree(plate_base / "BG01")
        if (plate_base / "bg01").exists():
            shutil.rmtree(plate_base / "bg01")

        shot_workspace = plate_structure_setup["shot_workspace"]
        shot_name = plate_structure_setup["shot_name"]

        latest_plate = RawPlateFinder.find_latest_raw_plate(shot_workspace, shot_name)

        assert latest_plate is not None
        # Should now select FG01 and prefer v002 (newer version)
        assert "FG01" in latest_plate
        assert (
            "v002" in latest_plate
        )  # Should select newer version within same plate type

    def test_raw_plate_finder_color_space_detection(self, plate_structure_setup):
        """Test automatic color space detection from existing files."""
        shot_workspace = plate_structure_setup["shot_workspace"]
        shot_name = plate_structure_setup["shot_name"]

        # Mock the file discovery to test pattern matching
        with patch(
            "raw_plate_finder.RawPlateFinder._find_plate_file_pattern"
        ) as mock_pattern:
            # Test different color space patterns
            test_cases = [
                "TST_0010_turnover-plate_BG01_lin_rec709_v001.1001.exr",
                "TST_0010_turnover-plate_FG01_aces_v002.1001.exr",
                "TST_0010_turnover-plate_FG02srgb_v003.1001.exr",  # No underscore before color space
            ]

            for test_file in test_cases:
                mock_pattern.return_value = (
                    f"/path/to/{test_file.replace('1001', '####')}"
                )

                plate = RawPlateFinder.find_latest_raw_plate(shot_workspace, shot_name)

                assert plate is not None
                assert "####" in plate
                # Should extract color space correctly
                if "lin_rec709" in test_file:
                    assert "lin_rec709" in plate
                elif "aces" in test_file:
                    assert "aces" in plate
                elif "srgb" in test_file:
                    assert "srgb" in plate

    def test_raw_plate_finder_missing_plates_graceful_handling(self):
        """Test graceful handling when no plates are found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create empty shot structure
            shot_workspace = Path(tmpdir) / "empty_shot"
            shot_workspace.mkdir(parents=True)

            result = RawPlateFinder.find_latest_raw_plate(
                str(shot_workspace), "EMPTY_001"
            )

            assert result is None  # Should handle gracefully

    def test_raw_plate_verification_workflow(self, plate_structure_setup):
        """Test the complete workflow: discovery → selection → verification."""
        shot_workspace = plate_structure_setup["shot_workspace"]
        shot_name = plate_structure_setup["shot_name"]

        # Step 1: Find plate
        latest_plate = RawPlateFinder.find_latest_raw_plate(shot_workspace, shot_name)
        assert latest_plate is not None

        # Step 2: Verify it exists
        exists = RawPlateFinder.verify_plate_exists(latest_plate)
        assert exists is True

        # Step 3: Extract version info
        version = RawPlateFinder.get_version_from_path(latest_plate)
        assert version is not None
        assert version.startswith("v")


class TestFileUrlGenerationIntegration:
    """Integration tests for non-blocking folder opening functionality."""

    @pytest.fixture
    def folder_structure(self):
        """Create test folder structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)

            # Create various folder types
            folders = {
                "normal": base_path / "normal_folder",
                "spaces": base_path / "folder with spaces",
                "special": base_path / "folder_with-special@chars",
                "unicode": base_path / "фолдер",  # Cyrillic
                "deep": base_path / "very/deep/nested/folder/structure",
                "relative": "relative/path/from/cwd",
            }

            # Create actual folders
            for name, path in folders.items():
                if name != "relative":  # Skip relative path
                    path.mkdir(parents=True, exist_ok=True)

            yield {"base_path": base_path, "folders": folders}

    def test_folder_opener_worker_url_generation(self, folder_structure):
        """Test that URLs are generated correctly with proper leading slashes."""
        folders = folder_structure["folders"]

        for folder_type, folder_path in folders.items():
            if folder_type == "relative":
                continue  # Skip relative paths for this test

            worker = FolderOpenerWorker(str(folder_path))

            # Mock QDesktopServices to capture the URL
            with patch("thumbnail_widget_base.QDesktopServices.openUrl") as mock_open:
                worker.run()

                # Should have been called once
                mock_open.assert_called_once()

                # Extract the URL that was passed
                called_url = mock_open.call_args[0][0]
                assert isinstance(called_url, QUrl)

                # Verify URL properties
                assert called_url.scheme() == "file"
                url_path = called_url.path()

                # Must have leading slash for proper file URLs
                assert url_path.startswith("/"), (
                    f"URL path missing leading slash: {url_path}"
                )

                # Should contain the folder name
                assert folder_path.name in url_path

    def test_folder_opener_fallback_mechanisms(self, folder_structure):
        """Test fallback to system commands when Qt fails."""
        folder_path = folder_structure["folders"]["normal"]
        worker = FolderOpenerWorker(str(folder_path))

        # Track signal emissions
        success_signals = []
        error_signals = []

        worker.signals.success.connect(lambda: success_signals.append(True))
        worker.signals.error.connect(lambda msg: error_signals.append(msg))

        # Mock Qt failure, subprocess success
        with patch(
            "thumbnail_widget_base.QDesktopServices.openUrl", return_value=False
        ):
            with patch("subprocess.run") as mock_subprocess:
                # Mock successful subprocess call
                mock_subprocess.return_value = None

                worker.run()

                # Should have attempted subprocess fallback
                mock_subprocess.assert_called_once()

                # Should emit success signal
                assert len(success_signals) == 1
                assert len(error_signals) == 0

    def test_folder_opener_platform_specific_commands(self, folder_structure):
        """Test that correct platform-specific commands are used."""
        folder_path = folder_structure["folders"]["normal"]
        worker = FolderOpenerWorker(str(folder_path))

        # Test different platform scenarios
        platform_commands = {
            "darwin": ["open", str(folder_path)],
            "win32": ["explorer", str(folder_path)],
            "linux": ["xdg-open", str(folder_path)],
        }

        for platform, expected_cmd in platform_commands.items():
            with patch("sys.platform", platform):
                with patch(
                    "thumbnail_widget_base.QDesktopServices.openUrl", return_value=False
                ):
                    with patch("subprocess.run") as mock_subprocess:
                        worker.run()

                        mock_subprocess.assert_called_once()
                        actual_cmd = mock_subprocess.call_args[0][0]
                        assert actual_cmd == expected_cmd

    def test_folder_opener_linux_gio_fallback(self, folder_structure):
        """Test Linux gio fallback when xdg-open fails."""
        folder_path = folder_structure["folders"]["normal"]
        worker = FolderOpenerWorker(str(folder_path))

        error_signals = []
        worker.signals.error.connect(lambda msg: error_signals.append(msg))

        with patch("sys.platform", "linux"):
            with patch(
                "thumbnail_widget_base.QDesktopServices.openUrl", return_value=False
            ):
                with patch("subprocess.run") as mock_subprocess:
                    # First call (xdg-open) fails, second (gio) succeeds
                    mock_subprocess.side_effect = [
                        FileNotFoundError("xdg-open not found"),
                        None,  # gio succeeds
                    ]

                    worker.run()

                    # Should have tried both commands
                    assert mock_subprocess.call_count == 2
                    assert mock_subprocess.call_args_list[0][0][0] == [
                        "xdg-open",
                        str(folder_path),
                    ]
                    assert mock_subprocess.call_args_list[1][0][0] == [
                        "gio",
                        "open",
                        str(folder_path),
                    ]

                    # Should not emit error if gio succeeds
                    assert len(error_signals) == 0

    def test_folder_opener_nonexistent_path_handling(self):
        """Test graceful handling of non-existent paths."""
        nonexistent_path = "/this/path/absolutely/does/not/exist"
        worker = FolderOpenerWorker(nonexistent_path)

        error_signals = []
        success_signals = []

        worker.signals.error.connect(lambda msg: error_signals.append(msg))
        worker.signals.success.connect(lambda: success_signals.append(True))

        worker.run()

        # Should emit error signal
        assert len(error_signals) == 1
        assert len(success_signals) == 0
        assert "does not exist" in error_signals[0]

    def test_folder_opener_concurrent_operations(self, folder_structure):
        """Test that multiple concurrent folder opening operations don't interfere."""
        folders = list(folder_structure["folders"].values())[:3]  # Test with 3 folders
        workers = []

        # Create workers for each folder
        for folder in folders:
            if isinstance(folder, str) and not folder.startswith("/"):
                continue  # Skip relative paths
            worker = FolderOpenerWorker(str(folder))
            workers.append(worker)

        success_count = []

        def on_success():
            success_count.append(1)

        # Connect signals and mock successful operations
        with patch("thumbnail_widget_base.QDesktopServices.openUrl", return_value=True):
            for worker in workers:
                worker.signals.success.connect(on_success)
                worker.run()  # Run synchronously for test determinism

        # All operations should succeed
        assert len(success_count) == len(workers)

    def test_folder_opener_thread_pool_integration(self, folder_structure, qtbot):
        """Test integration with Qt's thread pool system."""
        folder_path = folder_structure["folders"]["normal"]
        worker = FolderOpenerWorker(str(folder_path))

        completed = []

        def on_success():
            completed.append(True)

        worker.signals.success.connect(on_success)

        # Run in actual thread pool
        with patch("thumbnail_widget_base.QDesktopServices.openUrl", return_value=True):
            QThreadPool.globalInstance().start(worker)

            # Wait for completion with longer timeout and process events
            for _ in range(50):  # 5 second timeout
                qtbot.wait(100)
                if len(completed) > 0:
                    break

            # Give it one more chance to complete
            QThreadPool.globalInstance().waitForDone(2000)

            # Should have completed successfully
            assert len(completed) == 1, (
                f"Expected 1 completion, got {len(completed)}. Worker may not have executed in thread pool."
            )


class TestThreeDESceneDeduplicationIntegration:
    """Integration tests for 3DE scene deduplication and display name simplification."""

    @pytest.fixture
    def scene_deduplication_setup(self):
        """Create comprehensive 3DE scene data for deduplication testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()

            # Create cache manager with isolated directory
            cache_manager = CacheManager(cache_dir=cache_dir)

            # Create test shots
            shots = [
                Shot(
                    "show_a", "seq_01", "0010", "/shows/show_a/shots/seq_01/seq_01_0010"
                ),
                Shot(
                    "show_a", "seq_01", "0020", "/shows/show_a/shots/seq_01/seq_01_0020"
                ),
                Shot(
                    "show_b", "seq_02", "0030", "/shows/show_b/shots/seq_02/seq_02_0030"
                ),
            ]

            # Create model with our isolated cache
            model = ThreeDESceneModel(cache_manager, load_cache=False)

            yield {
                "cache_manager": cache_manager,
                "model": model,
                "shots": shots,
                "cache_dir": cache_dir,
            }

    def test_scene_deduplication_one_per_shot(self, scene_deduplication_setup):
        """Test that only one scene per shot is kept after deduplication."""
        model = scene_deduplication_setup["model"]
        shots = scene_deduplication_setup["shots"]

        # Create multiple scenes for the same shot
        discovered_scenes = [
            # Shot 0010 - multiple scenes (should be reduced to 1)
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0010",
                workspace_path="/shows/show_a/shots/seq_01/seq_01_0010",
                user="artist1",
                plate="FG01",
                scene_path=self._mock_scene_path("scene1_fg.3de", 3000.0),
            ),
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0010",
                workspace_path="/shows/show_a/shots/seq_01/seq_01_0010",
                user="artist2",
                plate="BG01",
                scene_path=self._mock_scene_path("scene2_bg.3de", 2000.0),
            ),
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0010",
                workspace_path="/shows/show_a/shots/seq_01/seq_01_0010",
                user="artist3",
                plate="FG01",
                scene_path=self._mock_scene_path(
                    "scene3_fg_old.3de", 1000.0
                ),  # Older FG01
            ),
            # Shot 0020 - single scene (should be kept)
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0020",
                workspace_path="/shows/show_a/shots/seq_01/seq_01_0020",
                user="artist4",
                plate="BG01",
                scene_path=self._mock_scene_path("scene4_bg.3de", 1500.0),
            ),
            # Shot 0030 - multiple scenes (should be reduced to 1)
            ThreeDEScene(
                show="show_b",
                sequence="seq_02",
                shot="0030",
                workspace_path="/shows/show_b/shots/seq_02/seq_02_0030",
                user="artist5",
                plate="FG01",
                scene_path=self._mock_scene_path("scene5_fg.3de", 2500.0),
            ),
            ThreeDEScene(
                show="show_b",
                sequence="seq_02",
                shot="0030",
                workspace_path="/shows/show_b/shots/seq_02/seq_02_0030",
                user="artist6",
                plate="BG01",
                scene_path=self._mock_scene_path("scene6_bg.3de", 2800.0),  # Newer BG01
            ),
        ]

        # Mock scene discovery
        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = discovered_scenes

            success, has_changes = model.refresh_scenes(shots)

            assert success
            assert has_changes

            # Should have exactly 3 scenes (one per shot)
            assert len(model.scenes) == 3

            # Verify each shot has only one scene
            shot_scene_count = defaultdict(int)
            for scene in model.scenes:
                shot_key = f"{scene.show}_{scene.sequence}_{scene.shot}"
                shot_scene_count[shot_key] += 1

            for shot_key, count in shot_scene_count.items():
                assert count == 1, f"Shot {shot_key} has {count} scenes, expected 1"

    def test_scene_selection_criteria_priority_and_mtime(
        self, scene_deduplication_setup
    ):
        """Test that scene selection follows priority (plate type) then modification time."""
        model = scene_deduplication_setup["model"]
        shots = [
            scene_deduplication_setup["shots"][0]
        ]  # Just one shot for focused testing

        # Create scenes with different priorities and mtimes
        scenes_with_mixed_priorities = [
            # FG01 - newer but lower priority
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user1",
                plate="FG01",
                scene_path=self._mock_scene_path("fg_newer.3de", 3000.0),
            ),
            # BG01 - older but higher priority
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user2",
                plate="BG01",
                scene_path=self._mock_scene_path("bg_older.3de", 2000.0),
            ),
            # Another BG01 - newest and same priority
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user3",
                plate="BG01",
                scene_path=self._mock_scene_path("bg_newest.3de", 3500.0),
            ),
        ]

        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = (
                scenes_with_mixed_priorities
            )

            success, has_changes = model.refresh_scenes(shots)

            assert success and has_changes
            assert len(model.scenes) == 1

            # Should select the newest BG01 (highest priority, newest mtime)
            selected = model.scenes[0]
            assert selected.user == "user3"
            assert selected.plate == "BG01"
            assert selected.scene_path.name == "bg_newest.3de"

    def test_display_name_simplification(self, scene_deduplication_setup):
        """Test that display names are simplified after deduplication."""
        model = scene_deduplication_setup["model"]
        shots = scene_deduplication_setup["shots"][:1]  # One shot

        test_scene = ThreeDEScene(
            show="show_a",
            sequence="seq_01",
            shot="0010",
            workspace_path="/path",
            user="test_artist",
            plate="FG01",
            scene_path=self._mock_scene_path("test_scene.3de", 1000.0),
        )

        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = [test_scene]

            model.refresh_scenes(shots)

            scene = model.scenes[0]
            display_name = scene.display_name

            # Display name should not include plate info (since deduplicated)
            assert "FG01" not in display_name, (
                "Display name should not include plate info after deduplication"
            )
            assert "test_artist" in display_name, (
                "Display name should include artist name"
            )
            assert "seq_01_0010" in display_name, (
                "Display name should include shot name"
            )

    def test_deduplication_with_file_access_errors(self, scene_deduplication_setup):
        """Test deduplication handles file access errors gracefully."""
        model = scene_deduplication_setup["model"]
        shots = scene_deduplication_setup["shots"][:1]

        scenes_with_errors = [
            # Valid scene
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user1",
                plate="BG01",
                scene_path=self._mock_scene_path("valid.3de", 2000.0),
            ),
            # Scene with file access error
            ThreeDEScene(
                show="show_a",
                sequence="seq_01",
                shot="0010",
                workspace_path="/path",
                user="user2",
                plate="FG01",
                scene_path=self._mock_scene_path_error(
                    "error.3de"
                ),  # Will raise OSError on stat()
            ),
        ]

        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = scenes_with_errors

            success, has_changes = model.refresh_scenes(shots)

            assert success  # Should still succeed
            assert has_changes
            assert len(model.scenes) == 1

            # Should select the valid scene (error scene should be filtered out)
            selected = model.scenes[0]
            assert selected.user == "user1"
            assert selected.scene_path.name == "valid.3de"

    def test_deduplication_empty_results_handling(self, scene_deduplication_setup):
        """Test handling of empty discovery results."""
        model = scene_deduplication_setup["model"]
        shots = scene_deduplication_setup["shots"]

        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = []  # Empty results

            success, has_changes = model.refresh_scenes(shots)

            assert success
            assert len(model.scenes) == 0

            # Second refresh should detect no changes
            success2, has_changes2 = model.refresh_scenes(shots)
            assert success2
            assert not has_changes2  # No changes from empty to empty

    def _mock_scene_path(self, filename: str, mtime: float) -> Mock:
        """Create a mock Path object with specified mtime."""
        mock_path = Mock(spec=Path)
        mock_path.name = filename
        mock_path.__str__ = Mock(return_value=f"/mock/path/{filename}")

        mock_stat = Mock()
        mock_stat.st_mtime = mtime
        mock_path.stat.return_value = mock_stat

        return mock_path

    def _mock_scene_path_error(self, filename: str) -> Mock:
        """Create a mock Path object that raises OSError on stat()."""
        mock_path = Mock(spec=Path)
        mock_path.name = filename
        mock_path.__str__ = Mock(return_value=f"/mock/path/{filename}")
        mock_path.stat.side_effect = OSError("File not found")

        return mock_path


class TestThreeDESceneCachePersistenceIntegration:
    """Integration tests for 3DE scene caching persistence across application restarts."""

    @pytest.fixture
    def cache_persistence_setup(self):
        """Set up isolated cache environment for persistence testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "persistent_cache"
            cache_dir.mkdir()

            # Test shots
            shots = [
                Shot(
                    "persist_show",
                    "SEQ01",
                    "0010",
                    "/shows/persist_show/shots/SEQ01/SEQ01_0010",
                ),
                Shot(
                    "persist_show",
                    "SEQ01",
                    "0020",
                    "/shows/persist_show/shots/SEQ01/SEQ01_0020",
                ),
            ]

            yield {"cache_dir": cache_dir, "shots": shots}

    def test_cache_persistence_across_app_restarts(self, cache_persistence_setup):
        """Test that deduplicated scenes persist across application restarts."""
        cache_dir = cache_persistence_setup["cache_dir"]
        shots = cache_persistence_setup["shots"]

        # Original scenes before deduplication
        original_scenes = [
            ThreeDEScene(
                show="persist_show",
                sequence="SEQ01",
                shot="0010",
                workspace_path="/path/0010",
                user="artist1",
                plate="FG01",
                scene_path=self._mock_scene_path("scene1_fg.3de", 3000.0),
            ),
            ThreeDEScene(
                show="persist_show",
                sequence="SEQ01",
                shot="0010",
                workspace_path="/path/0010",
                user="artist2",
                plate="BG01",
                scene_path=self._mock_scene_path("scene2_bg.3de", 2000.0),
            ),
            ThreeDEScene(
                show="persist_show",
                sequence="SEQ01",
                shot="0020",
                workspace_path="/path/0020",
                user="artist3",
                plate="BG01",
                scene_path=self._mock_scene_path("scene3_bg.3de", 2500.0),
            ),
        ]

        # First application session: discovery and caching
        cache_manager1 = CacheManager(cache_dir=cache_dir)
        model1 = ThreeDESceneModel(cache_manager1, load_cache=False)

        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = original_scenes

            success, has_changes = model1.refresh_scenes(shots)
            assert success and has_changes

            # Should be deduplicated to 2 scenes (one per shot)
            assert len(model1.scenes) == 2

            # Verify deduplication results
            shot_0010_scene = next(s for s in model1.scenes if s.shot == "0010")
            shot_0020_scene = next(s for s in model1.scenes if s.shot == "0020")

            assert shot_0010_scene.user == "artist1"  # FG01 with highest mtime
            assert shot_0010_scene.plate == "FG01"
            assert shot_0020_scene.user == "artist3"  # Only BG01 scene
            assert shot_0020_scene.plate == "BG01"

        # Simulate application restart: create new cache manager and model
        cache_manager2 = CacheManager(cache_dir=cache_dir)
        model2 = ThreeDESceneModel(cache_manager2, load_cache=True)  # Load from cache

        # Verify scenes were loaded from cache
        assert len(model2.scenes) == 2

        # Verify the cached data matches the original deduplication results
        cached_shot_0010 = next(s for s in model2.scenes if s.shot == "0010")
        cached_shot_0020 = next(s for s in model2.scenes if s.shot == "0020")

        assert cached_shot_0010.user == "artist1"
        assert cached_shot_0010.plate == "FG01"
        assert cached_shot_0010.scene_path.name == "scene1_fg.3de"

        assert cached_shot_0020.user == "artist3"
        assert cached_shot_0020.plate == "BG01"
        assert cached_shot_0020.scene_path.name == "scene3_bg.3de"

        # Verify display names are simplified
        assert "FG01" not in cached_shot_0010.display_name
        assert "BG01" not in cached_shot_0020.display_name

    def test_cache_ttl_refresh_mechanism(self, cache_persistence_setup):
        """Test that cache TTL works correctly and triggers refresh when expired."""
        cache_dir = cache_persistence_setup["cache_dir"]
        shots = cache_persistence_setup["shots"][:1]  # Use one shot for simplicity

        initial_scene = ThreeDEScene(
            show="persist_show",
            sequence="SEQ01",
            shot="0010",
            workspace_path="/path",
            user="initial_artist",
            plate="BG01",
            scene_path=self._mock_scene_path("initial_scene.3de", 1000.0),
        )

        updated_scene = ThreeDEScene(
            show="persist_show",
            sequence="SEQ01",
            shot="0010",
            workspace_path="/path",
            user="updated_artist",
            plate="FG01",
            scene_path=self._mock_scene_path("updated_scene.3de", 2000.0),
        )

        # Create cache manager with short TTL for testing
        cache_manager = CacheManager(cache_dir=cache_dir)

        # Override cache TTL for testing by patching Config
        with patch(
            "config.Config.CACHE_EXPIRY_MINUTES", 0.0017
        ):  # ~0.1 second in minutes
            model = ThreeDESceneModel(cache_manager, load_cache=False)

            # First refresh - cache initial scene
            with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
                mock_finder.find_all_scenes_in_shows.return_value = [initial_scene]

                success, has_changes = model.refresh_scenes(shots)
                assert success and has_changes
                assert len(model.scenes) == 1
                assert model.scenes[0].user == "initial_artist"

            # Wait for cache to expire
            time.sleep(0.2)

            # Second refresh - should detect cache expiry and fetch updated data
            with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
                mock_finder.find_all_scenes_in_shows.return_value = [updated_scene]

                success, has_changes = model.refresh_scenes(shots)
                assert (
                    success and has_changes
                )  # Should detect changes due to cache expiry
                assert len(model.scenes) == 1
                assert model.scenes[0].user == "updated_artist"

    def test_cache_corruption_recovery(self, cache_persistence_setup):
        """Test graceful recovery from corrupted cache files."""
        cache_dir = cache_persistence_setup["cache_dir"]
        shots = cache_persistence_setup["shots"][:1]

        # Create corrupt cache file
        cache_file = cache_dir / "threede_scenes.json"
        cache_file.write_text("{ invalid json content }")

        # Model should handle corrupt cache gracefully
        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ThreeDESceneModel(cache_manager, load_cache=True)

        # Should start with empty scenes (corrupt cache ignored)
        assert len(model.scenes) == 0

        # Should be able to populate with fresh data
        fresh_scene = ThreeDEScene(
            show="persist_show",
            sequence="SEQ01",
            shot="0010",
            workspace_path="/path",
            user="recovery_artist",
            plate="BG01",
            scene_path=self._mock_scene_path("recovery_scene.3de", 1000.0),
        )

        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = [fresh_scene]

            success, has_changes = model.refresh_scenes(shots)
            assert success and has_changes
            assert len(model.scenes) == 1
            assert model.scenes[0].user == "recovery_artist"

    def test_concurrent_cache_access(self, cache_persistence_setup):
        """Test behavior with concurrent cache access (simulated)."""
        cache_dir = cache_persistence_setup["cache_dir"]
        shots = cache_persistence_setup["shots"][:1]

        scene = ThreeDEScene(
            show="persist_show",
            sequence="SEQ01",
            shot="0010",
            workspace_path="/path",
            user="concurrent_artist",
            plate="BG01",
            scene_path=self._mock_scene_path("concurrent_scene.3de", 1000.0),
        )

        # Create multiple models sharing the same cache
        cache_manager1 = CacheManager(cache_dir=cache_dir)
        cache_manager2 = CacheManager(cache_dir=cache_dir)

        model1 = ThreeDESceneModel(cache_manager1, load_cache=False)
        model2 = ThreeDESceneModel(cache_manager2, load_cache=False)

        # First model populates cache
        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = [scene]

            success, has_changes = model1.refresh_scenes(shots)
            assert success and has_changes
            assert len(model1.scenes) == 1

        # Second model should load from cache
        model2._load_from_cache()
        assert len(model2.scenes) == 1
        assert model2.scenes[0].user == "concurrent_artist"

        # Both models should have consistent data
        assert len(model1.scenes) == len(model2.scenes)
        assert model1.scenes[0].user == model2.scenes[0].user

    def test_cache_size_limits_and_cleanup(self, cache_persistence_setup):
        """Test that cache respects size limits and cleans up appropriately."""
        cache_dir = cache_persistence_setup["cache_dir"]

        # Create many shots to test cache size limits
        many_shots = []
        many_scenes = []

        for i in range(100):  # Create 100 shots
            shot = Shot("big_show", "SEQ01", f"{i:04d}", f"/path/shot_{i:04d}")
            many_shots.append(shot)

            scene = ThreeDEScene(
                show="big_show",
                sequence="SEQ01",
                shot=f"{i:04d}",
                workspace_path=f"/path/shot_{i:04d}",
                user=f"artist_{i}",
                plate="BG01",
                scene_path=self._mock_scene_path(f"scene_{i:04d}.3de", 1000.0 + i),
            )
            many_scenes.append(scene)

        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ThreeDESceneModel(cache_manager, load_cache=False)

        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = many_scenes

            success, has_changes = model.refresh_scenes(many_shots)
            assert success and has_changes
            assert len(model.scenes) == 100  # Should handle large datasets

        # Verify cache file was created and is reasonable in size
        cache_file = cache_dir / "threede_scenes.json"
        assert cache_file.exists()

        # Cache file should not be excessively large (basic sanity check)
        cache_size_mb = cache_file.stat().st_size / (1024 * 1024)
        assert cache_size_mb < 10, f"Cache file too large: {cache_size_mb}MB"

    def _mock_scene_path(self, filename: str, mtime: float) -> Mock:
        """Create a mock Path object with specified mtime."""
        mock_path = Mock(spec=Path)
        mock_path.name = filename
        mock_path.__str__ = Mock(return_value=f"/mock/cache/path/{filename}")

        mock_stat = Mock()
        mock_stat.st_mtime = mtime
        mock_path.stat.return_value = mock_stat

        return mock_path


class TestKeyFeaturesWorkflowIntegration:
    """Integration tests for workflows combining multiple key features."""

    @pytest.fixture
    def complete_workflow_setup(self):
        """Set up complete environment for workflow testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)
            cache_dir = base_path / "cache"
            cache_dir.mkdir()

            # Create realistic show structure
            show_path = base_path / "shows/workflow_show/shots/WF/WF_0010"
            show_path.mkdir(parents=True)

            # Raw plates with different priorities
            plate_base = show_path / "publish/turnover/plate/input_plate"
            for plate_name, version in [("BG01", "v001"), ("FG01", "v002")]:
                plate_dir = plate_base / plate_name / version / "exr/2048x1152"
                plate_dir.mkdir(parents=True)

                for frame in [1001, 1002]:
                    plate_file = (
                        plate_dir
                        / f"WF_0010_turnover-plate_{plate_name}_aces_{version}.{frame}.exr"
                    )
                    plate_file.touch()

            # 3DE scenes from multiple users
            for user, plate in [
                ("user1", "FG01"),
                ("user2", "BG01"),
                ("user3", "FG01"),
            ]:
                scene_dir = (
                    show_path
                    / f"user/{user}/mm/3de/mm-default/scenes/scene/{plate}/v001"
                )
                scene_dir.mkdir(parents=True)
                (scene_dir / f"{user}_scene.3de").touch()

            # Thumbnails
            thumb_dir = show_path / "publish/editorial/cutref/v001/jpg/1920x1080"
            thumb_dir.mkdir(parents=True)
            (thumb_dir / "frame_001.jpg").touch()

            yield {
                "base_path": base_path,
                "cache_dir": cache_dir,
                "shot_workspace": str(show_path),
                "shot": Shot("workflow_show", "WF", "0010", str(show_path)),
            }

    def test_complete_shot_workflow(self, complete_workflow_setup):
        """Test complete workflow: raw plate discovery → 3DE scene deduplication → folder opening."""
        shot_workspace = complete_workflow_setup["shot_workspace"]
        shot = complete_workflow_setup["shot"]
        cache_dir = complete_workflow_setup["cache_dir"]

        # Step 1: Raw plate discovery should find BG01 (higher priority)
        latest_plate = RawPlateFinder.find_latest_raw_plate(
            shot_workspace, shot.full_name
        )
        assert latest_plate is not None
        assert "BG01" in latest_plate  # Should prefer BG01 over FG01
        assert RawPlateFinder.verify_plate_exists(latest_plate)

        # Step 2: 3DE scene discovery and deduplication
        cache_manager = CacheManager(cache_dir=cache_dir)
        scene_model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Mock scene discovery
        discovered_scenes = [
            ThreeDEScene(
                show="workflow_show",
                sequence="WF",
                shot="0010",
                workspace_path=shot_workspace,
                user="user1",
                plate="FG01",
                scene_path=self._mock_scene_path("user1_scene.3de", 3000.0),
            ),
            ThreeDEScene(
                show="workflow_show",
                sequence="WF",
                shot="0010",
                workspace_path=shot_workspace,
                user="user2",
                plate="BG01",
                scene_path=self._mock_scene_path("user2_scene.3de", 2000.0),
            ),
            ThreeDEScene(
                show="workflow_show",
                sequence="WF",
                shot="0010",
                workspace_path=shot_workspace,
                user="user3",
                plate="FG01",
                scene_path=self._mock_scene_path("user3_scene.3de", 1000.0),
            ),
        ]

        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = discovered_scenes

            success, has_changes = scene_model.refresh_scenes([shot])
            assert success and has_changes
            assert len(scene_model.scenes) == 1  # Deduplicated to one scene

            # Should select newest FG01 (user1, mtime=3000.0)
            selected_scene = scene_model.scenes[0]
            assert selected_scene.user == "user1"
            assert selected_scene.plate == "FG01"

        # Step 3: Folder opening should work non-blocking
        folder_worker = FolderOpenerWorker(shot_workspace)

        success_signals = []
        folder_worker.signals.success.connect(lambda: success_signals.append(True))

        with patch("thumbnail_widget_base.QDesktopServices.openUrl", return_value=True):
            folder_worker.run()

            assert len(success_signals) == 1

        # Step 4: Cache persistence verification
        scene_model2 = ThreeDESceneModel(cache_manager, load_cache=True)
        assert len(scene_model2.scenes) == 1
        assert scene_model2.scenes[0].user == "user1"  # Same result after cache reload

    def test_workflow_with_missing_data_resilience(self, complete_workflow_setup):
        """Test workflow resilience when some data is missing."""
        shot_workspace = complete_workflow_setup["shot_workspace"]
        shot = complete_workflow_setup["shot"]
        cache_dir = complete_workflow_setup["cache_dir"]

        # Remove some raw plate data
        plate_path = Path(shot_workspace) / "publish/turnover/plate/input_plate/FG01"
        if plate_path.exists():
            import shutil

            shutil.rmtree(plate_path)

        # Raw plate finder should still find BG01
        latest_plate = RawPlateFinder.find_latest_raw_plate(
            shot_workspace, shot.full_name
        )
        assert latest_plate is not None
        assert "BG01" in latest_plate

        # 3DE scene model should handle missing scenes gracefully
        cache_manager = CacheManager(cache_dir=cache_dir)
        scene_model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Mock empty discovery
        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = []

            success, has_changes = scene_model.refresh_scenes([shot])
            assert success  # Should succeed even with no scenes
            assert len(scene_model.scenes) == 0

        # Folder opening should still work
        folder_worker = FolderOpenerWorker(shot_workspace)

        success_signals = []
        folder_worker.signals.success.connect(lambda: success_signals.append(True))

        with patch("thumbnail_widget_base.QDesktopServices.openUrl", return_value=True):
            folder_worker.run()
            assert len(success_signals) == 1

    def test_workflow_performance_with_large_dataset(self, complete_workflow_setup):
        """Test workflow performance with large datasets."""
        cache_dir = complete_workflow_setup["cache_dir"]

        # Create many shots
        many_shots = []
        for i in range(50):  # 50 shots for performance testing
            shot = Shot(
                "perf_show",
                "PERF",
                f"{i:03d}",
                f"/shows/perf_show/shots/PERF/PERF_{i:03d}",
            )
            many_shots.append(shot)

        # Test 3DE scene processing performance
        cache_manager = CacheManager(cache_dir=cache_dir)
        scene_model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Create scenes for all shots
        many_scenes = []
        for shot in many_shots:
            scene = ThreeDEScene(
                show=shot.show,
                sequence=shot.sequence,
                shot=shot.shot,
                workspace_path=shot.workspace_path,
                user="perf_user",
                plate="BG01",
                scene_path=self._mock_scene_path(f"scene_{shot.shot}.3de", 1000.0),
            )
            many_scenes.append(scene)

        start_time = time.time()

        with patch("threede_scene_finder.ThreeDESceneFinder") as mock_finder:
            mock_finder.find_all_scenes_in_shows.return_value = many_scenes

            success, has_changes = scene_model.refresh_scenes(many_shots)

        processing_time = time.time() - start_time

        assert success
        assert len(scene_model.scenes) == 50
        # Processing should be reasonably fast (less than 2 seconds for 50 shots)
        assert processing_time < 2.0, f"Processing took too long: {processing_time}s"

    def _mock_scene_path(self, filename: str, mtime: float) -> Mock:
        """Create a mock Path object with specified mtime."""
        mock_path = Mock(spec=Path)
        mock_path.name = filename
        mock_path.__str__ = Mock(return_value=f"/mock/workflow/path/{filename}")

        mock_stat = Mock()
        mock_stat.st_mtime = mtime
        mock_path.stat.return_value = mock_stat

        return mock_path
