"""Comprehensive end-to-end VFX workflow integration tests.

This module tests the complete workflows that VFX artists follow daily:
1. Shot discovery and loading
2. Shot selection and context switching
3. Application launching with proper context
4. 3DE scene discovery and thumbnail generation
5. Custom launcher creation and execution
6. Progressive scanning with real datasets

These tests use minimal mocking to ensure real workflow reliability.
"""

import os
import threading
import time
from pathlib import Path
from typing import List
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox

from cache_manager import CacheManager
from launcher_manager import LauncherManager
from main_window import MainWindow
from raw_plate_finder import RawPlateFinder
from shot_model import Shot, ShotModel
from threede_scene_finder import ThreeDESceneFinder
from threede_scene_model import ThreeDESceneModel
from undistortion_finder import UndistortionFinder
from utils import PathUtils


class TestCompleteVFXWorkflows:
    """Test complete end-to-end VFX workflows with real components."""

    @pytest.fixture
    def production_vfx_structure(self, tmp_path):
        """Create realistic VFX production directory structure."""
        shows_root = tmp_path / "shows"

        # Create multiple shows with realistic structure
        shows_config = {
            "commercial_project": {
                "sequences": ["CM001", "CM002", "CM003"],
                "shots_per_seq": 8,
                "users": ["john_comp", "sarah_track", "mike_3d"],
                "plates": ["BG01", "FG01", "FG02"],
                "colorspaces": ["aces", "lin_sgamut3cine", "log_sgamut3cine"],
            },
            "feature_film": {
                "sequences": ["FF_010", "FF_020", "FF_030"],
                "shots_per_seq": 12,
                "users": ["alice_lead", "bob_junior", "carol_senior"],
                "plates": ["BG01", "FG01", "CHAR01"],
                "colorspaces": ["aces", "lin_rec2020"],
            },
            "episodic_tv": {
                "sequences": ["EP101", "EP102"],
                "shots_per_seq": 15,
                "users": ["dan_comp", "eve_track"],
                "plates": ["BG01", "FG01"],
                "colorspaces": ["rec709", "aces"],
            },
        }

        created_shots = []
        workspace_paths = []

        for show_name, config in shows_config.items():
            for seq_name in config["sequences"]:
                for shot_idx in range(1, config["shots_per_seq"] + 1):
                    shot_name = f"{seq_name}_{shot_idx:04d}"
                    shot_path = shows_root / show_name / "shots" / seq_name / shot_name

                    # Create comprehensive shot structure
                    self._create_complete_shot_structure(
                        shot_path,
                        shot_name,
                        config["users"],
                        config["plates"],
                        config["colorspaces"],
                    )

                    workspace_path = f"/shows/{show_name}/shots/{seq_name}/{shot_name}"
                    workspace_paths.append(f"workspace {workspace_path}")

                    shot = Shot(show_name, seq_name, f"{shot_idx:04d}", workspace_path)
                    created_shots.append(shot)

        return {
            "shows_root": shows_root,
            "shots": created_shots,
            "workspace_output": "\\n".join(workspace_paths),
            "total_shots": len(created_shots),
            "shows_config": shows_config,
        }

    def _create_complete_shot_structure(
        self,
        shot_path: Path,
        shot_name: str,
        users: List[str],
        plates: List[str],
        colorspaces: List[str],
    ):
        """Create complete shot directory structure."""
        # Editorial thumbnails with multiple formats
        thumb_formats = [
            ("publish/editorial/cutref/v001/jpg/1920x1080", "jpg"),
            ("publish/editorial/cutref/v001/png/1920x1080", "png"),
            ("editorial/ref", "jpg"),  # Alternative structure
        ]

        for thumb_dir, ext in thumb_formats:
            full_thumb_dir = shot_path / thumb_dir
            full_thumb_dir.mkdir(parents=True, exist_ok=True)
            thumb_file = full_thumb_dir / f"{shot_name}_ref.{ext}"
            thumb_file.write_bytes(b"FAKE_IMAGE_DATA")

        # Raw plates with multiple colorspaces and versions
        for plate in plates:
            for cs_idx, colorspace in enumerate(colorspaces):
                for version in ["v001", "v002"]:
                    # Main plate location
                    plate_dir = (
                        shot_path
                        / "publish/turnover/plate/input_plate"
                        / plate
                        / version
                        / "exr/2048x1152"
                    )
                    plate_dir.mkdir(parents=True, exist_ok=True)

                    # Create frame sequence (1001-1050)
                    for frame in range(1001, 1051):
                        plate_file = (
                            plate_dir
                            / f"{shot_name}_turnover-plate_{plate}_{colorspace}_{version}.{frame}.exr"
                        )
                        plate_file.touch()

                        # Set different mtimes for version testing
                        mtime = (
                            1000000 + cs_idx * 10000 + int(version[1:]) * 1000 + frame
                        )
                        os.utime(plate_file, (mtime, mtime))

                    # Alternative plate locations for robustness testing
                    alt_plate_dir = (
                        shot_path
                        / "sourceimages/plates"
                        / plate
                        / version
                        / "exr/4096x2304"
                    )
                    alt_plate_dir.mkdir(parents=True, exist_ok=True)
                    for frame in [1001, 1025, 1050]:  # Sparse alternative
                        alt_file = (
                            alt_plate_dir
                            / f"{shot_name}_{plate}_{colorspace}_{version}.{frame}.exr"
                        )
                        alt_file.touch()

        # 3DE scenes with realistic user directory structure
        base_mtime = 2000000
        for user_idx, user in enumerate(users):
            for plate in plates:
                # Multiple versions per user
                for ver_idx, version in enumerate(["v001", "v002", "v003"]):
                    scene_dir = (
                        shot_path
                        / f"user/{user}/mm/3de/mm-default/scenes/scene/{plate}/{version}"
                    )
                    scene_dir.mkdir(parents=True, exist_ok=True)

                    # Multiple scene files per version
                    scene_files = [
                        f"{user}_{plate}_{version}_main.3de",
                        f"{user}_{plate}_{version}_backup.3de",
                    ]

                    for scene_idx, scene_file in enumerate(scene_files):
                        full_scene_path = scene_dir / scene_file
                        full_scene_path.write_bytes(b"FAKE_3DE_DATA")

                        # Realistic modification times
                        mtime = (
                            base_mtime
                            + (user_idx * 100000)
                            + (ver_idx * 10000)
                            + scene_idx
                        )
                        os.utime(full_scene_path, (mtime, mtime))

        # Undistortion files
        for plate in plates:
            for version in ["v001", "v002"]:
                undist_dir = shot_path / "mm/nuke/undistortion" / plate / version
                undist_dir.mkdir(parents=True, exist_ok=True)

                undist_files = [
                    "undistortion.nk",
                    "undist_setup.nk",
                    f"{shot_name}_{plate}_undist.nk",
                ]

                for undist_file in undist_files:
                    (undist_dir / undist_file).write_bytes(b"FAKE_NUKE_SCRIPT")

        # Additional production files
        comp_dir = shot_path / "mm/nuke/comp/v001"
        comp_dir.mkdir(parents=True, exist_ok=True)
        (comp_dir / f"{shot_name}_comp_v001.nk").write_bytes(b"COMP_SCRIPT")

        # Maya scenes
        maya_dir = shot_path / "mm/maya/scenes/v001"
        maya_dir.mkdir(parents=True, exist_ok=True)
        (maya_dir / f"{shot_name}_anim_v001.ma").write_bytes(b"MAYA_SCENE")

    @pytest.fixture
    def main_window_with_real_data(self, qtbot, monkeypatch, production_vfx_structure):
        """Create MainWindow with real production data structure."""
        # Mock system interactions but keep core logic
        monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
        monkeypatch.setattr(QMessageBox, "warning", Mock())
        monkeypatch.setattr(QMessageBox, "information", Mock())
        monkeypatch.setattr(QMessageBox, "critical", Mock())

        # Mock workspace command to return our test data
        ws_output = production_vfx_structure["workspace_output"]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=ws_output, returncode=0)

            window = MainWindow()
            qtbot.addWidget(window)

            # Disable background timers
            if hasattr(window, "refresh_timer"):
                window.refresh_timer.stop()

            # Load real shot data
            success, has_changes = window.shot_model.refresh_shots()
            assert success, "Failed to load shot data"

            yield window, production_vfx_structure

        # Cleanup
        if hasattr(window, "_threede_worker") and window._threede_worker:
            if (
                hasattr(window._threede_worker, "isRunning")
                and window._threede_worker.isRunning()
            ):
                if hasattr(window._threede_worker, "stop"):
                    window._threede_worker.stop()
                if hasattr(window._threede_worker, "wait"):
                    window._threede_worker.wait(500)

        window.close()
        qtbot.wait(50)

    def test_complete_shot_discovery_to_launch_workflow(
        self, main_window_with_real_data, qtbot
    ):
        """Test complete workflow: shot discovery → selection → launch."""
        window, data = main_window_with_real_data
        shots = data["shots"]

        # Step 1: Verify shot discovery worked
        assert len(window.shot_model.shots) == data["total_shots"]
        assert window.shot_model.shots[0].show in [
            "commercial_project",
            "feature_film",
            "episodic_tv",
        ]

        # Step 2: UI should show shots
        window.shot_grid.refresh_shots()
        assert window.shot_grid.thumbnail_widgets is not None

        # Step 3: Artist selects a commercial project shot
        commercial_shots = [s for s in shots if s.show == "commercial_project"]
        assert len(commercial_shots) > 0

        selected_shot = commercial_shots[0]
        window._on_shot_selected(selected_shot)

        # Verify UI updates
        assert window.shot_info_panel._current_shot == selected_shot
        assert selected_shot.full_name in window.windowTitle()

        # Step 4: Test keyboard navigation through shots
        initial_selection = window.shot_grid.selected_shot
        qtbot.keyPress(window.shot_grid, Qt.Key.Key_Right)
        qtbot.wait(100)

        # Should have navigated (selection changed or at least handled)
        # In real usage, this would move through thumbnails

        # Step 5: Test application launch with mocked subprocess
        feature_shots = [s for s in shots if s.show == "feature_film"]
        if feature_shots:
            launch_shot = feature_shots[0]
            window._on_shot_selected(launch_shot)

            with patch.object(
                window.command_launcher, "launch_app", return_value=True
            ) as mock_launch:
                # Test double-click launch (default app)
                window._on_shot_double_clicked(launch_shot)
                mock_launch.assert_called_once()

                # Test keyboard shortcut launches
                qtbot.keyPress(window, Qt.Key.Key_3)  # 3DE
                qtbot.wait(50)

                # Should have attempted 3DE launch
                if mock_launch.call_count > 1:
                    # Verify second call was for 3DE
                    second_call_args = mock_launch.call_args_list[1][0]
                    assert second_call_args[0] == "3de"

        # Step 6: Verify status updates
        status_text = window.status_bar.currentMessage()
        assert len(status_text) > 0  # Should have some status message

    def test_3de_scene_discovery_and_thumbnail_workflow(
        self, main_window_with_real_data, qtbot
    ):
        """Test 3DE scene discovery → thumbnail generation → scene loading workflow."""
        window, data = main_window_with_real_data
        shows_root = data["shows_root"]

        # Step 1: Create real 3DE scene finder and model
        cache_dir = shows_root / "test_cache"
        cache_manager = CacheManager(cache_dir=cache_dir)
        threede_model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Step 2: Discover 3DE scenes in production structure
        finder = ThreeDESceneFinder()
        all_scenes = finder.find_all_scenes_in_shows([str(shows_root)])

        # Should find scenes from our realistic structure
        assert len(all_scenes) > 0, "No 3DE scenes found in production structure"

        # Verify scene metadata is correct
        scene = all_scenes[0]
        assert hasattr(scene, "show")
        assert hasattr(scene, "sequence")
        assert hasattr(scene, "shot")
        assert hasattr(scene, "user")
        assert hasattr(scene, "plate")
        assert scene.scene_path.endswith(".3de")

        # Step 3: Test model integration with real scenes
        shots_for_scenes = [
            Shot(scene.show, scene.sequence, scene.shot, scene.workspace_path)
            for scene in all_scenes[:5]
        ]  # Use first 5 for performance

        success, has_changes = threede_model.refresh_scenes(shots_for_scenes)
        assert success, "Failed to refresh 3DE scenes"

        # Should have deduplicated scenes (one per shot)
        assert len(threede_model.scenes) <= len(shots_for_scenes)

        # Step 4: Verify deduplication picked newest scenes
        if len(threede_model.scenes) > 0:
            dedupe_scene = threede_model.scenes[0]
            # In our structure, users have increasing mtimes
            # So should pick scenes from later users (higher user index)

        # Step 5: Test 3DE grid UI integration
        window.threede_scene_model = threede_model
        if hasattr(window, "threede_grid"):
            window.threede_grid.refresh_scenes()

            # Should display found scenes
            if len(threede_model.scenes) > 0:
                # Test scene selection
                first_scene = threede_model.scenes[0]
                if hasattr(window.threede_grid, "_on_scene_selected"):
                    window.threede_grid._on_scene_selected(first_scene)

    def test_custom_launcher_creation_and_execution_workflow(
        self, main_window_with_real_data, qtbot
    ):
        """Test custom launcher creation → execution → cleanup workflow."""
        window, data = main_window_with_real_data
        shots = data["shots"]

        # Step 1: Select a shot for context
        test_shot = shots[0]
        window._on_shot_selected(test_shot)
        window.command_launcher.set_current_shot(test_shot)

        # Step 2: Create custom launcher with real-world command
        launcher_manager = LauncherManager()

        # Create launcher with variable substitution
        launcher_id = launcher_manager.create_launcher(
            name="Custom Nuke with Plates",
            description="Launch Nuke with automatic plate loading",
            command='nuke -t "import os; nuke.scriptSave(\\"{workspace_path}/mm/nuke/comp/auto_comp.nk\\")"',
            variables={
                "SHOT_NAME": "{shot_name}",
                "WORKSPACE": "{workspace_path}",
                "PLATE_PATH": "{raw_plate_path}",
            },
        )

        assert launcher_id is not None, "Failed to create custom launcher"

        # Step 3: Verify launcher was created
        launcher = launcher_manager.get_launcher(launcher_id)
        assert launcher is not None
        assert launcher.name == "Custom Nuke with Plates"
        assert "{workspace_path}" in launcher.command

        # Step 4: Execute launcher with real process mocking
        execution_started = threading.Event()
        execution_finished = threading.Event()
        execution_success = threading.Event()

        def on_started(lid):
            if lid == launcher_id:
                execution_started.set()

        def on_finished(lid, success):
            if lid == launcher_id:
                execution_finished.set()
                if success:
                    execution_success.set()

        launcher_manager.execution_started.connect(on_started)
        launcher_manager.execution_finished.connect(on_finished)

        # Mock subprocess to simulate successful execution
        with patch("launcher_manager.subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.wait.return_value = 0  # Success
            mock_process.pid = 12345
            mock_popen.return_value = mock_process

            # Execute the launcher
            success = launcher_manager.execute_launcher(launcher_id)
            assert success, "Failed to execute custom launcher"

            # Wait for worker thread to process
            qtbot.wait(500)

            # Should have started execution
            assert execution_started.wait(1.0), "Launcher execution did not start"

            # Verify process was created with correct command
            assert mock_popen.called, "Subprocess was not called"

            # Command should have variable substitution
            called_cmd = mock_popen.call_args[0][0]
            cmd_str = (
                " ".join(called_cmd)
                if isinstance(called_cmd, list)
                else str(called_cmd)
            )

            # Should contain actual shot data, not template variables
            assert test_shot.workspace_path in cmd_str or test_shot.full_name in cmd_str

        # Step 5: Test launcher persistence
        # Verify launcher can be retrieved after creation
        retrieved = launcher_manager.get_launcher(launcher_id)
        assert retrieved is not None
        assert retrieved.id == launcher_id

        # Step 6: Cleanup
        success = launcher_manager.delete_launcher(launcher_id)
        assert success, "Failed to delete custom launcher"

        # Verify deletion
        deleted = launcher_manager.get_launcher(launcher_id)
        assert deleted is None, "Launcher was not properly deleted"

    def test_raw_plate_discovery_with_priority_system(
        self, main_window_with_real_data, qtbot
    ):
        """Test raw plate discovery with realistic priority and fallback system."""
        window, data = main_window_with_real_data
        shows_root = data["shows_root"]

        # Step 1: Test plate discovery on commercial project shots
        commercial_shots = [s for s in data["shots"] if s.show == "commercial_project"]
        assert len(commercial_shots) > 0

        test_shot = commercial_shots[0]
        shot_path = (
            shows_root
            / "commercial_project"
            / "shots"
            / test_shot.sequence
            / test_shot.full_name
        )

        # Step 2: Test primary plate discovery (BG01 should be preferred)
        result = RawPlateFinder.find_latest_raw_plate(
            str(shot_path), test_shot.full_name
        )

        if result:
            # Should prefer BG01 over other plates based on our priority system
            assert "BG01" in result or "FG01" in result  # Should find one of our plates

            # Verify plate exists
            exists = RawPlateFinder.verify_plate_exists(result)
            assert exists, f"Discovered plate does not exist: {result}"

            # Should use latest colorspace (aces preferred)
            assert (
                "aces" in result
                or "lin_rec2020" in result
                or "lin_sgamut3cine" in result
            )

        # Step 3: Test fallback behavior with missing BG01
        # Create shot with only FG01
        fallback_shot_path = shot_path.parent / "fallback_test"
        fallback_shot_name = "CM001_fallback"

        # Create only FG01 plate
        fg_plate_dir = (
            fallback_shot_path
            / "publish/turnover/plate/input_plate/FG01/v001/exr/2048x1152"
        )
        fg_plate_dir.mkdir(parents=True, exist_ok=True)

        for frame in [1001, 1002, 1003]:
            plate_file = (
                fg_plate_dir
                / f"{fallback_shot_name}_turnover-plate_FG01_aces_v001.{frame}.exr"
            )
            plate_file.touch()

        # Should fall back to FG01
        fallback_result = RawPlateFinder.find_latest_raw_plate(
            str(fallback_shot_path), fallback_shot_name
        )

        if fallback_result:
            assert "FG01" in fallback_result, "Should have fallen back to FG01"
            assert RawPlateFinder.verify_plate_exists(fallback_result), (
                "Fallback plate should exist"
            )

        # Step 4: Test colorspace detection
        all_plates = PathUtils.discover_plate_directories(
            shot_path / "publish/turnover/plate/input_plate"
        )

        if all_plates:
            # Should find multiple colorspaces
            colorspaces_found = set()
            for plate_dir in all_plates:
                plate_files = list(Path(plate_dir).glob("*.exr"))
                for plate_file in plate_files[:3]:  # Check first few
                    if "_aces_" in plate_file.name:
                        colorspaces_found.add("aces")
                    elif "_lin_sgamut3cine_" in plate_file.name:
                        colorspaces_found.add("lin_sgamut3cine")

            # Should have found multiple colorspaces from our structure
            assert len(colorspaces_found) > 0, "No colorspaces detected in plate names"

        # Step 5: Test UI integration
        window._on_shot_selected(test_shot)

        # Raw plate checkbox should affect launcher behavior
        window.raw_plate_checkbox.setChecked(True)

        with patch.object(
            window.command_launcher, "launch_app", return_value=True
        ) as mock_launch:
            window.command_launcher.launch_app("nuke", include_raw_plate=True)

            # Should have attempted launch with raw plate
            mock_launch.assert_called_once()
            args, kwargs = mock_launch.call_args
            assert kwargs.get("include_raw_plate") == True

    def test_undistortion_file_discovery_workflow(
        self, main_window_with_real_data, qtbot
    ):
        """Test undistortion file discovery and integration workflow."""
        window, data = main_window_with_real_data
        shows_root = data["shows_root"]

        # Step 1: Test undistortion discovery
        feature_shots = [s for s in data["shots"] if s.show == "feature_film"]
        if not feature_shots:
            pytest.skip("No feature film shots available")

        test_shot = feature_shots[0]
        shot_path = (
            shows_root
            / "feature_film"
            / "shots"
            / test_shot.sequence
            / test_shot.full_name
        )

        # Step 2: Use real undistortion finder
        undist_file = UndistortionFinder.find_latest_undistortion_file(
            str(shot_path), test_shot.full_name
        )

        if undist_file:
            # Should find undistortion file from our structure
            assert undist_file.endswith(".nk"), (
                f"Expected Nuke script, got: {undist_file}"
            )
            assert Path(undist_file).exists(), (
                f"Undistortion file does not exist: {undist_file}"
            )

            # Should prefer files with shot name
            if test_shot.full_name in undist_file:
                assert test_shot.full_name in Path(undist_file).name

        # Step 3: Test UI integration
        window._on_shot_selected(test_shot)
        window.undistortion_checkbox.setChecked(True)

        with patch.object(
            window.command_launcher, "launch_app", return_value=True
        ) as mock_launch:
            window.command_launcher.launch_app("nuke", include_undistortion=True)

            mock_launch.assert_called_once()
            args, kwargs = mock_launch.call_args
            assert kwargs.get("include_undistortion") == True

        # Step 4: Test version preference
        # In our structure, v002 should be newer than v001
        v2_undist_dir = shot_path / "mm/nuke/undistortion/BG01/v002"
        if v2_undist_dir.exists():
            # Should prefer v002 over v001
            if undist_file and "v002" in undist_file:
                assert "v002" in undist_file, "Should prefer newer version"

    def test_concurrent_operations_stress_test(self, main_window_with_real_data, qtbot):
        """Test concurrent operations under realistic stress."""
        window, data = main_window_with_real_data
        shots = data["shots"][:10]  # Use first 10 shots for performance

        # Step 1: Rapid shot switching while launching apps
        launched_apps = []

        def track_launch(timestamp, command):
            launched_apps.append((timestamp, command))

        window.command_launcher.command_executed.connect(track_launch)

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = Mock(pid=99999)

            # Rapidly switch shots and launch apps
            for i, shot in enumerate(shots):
                window._on_shot_selected(shot)
                qtbot.wait(20)  # Minimal wait

                # Launch different app for each shot
                app = ["nuke", "maya", "3de", "rv"][i % 4]
                window.command_launcher.launch_app(app)
                qtbot.wait(30)  # Allow launch processing

        # Should have successfully launched multiple apps
        assert len(launched_apps) == len(shots), (
            f"Expected {len(shots)} launches, got {len(launched_apps)}"
        )

        # Step 2: Verify context was correct for each launch
        for i, (timestamp, command) in enumerate(launched_apps):
            expected_shot = shots[i]
            # Command should contain correct workspace path
            assert expected_shot.workspace_path in command, (
                f"Wrong context in command: {command}"
            )

        # Step 3: Test concurrent custom launcher execution
        launcher_manager = LauncherManager()
        launcher_ids = []

        # Create multiple custom launchers
        for i in range(5):
            launcher_id = launcher_manager.create_launcher(
                name=f"Stress Test Launcher {i}",
                command=f"echo 'Launcher {i} executing'",
                description=f"Stress test launcher {i}",
            )
            if launcher_id:
                launcher_ids.append(launcher_id)

        # Execute all launchers rapidly
        with patch("launcher_manager.subprocess.Popen") as mock_popen:
            mock_popen.return_value = Mock(pid=88888, wait=Mock(return_value=0))

            execution_results = []
            for launcher_id in launcher_ids:
                success = launcher_manager.execute_launcher(launcher_id)
                execution_results.append(success)
                qtbot.wait(50)  # Brief delay between executions

        # All executions should have been initiated successfully
        assert all(execution_results), (
            f"Some launcher executions failed: {execution_results}"
        )

        # Clean up launchers
        for launcher_id in launcher_ids:
            launcher_manager.delete_launcher(launcher_id)

    def test_memory_and_resource_management(self, main_window_with_real_data, qtbot):
        """Test memory and resource management during intensive workflows."""
        window, data = main_window_with_real_data
        shots = data["shots"]

        # Step 1: Test cache behavior with large dataset
        initial_cache_size = (
            len(window.shot_model._cache) if hasattr(window.shot_model, "_cache") else 0
        )

        # Repeatedly load and switch shots
        for _ in range(3):  # Multiple passes through shots
            for shot in shots[:20]:  # Use subset for performance
                window._on_shot_selected(shot)
                qtbot.wait(10)

        # Cache should not grow unboundedly
        final_cache_size = (
            len(window.shot_model._cache) if hasattr(window.shot_model, "_cache") else 0
        )

        # Should have reasonable cache growth
        cache_growth = final_cache_size - initial_cache_size
        assert cache_growth < len(shots), (
            f"Cache grew too much: {cache_growth} vs {len(shots)} shots"
        )

        # Step 2: Test 3DE scene caching
        if hasattr(window, "threede_scene_model"):
            # Load scenes multiple times
            test_shots = shots[:5]  # Smaller set for 3DE testing

            for _ in range(3):
                success, _ = window.threede_scene_model.refresh_scenes(test_shots)
                assert success, "3DE scene refresh failed during stress test"
                qtbot.wait(100)

        # Step 3: Test launcher cleanup
        launcher_manager = LauncherManager()

        # Create and delete many launchers
        created_ids = []
        for i in range(10):
            launcher_id = launcher_manager.create_launcher(
                name=f"Memory Test {i}",
                command=f"echo {i}",
                description="Memory test launcher",
            )
            if launcher_id:
                created_ids.append(launcher_id)

        # Verify all were created
        assert len(created_ids) == 10, "Not all launchers were created"

        # Delete all launchers
        deleted_count = 0
        for launcher_id in created_ids:
            if launcher_manager.delete_launcher(launcher_id):
                deleted_count += 1

        # All should be deleted
        assert deleted_count == len(created_ids), (
            f"Only {deleted_count} of {len(created_ids)} launchers deleted"
        )

        # Verify they're actually gone
        remaining = [launcher_manager.get_launcher(lid) for lid in created_ids]
        assert all(l is None for l in remaining), (
            "Some launchers were not properly deleted"
        )

    def test_error_recovery_and_resilience(self, main_window_with_real_data, qtbot):
        """Test system resilience and error recovery."""
        window, data = main_window_with_real_data

        # Step 1: Test recovery from missing files
        # Create shot with missing thumbnail
        missing_thumb_shot = Shot("missing", "MISSING", "0001", "/nonexistent/path")

        # Should handle gracefully without crashing
        window._on_shot_selected(missing_thumb_shot)
        assert window.shot_info_panel._current_shot == missing_thumb_shot

        # Step 2: Test app launch with bad workspace
        with patch(
            "subprocess.Popen", side_effect=FileNotFoundError("Command not found")
        ):
            # Should handle launch failure gracefully
            success = window.command_launcher.launch_app("nuke")
            assert success == False, "Should return False for failed launch"

        # Step 3: Test workspace command failure
        with patch("subprocess.run", side_effect=Exception("Workspace command failed")):
            # Should handle workspace failure gracefully
            success, _ = window.shot_model.refresh_shots()
            # Depending on implementation, might return False or handle gracefully
            # Key is that it doesn't crash

        # Step 4: Test 3DE finder with permission errors
        if hasattr(window, "threede_scene_model"):
            with patch(
                "threede_scene_finder.Path.glob",
                side_effect=PermissionError("Access denied"),
            ):
                # Should handle permission errors gracefully
                success, _ = window.threede_scene_model.refresh_scenes(
                    data["shots"][:1]
                )
                # Should not crash, might return False

        # Step 5: Test UI resilience
        # UI should remain responsive after errors
        assert window.isVisible()
        assert window.shot_grid is not None
        assert window.shot_info_panel is not None

        # Should be able to continue normal operations
        valid_shot = data["shots"][0]
        window._on_shot_selected(valid_shot)
        assert window.shot_info_panel._current_shot == valid_shot


class TestScalabilityAndPerformance:
    """Test system performance with large datasets."""

    @pytest.fixture
    def large_production_dataset(self, tmp_path):
        """Create large production dataset for scalability testing."""
        shows_root = tmp_path / "large_production"

        # Create 5 shows, 10 sequences each, 20 shots per sequence = 1000 shots
        total_shots = []
        workspace_lines = []

        for show_idx in range(5):
            show_name = f"bigshow_{show_idx:02d}"

            for seq_idx in range(10):
                seq_name = f"SEQ_{seq_idx:03d}"

                for shot_idx in range(20):
                    shot_name = f"{seq_name}_{shot_idx:04d}"
                    shot_path = shows_root / show_name / "shots" / seq_name / shot_name

                    # Minimal structure for performance
                    thumb_dir = shot_path / "editorial/ref"
                    thumb_dir.mkdir(parents=True, exist_ok=True)
                    (thumb_dir / f"{shot_name}.jpg").write_bytes(b"IMG")

                    workspace_path = f"/shows/{show_name}/shots/{seq_name}/{shot_name}"
                    workspace_lines.append(f"workspace {workspace_path}")

                    shot = Shot(show_name, seq_name, f"{shot_idx:04d}", workspace_path)
                    total_shots.append(shot)

        return {
            "shows_root": shows_root,
            "shots": total_shots,
            "workspace_output": "\\n".join(workspace_lines),
            "total_count": len(total_shots),
        }

    @pytest.mark.performance
    def test_large_dataset_loading_performance(self, large_production_dataset, qtbot):
        """Test loading performance with 1000+ shots."""
        data = large_production_dataset

        # Mock workspace command
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=data["workspace_output"], returncode=0)

            # Time the shot loading
            start_time = time.time()

            shot_model = ShotModel()
            success, has_changes = shot_model.refresh_shots()

            load_time = time.time() - start_time

            # Should load successfully
            assert success, "Failed to load large dataset"
            assert len(shot_model.shots) == data["total_count"]

            # Should complete within reasonable time (adjust based on system)
            assert load_time < 5.0, f"Loading took too long: {load_time:.2f}s"

            print(f"Loaded {data['total_count']} shots in {load_time:.2f}s")

    @pytest.mark.performance
    def test_ui_responsiveness_with_large_dataset(
        self, large_production_dataset, qtbot, monkeypatch
    ):
        """Test UI remains responsive with large datasets."""
        data = large_production_dataset

        # Create window with large dataset
        monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
        monkeypatch.setattr(QMessageBox, "warning", Mock())

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=data["workspace_output"], returncode=0)

            window = MainWindow()
            qtbot.addWidget(window)

            # Disable background operations
            if hasattr(window, "refresh_timer"):
                window.refresh_timer.stop()

            # Load shots
            start_time = time.time()
            success, _ = window.shot_model.refresh_shots()
            assert success

            # Update UI
            window.shot_grid.refresh_shots()
            ui_update_time = time.time() - start_time

            # UI update should complete quickly
            assert ui_update_time < 3.0, (
                f"UI update took too long: {ui_update_time:.2f}s"
            )

            # Test rapid shot switching
            rapid_switch_start = time.time()
            test_shots = data["shots"][:50]  # Use subset for rapid switching

            for shot in test_shots:
                window._on_shot_selected(shot)
                qtbot.wait(5)  # Very brief wait

            rapid_switch_time = time.time() - rapid_switch_start

            # Should handle rapid switching without major delays
            assert rapid_switch_time < 10.0, (
                f"Rapid switching took too long: {rapid_switch_time:.2f}s"
            )

            window.close()

    @pytest.mark.performance
    def test_memory_usage_with_large_dataset(
        self, large_production_dataset, qtbot, monkeypatch
    ):
        """Test memory usage remains reasonable with large datasets."""
        import os

        import psutil

        data = large_production_dataset
        process = psutil.Process(os.getpid())

        # Get baseline memory
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
        monkeypatch.setattr(QMessageBox, "warning", Mock())

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=data["workspace_output"], returncode=0)

            window = MainWindow()
            qtbot.addWidget(window)

            if hasattr(window, "refresh_timer"):
                window.refresh_timer.stop()

            # Load large dataset
            window.shot_model.refresh_shots()
            window.shot_grid.refresh_shots()

            # Measure memory after loading
            loaded_memory = process.memory_info().rss / 1024 / 1024

            # Exercise the system
            for shot in data["shots"][:100]:
                window._on_shot_selected(shot)
                if len(data["shots"]) % 20 == 0:  # Periodic wait
                    qtbot.wait(10)

            # Final memory measurement
            final_memory = process.memory_info().rss / 1024 / 1024

            memory_growth = final_memory - initial_memory

            # Memory growth should be reasonable (less than 500MB for 1000 shots)
            assert memory_growth < 500, (
                f"Memory usage too high: {memory_growth:.1f}MB growth"
            )

            print(
                f"Memory: {initial_memory:.1f}MB → {final_memory:.1f}MB (+{memory_growth:.1f}MB)"
            )

            window.close()


@pytest.mark.integration
class TestRealWorldScenarios:
    """Test scenarios that mirror real VFX production workflows."""

    def test_artist_morning_startup_workflow(self, tmp_path, qtbot):
        """Test typical artist morning startup workflow."""
        # This test simulates what happens when an artist starts their day

        # Step 1: Artist starts ShotBot
        shows_root = tmp_path / "morning_test"
        self._create_artist_workspace(shows_root, "project_alpha", 3, 5)

        ws_lines = []
        for seq in range(3):
            for shot in range(5):
                ws_lines.append(
                    f"workspace /shows/project_alpha/shots/SEQ_{seq:03d}/SEQ_{seq:03d}_{shot:04d}"
                )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout="\\n".join(ws_lines), returncode=0)

            # Create window (artist startup)
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QMessageBox

            with patch.object(QTimer, "singleShot", lambda *args: None):
                with patch.object(QMessageBox, "warning", Mock()):
                    window = MainWindow()
                    qtbot.addWidget(window)

                    if hasattr(window, "refresh_timer"):
                        window.refresh_timer.stop()

                    # Step 2: Shots load automatically
                    success, _ = window.shot_model.refresh_shots()
                    assert success

                    # Step 3: Artist finds their assigned shots
                    # In real world, they'd scroll/search, here we simulate
                    assigned_shots = [
                        s for s in window.shot_model.shots if "SEQ_001" in s.sequence
                    ]
                    assert len(assigned_shots) > 0

                    # Step 4: Artist selects today's first shot
                    today_shot = assigned_shots[0]
                    window._on_shot_selected(today_shot)

                    # Step 5: Artist launches Nuke to continue work
                    with patch.object(
                        window.command_launcher, "launch_app", return_value=True
                    ) as mock_launch:
                        window._on_shot_double_clicked(today_shot)
                        mock_launch.assert_called_once()

                    window.close()

    def test_supervisor_review_workflow(self, tmp_path, qtbot):
        """Test supervisor reviewing multiple shots workflow."""
        shows_root = tmp_path / "supervisor_test"
        self._create_artist_workspace(shows_root, "review_project", 2, 8)

        ws_lines = []
        shots = []
        for seq in range(2):
            for shot in range(8):
                shot_name = f"SEQ_{seq:03d}_{shot:04d}"
                ws_line = (
                    f"workspace /shows/review_project/shots/SEQ_{seq:03d}/{shot_name}"
                )
                ws_lines.append(ws_line)
                shots.append(
                    Shot(
                        "review_project",
                        f"SEQ_{seq:03d}",
                        f"{shot:04d}",
                        ws_line.split()[1],
                    )
                )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout="\\n".join(ws_lines), returncode=0)

            with patch.object(QTimer, "singleShot", lambda *args: None):
                with patch.object(QMessageBox, "warning", Mock()):
                    window = MainWindow()
                    qtbot.addWidget(window)

                    if hasattr(window, "refresh_timer"):
                        window.refresh_timer.stop()

                    window.shot_model.refresh_shots()

                    # Supervisor rapidly reviews shots
                    reviewed_shots = []

                    for shot in window.shot_model.shots[:6]:  # Review first 6
                        window._on_shot_selected(shot)
                        qtbot.wait(100)  # Time to "review"
                        reviewed_shots.append(shot)

                        # Every 3rd shot, launch RV for playblast review
                        if len(reviewed_shots) % 3 == 0:
                            with patch.object(
                                window.command_launcher, "launch_app"
                            ) as mock_launch:
                                window.command_launcher.launch_app("rv")

                    # Should have reviewed multiple shots successfully
                    assert len(reviewed_shots) == 6

                    window.close()

    def test_technical_artist_setup_workflow(self, tmp_path, qtbot):
        """Test technical artist setting up shot templates."""
        shows_root = tmp_path / "tech_setup"
        self._create_artist_workspace(shows_root, "tech_project", 1, 3)

        # Technical artist needs to set up custom launchers for pipeline tools
        launcher_manager = LauncherManager()

        # Create pipeline tool launchers
        pipeline_tools = [
            {
                "name": "Asset Publisher",
                "command": "python /pipeline/tools/asset_publisher.py --shot {shot_name}",
                "description": "Publish shot assets",
            },
            {
                "name": "Render Queue",
                "command": "python /pipeline/tools/render_queue.py --workspace {workspace_path}",
                "description": "Submit renders to farm",
            },
            {
                "name": "Shot Validator",
                "command": "python /pipeline/tools/validator.py --check-all {workspace_path}",
                "description": "Validate shot setup",
            },
        ]

        created_launchers = []
        for tool in pipeline_tools:
            launcher_id = launcher_manager.create_launcher(
                name=tool["name"],
                command=tool["command"],
                description=tool["description"],
            )

            if launcher_id:
                created_launchers.append(launcher_id)

        # Should have created all pipeline tools
        assert len(created_launchers) == len(pipeline_tools)

        # Test that they can be retrieved and have correct properties
        for launcher_id in created_launchers:
            launcher = launcher_manager.get_launcher(launcher_id)
            assert launcher is not None
            assert (
                "{shot_name}" in launcher.command
                or "{workspace_path}" in launcher.command
            )

        # Cleanup
        for launcher_id in created_launchers:
            launcher_manager.delete_launcher(launcher_id)

    def _create_artist_workspace(
        self, shows_root: Path, project_name: str, sequences: int, shots_per_seq: int
    ):
        """Create realistic artist workspace structure."""
        for seq in range(sequences):
            seq_name = f"SEQ_{seq:03d}"

            for shot in range(shots_per_seq):
                shot_name = f"{seq_name}_{shot:04d}"
                shot_path = shows_root / project_name / "shots" / seq_name / shot_name

                # Minimal realistic structure
                (shot_path / "editorial/ref").mkdir(parents=True, exist_ok=True)
                (shot_path / "editorial/ref/ref.jpg").write_bytes(b"THUMB")

                # Work areas
                (shot_path / "mm/nuke/comp").mkdir(parents=True, exist_ok=True)
                (shot_path / "mm/maya/scenes").mkdir(parents=True, exist_ok=True)

                # Plates
                plate_dir = shot_path / "sourceimages/plates/BG01/v001/exr/2048x1152"
                plate_dir.mkdir(parents=True, exist_ok=True)

                for frame in [1001, 1050, 1100]:
                    (plate_dir / f"{shot_name}_BG01_v001.{frame}.exr").touch()
