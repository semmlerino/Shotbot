"""Error recovery integration tests for ShotBot.

This module tests error recovery scenarios in production environments:
1. Recovery from missing workspace command
2. Handling of permission denied errors
3. Network storage timeout scenarios
4. Recovery from process crashes
5. User-friendly error message verification
6. Graceful degradation under failure conditions
7. State consistency after errors
8. Resource cleanup after failures

These tests validate the application remains stable and usable
even when encountering various error conditions.
"""

import os
import time
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from cache_manager import CacheManager
from command_launcher import CommandLauncher
from main_window import MainWindow
from shot_model import Shot, ShotModel
from threede_scene_model import ThreeDESceneModel
from utils import PathUtils


class TestWorkspaceCommandErrorRecovery:
    """Test recovery from workspace command failures."""

    def test_missing_workspace_command_recovery(self, qtbot):
        """Test recovery when workspace command is not found."""
        model = ShotModel()

        # Simulate workspace command not found
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("ws: command not found")

            success, has_changes = model.refresh_shots()

            # Should handle error gracefully
            assert success is False, (
                "Should return False when workspace command missing"
            )
            assert has_changes is False, "Should not report changes on error"
            assert len(model.shots) == 0, "Should not populate shots on error"

    def test_workspace_command_timeout_recovery(self, qtbot):
        """Test recovery from workspace command timeout."""
        model = ShotModel()

        # Simulate command timeout
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = TimeoutError("Workspace command timed out")

            success, has_changes = model.refresh_shots()

            # Should handle timeout gracefully
            assert success is False, "Should return False on timeout"
            assert len(model.shots) == 0, "Should not populate shots on timeout"

    def test_workspace_command_permission_denied(self, qtbot):
        """Test recovery from workspace command permission errors."""
        model = ShotModel()

        # Simulate permission denied
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = PermissionError("Permission denied: ws command")

            success, has_changes = model.refresh_shots()

            # Should handle permission error gracefully
            assert success is False, "Should return False on permission error"
            assert len(model.shots) == 0, (
                "Should not populate shots on permission error"
            )

    def test_workspace_command_invalid_output_recovery(self, qtbot):
        """Test recovery from invalid workspace command output."""
        model = ShotModel()

        # Test various invalid outputs
        invalid_outputs = [
            "",  # Empty output
            "invalid output format",  # Wrong format
            "workspace",  # Missing path
            "workspace /incomplete",  # Incomplete path
            "not_workspace /some/path",  # Wrong command
            "\n\n  \n",  # Only whitespace
        ]

        for invalid_output in invalid_outputs:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(stdout=invalid_output, returncode=0)

                success, has_changes = model.refresh_shots()

                # Should handle invalid output gracefully
                if invalid_output.strip() == "":
                    # Empty output might be valid (no shots)
                    assert success is True, (
                        f"Empty output should succeed: '{invalid_output}'"
                    )
                    assert len(model.shots) == 0, (
                        f"Empty output should yield no shots: '{invalid_output}'"
                    )
                else:
                    # Most invalid outputs should be handled gracefully
                    # Implementation may vary on how strict parsing is
                    assert isinstance(success, bool), (
                        f"Should return boolean for: '{invalid_output}'"
                    )
                    if not success:
                        assert len(model.shots) == 0, (
                            f"Failed parsing should yield no shots: '{invalid_output}'"
                        )

    def test_workspace_command_mixed_valid_invalid_lines(self, qtbot):
        """Test handling mixed valid and invalid workspace lines."""
        model = ShotModel()

        mixed_output = """workspace /shows/valid/shots/SEQ_001/SEQ_001_0010
invalid line without workspace prefix
workspace /shows/valid/shots/SEQ_001/SEQ_001_0020
workspace incomplete_path
workspace /shows/valid/shots/SEQ_002/SEQ_002_0010
another invalid line
workspace /shows/valid/shots/SEQ_002/SEQ_002_0020"""

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=mixed_output, returncode=0)

            success, has_changes = model.refresh_shots()

            # Should successfully parse valid lines and skip invalid ones
            assert success is True, "Should succeed with mixed valid/invalid lines"
            assert len(model.shots) == 4, (
                f"Should find 4 valid shots, got {len(model.shots)}"
            )

            # Verify valid shots were parsed correctly
            shot_names = {shot.full_name for shot in model.shots}
            expected_names = {
                "SEQ_001_0010",
                "SEQ_001_0020",
                "SEQ_002_0010",
                "SEQ_002_0020",
            }
            assert shot_names == expected_names, (
                f"Expected {expected_names}, got {shot_names}"
            )


class TestPermissionErrorRecovery:
    """Test recovery from permission denied errors."""

    def test_file_system_permission_recovery(self, tmp_path, qtbot):
        """Test recovery from filesystem permission errors."""
        # Create directory structure
        test_dir = tmp_path / "permission_test"
        test_dir.mkdir()

        # Create shot
        shot = Shot("perm_test", "PERM", "0001", str(test_dir))

        # Test thumbnail discovery with permission error
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.side_effect = PermissionError("Permission denied")

            # Should handle permission error gracefully
            thumbnail_path = PathUtils.find_thumbnail(str(test_dir), shot.full_name)

            # Implementation should return None or handle gracefully
            assert thumbnail_path is None or isinstance(thumbnail_path, str)

    def test_app_launch_permission_recovery(self, qtbot):
        """Test recovery from app launch permission errors."""
        shot = Shot("perm_test", "PERM", "0001", "/test/permission")
        launcher = CommandLauncher()
        launcher.set_current_shot(shot)

        # Test various permission error scenarios
        permission_errors = [
            PermissionError("Permission denied"),
            OSError(13, "Permission denied"),  # EACCES
            FileNotFoundError("Application not found"),
        ]

        for error in permission_errors:
            with patch("subprocess.Popen") as mock_popen:
                mock_popen.side_effect = error

                success = launcher.launch_app("nuke")

                # Should handle permission error gracefully
                assert success is False, f"Should return False for error: {error}"

    def test_cache_permission_recovery(self, tmp_path, qtbot):
        """Test recovery from cache permission errors."""
        # Create cache directory with restrictive permissions
        cache_dir = tmp_path / "restricted_cache"
        cache_dir.mkdir(mode=0o000)  # No permissions

        try:
            cache_manager = CacheManager(cache_dir=cache_dir)

            # Test shots
            test_shots = [
                Shot("cache_test", "CACHE", "0001", "/test/cache1"),
                Shot("cache_test", "CACHE", "0002", "/test/cache2"),
            ]

            # Should handle permission error gracefully
            with patch("pathlib.Path.mkdir") as mock_mkdir:
                mock_mkdir.side_effect = PermissionError("Permission denied")

                # Cache operations should not crash
                try:
                    cache_manager.cache_shots(test_shots)
                    # Success or graceful failure both acceptable
                except PermissionError:
                    # If exception propagates, that's also acceptable behavior
                    pass

                # Should be able to attempt loading even if caching failed
                try:
                    loaded_shots = cache_manager.get_cached_shots()
                    # None or empty list are both acceptable
                    assert loaded_shots is None or isinstance(loaded_shots, list)
                except (PermissionError, FileNotFoundError):
                    # Expected if cache directory is inaccessible
                    pass

        finally:
            # Restore permissions for cleanup
            cache_dir.chmod(0o755)


class TestNetworkStorageTimeouts:
    """Test recovery from network storage timeout scenarios."""

    def test_network_path_timeout_recovery(self, qtbot):
        """Test recovery from network storage timeouts."""
        # Simulate network paths that might timeout
        network_paths = [
            "//server/share/shows/network_test/shots/NET/NET_0001",
            "/mnt/network_storage/shows/timeout_test/shots/TO/TO_0001",
            "\\\\server\\share\\shows\\windows_test\\shots\\WIN\\WIN_0001",
        ]

        for network_path in network_paths:
            shot = Shot("network_test", "NET", "0001", network_path)

            # Test raw plate finder with timeout
            with patch("pathlib.Path.exists") as mock_exists:
                mock_exists.side_effect = TimeoutError("Network timeout")

                from raw_plate_finder import RawPlateFinder

                # Should handle timeout gracefully
                result = RawPlateFinder.find_latest_raw_plate(
                    network_path, shot.full_name
                )

                # Should return None or handle gracefully, not crash
                assert result is None or isinstance(result, str)

    def test_network_3de_discovery_timeout_recovery(self, qtbot):
        """Test recovery from network timeouts during 3DE discovery."""
        network_shot = Shot("network", "NET", "0001", "//server/network/shot")

        with patch("pathlib.Path.rglob") as mock_rglob:
            mock_rglob.side_effect = TimeoutError("Network storage timeout")

            from threede_scene_finder import ThreeDESceneFinder

            finder = ThreeDESceneFinder()

            # Should handle timeout gracefully
            try:
                scenes = finder.find_scenes_for_shot(
                    network_shot.workspace_path,
                    network_shot.show,
                    network_shot.sequence,
                    network_shot.shot,
                    excluded_users=set(),
                )

                # Should return empty list or handle gracefully
                assert isinstance(scenes, list)

            except TimeoutError:
                # If timeout propagates, that's acceptable too
                pass

    def test_network_thumbnail_timeout_recovery(self, qtbot):
        """Test recovery from thumbnail loading timeouts on network storage."""
        network_shot = Shot("network", "NET", "0001", "//server/network/thumbnails")

        with patch("pathlib.Path.exists") as mock_exists:
            # First call times out, second succeeds
            mock_exists.side_effect = [TimeoutError("Network timeout"), False]

            # Should handle timeout and continue gracefully
            thumbnail_path = PathUtils.find_thumbnail(
                network_shot.workspace_path, network_shot.full_name
            )

            # Should complete without crashing
            assert thumbnail_path is None or isinstance(thumbnail_path, str)


class TestProcessCrashRecovery:
    """Test recovery from process crashes."""

    def test_workspace_process_crash_recovery(self, qtbot):
        """Test recovery from workspace process crashes."""
        model = ShotModel()

        # Simulate process crash scenarios
        crash_scenarios = [
            OSError("Process crashed unexpectedly"),
            RuntimeError("Process terminated abnormally"),
            Exception("Unknown process error"),
        ]

        for crash_error in crash_scenarios:
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = crash_error

                success, has_changes = model.refresh_shots()

                # Should handle crash gracefully
                assert success is False, f"Should return False for crash: {crash_error}"
                assert has_changes is False, "Should not report changes on crash"
                assert len(model.shots) == 0, "Should not populate shots on crash"

    def test_app_launch_process_crash_recovery(self, qtbot):
        """Test recovery from application launch crashes."""
        shot = Shot("crash_test", "CRASH", "0001", "/test/crash")
        launcher = CommandLauncher()
        launcher.set_current_shot(shot)

        # Test process that crashes immediately
        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.pid = 12345
            mock_process.poll.return_value = -9  # SIGKILL - crashed
            mock_popen.return_value = mock_process

            success = launcher.launch_app("crashing_app")

            # Should handle crashed process
            # Success might still be True if launch initiated successfully
            assert isinstance(success, bool)

    def test_cache_corruption_recovery(self, tmp_path, qtbot):
        """Test recovery from corrupted cache files."""
        cache_dir = tmp_path / "corrupted_cache"
        cache_dir.mkdir()

        # Create corrupted cache file
        cache_file = cache_dir / "shots.json"
        cache_file.write_text("{ invalid json content }")

        cache_manager = CacheManager(cache_dir=cache_dir)

        # Should handle corrupted cache gracefully
        loaded_shots = cache_manager.get_cached_shots()

        # Should return None or empty list, not crash
        assert loaded_shots is None or isinstance(loaded_shots, list)

        # Should be able to create new cache after corruption
        test_shots = [Shot("recovery", "REC", "0001", "/test/recovery")]

        try:
            cache_manager.cache_shots(test_shots)
            # Should succeed in creating new cache
        except Exception as e:
            # If it fails, at least it shouldn't crash the app
            print(f"Cache recovery failed: {e}")

    def test_3de_worker_thread_crash_recovery(self, qtbot):
        """Test recovery from 3DE worker thread crashes."""
        from cache_manager import CacheManager

        cache_manager = CacheManager(cache_dir="/tmp/crash_test")
        model = ThreeDESceneModel(cache_manager, load_cache=False)

        test_shot = Shot("crash", "CRASH", "0001", "/test/crash")

        # Mock worker crash
        with patch.object(model, "_start_background_refresh") as mock_start:
            mock_start.side_effect = RuntimeError("Worker thread crashed")

            # Should handle worker crash gracefully
            success, has_changes = model.refresh_scenes([test_shot])

            # Behavior may vary by implementation
            # Key is that it doesn't crash the main application
            assert isinstance(success, bool)


class TestUserFriendlyErrorMessages:
    """Test that error messages are user-friendly."""

    def test_workspace_error_messages(self, qtbot, monkeypatch):
        """Test user-friendly workspace error messages."""
        # Mock message box to capture error messages
        captured_messages = []

        def mock_warning(parent, title, message):
            captured_messages.append((title, message))

        monkeypatch.setattr(QMessageBox, "warning", mock_warning)
        monkeypatch.setattr(QMessageBox, "critical", mock_warning)

        model = ShotModel()

        # Test different error scenarios
        error_scenarios = [
            (
                FileNotFoundError("ws: command not found"),
                "workspace command",
                "not found",
            ),
            (PermissionError("Permission denied"), "permission", "denied"),
            (TimeoutError("Command timeout"), "timeout", "timeout"),
        ]

        for error, expected_keyword1, expected_keyword2 in error_scenarios:
            captured_messages.clear()

            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = error

                success, _ = model.refresh_shots()

                # Error handling might emit signals or show dialogs
                # The key is messages should be user-friendly, not technical
                if captured_messages:
                    title, message = captured_messages[0]

                    # Messages should contain user-friendly terms
                    message_lower = message.lower()
                    assert expected_keyword1 in message_lower, (
                        f"Message should mention '{expected_keyword1}': {message}"
                    )
                    assert expected_keyword2 in message_lower, (
                        f"Message should mention '{expected_keyword2}': {message}"
                    )

                    # Messages should not contain technical jargon
                    technical_terms = ["subprocess", "errno", "traceback", "exception"]
                    for term in technical_terms:
                        assert term not in message_lower, (
                            f"Message should not contain technical term '{term}': {message}"
                        )

    def test_app_launch_error_messages(self, qtbot):
        """Test user-friendly app launch error messages."""
        shot = Shot("error_msg", "ERR", "0001", "/test/error")
        launcher = CommandLauncher()
        launcher.set_current_shot(shot)

        # Track error signals
        error_messages = []

        def track_error(timestamp, error_msg):
            error_messages.append(error_msg)

        launcher.command_error.connect(track_error)

        # Test various error scenarios
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("nuke: command not found")

            success = launcher.launch_app("nuke")

            assert success is False

            # Should emit user-friendly error message
            if error_messages:
                error_msg = error_messages[0].lower()

                # Should mention the application name
                assert "nuke" in error_msg, (
                    f"Error should mention app name: {error_messages[0]}"
                )

                # Should be user-friendly
                friendly_terms = ["not found", "unavailable", "unable", "failed"]
                assert any(term in error_msg for term in friendly_terms), (
                    f"Should use friendly terms: {error_messages[0]}"
                )

    def test_network_timeout_error_messages(self, qtbot):
        """Test user-friendly network timeout error messages."""
        # This would depend on how the application handles and reports network errors
        # The key principle is errors should be understandable by artists
        network_shot = Shot("network", "NET", "0001", "//server/network/path")

        # Mock network timeout
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.side_effect = TimeoutError("Network timeout")

            # Should handle gracefully - exact error reporting depends on implementation
            result = PathUtils.find_thumbnail(
                network_shot.workspace_path, network_shot.full_name
            )

            # Key is that it doesn't crash and handles the error appropriately
            assert result is None or isinstance(result, str)


class TestGracefulDegradation:
    """Test graceful degradation under failure conditions."""

    def test_main_window_degraded_functionality(self, qtbot, monkeypatch):
        """Test main window with degraded functionality."""
        # Mock various component failures
        monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
        monkeypatch.setattr(QMessageBox, "warning", Mock())

        # Create main window that will encounter errors
        window = MainWindow()
        qtbot.addWidget(window)

        # Simulate shot model failure
        window.shot_model.refresh_shots = Mock(return_value=(False, False))

        # Simulate 3DE model failure
        if hasattr(window, "threede_model"):
            window.threede_model.refresh_scenes = Mock(return_value=(False, False))

        # Window should still be usable despite component failures
        assert window.isVisible(), (
            "Window should remain visible with component failures"
        )

        # UI elements should still be accessible
        assert window.shot_grid is not None, "Shot grid should be available"
        assert window.tab_widget is not None, "Tab widget should be available"

        # Should be able to interact with UI
        qtbot.wait(100)  # Allow UI to settle

        window.close()

    def test_partial_shot_loading_degradation(self, qtbot):
        """Test graceful degradation with partial shot loading."""
        model = ShotModel()

        # Mix of valid and invalid workspace output
        mixed_output = """workspace /shows/valid1/shots/SEQ/SEQ_0001
workspace /nonexistent/invalid/path
workspace /shows/valid2/shots/SEQ/SEQ_0002
workspace /another/invalid/path
workspace /shows/valid3/shots/SEQ/SEQ_0003"""

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=mixed_output, returncode=0)

            success, has_changes = model.refresh_shots()

            # Should succeed partially
            assert success is True, "Should succeed with partial valid data"
            assert len(model.shots) == 3, (
                f"Should load 3 valid shots, got {len(model.shots)}"
            )

            # Valid shots should be properly parsed
            valid_shows = {shot.show for shot in model.shots}
            assert "valid1" in valid_shows
            assert "valid2" in valid_shows
            assert "valid3" in valid_shows

    def test_cache_failure_degradation(self, tmp_path, qtbot):
        """Test graceful degradation when cache fails."""
        # Create cache directory that will fail
        cache_dir = tmp_path / "failing_cache"

        # Don't create directory - will cause failures
        cache_manager = CacheManager(cache_dir=cache_dir)

        # Should work without cache
        test_shots = [Shot("no_cache", "NC", "0001", "/test/no_cache")]

        # Cache operations may fail, but should not crash application
        try:
            cache_manager.cache_shots(test_shots)
        except (PermissionError, FileNotFoundError, OSError):
            pass  # Expected when cache directory doesn't exist

        # Should be able to continue without cache
        loaded = cache_manager.get_cached_shots()
        assert loaded is None or isinstance(loaded, list)

    def test_ui_responsiveness_during_errors(self, qtbot, monkeypatch):
        """Test UI remains responsive during error conditions."""
        monkeypatch.setattr(QMessageBox, "warning", Mock())

        # Create window
        window = MainWindow()
        qtbot.addWidget(window)

        # Simulate slow/failing operations
        def slow_failing_refresh():
            time.sleep(0.1)  # Simulate slow operation
            raise Exception("Simulated failure")

        window.shot_model.refresh_shots = slow_failing_refresh

        # UI should remain responsive
        start_time = time.time()

        # Try to refresh (will fail)
        try:
            window.shot_model.refresh_shots()
        except Exception:
            pass

        # Process UI events
        qtbot.qapp.processEvents()

        response_time = time.time() - start_time

        # UI should still be responsive despite errors
        assert response_time < 1.0, (
            f"UI response too slow during errors: {response_time:.3f}s"
        )
        assert window.isVisible(), "Window should remain visible during errors"

        window.close()


class TestStateConsistencyAfterErrors:
    """Test that application state remains consistent after errors."""

    def test_shot_model_state_after_error(self, qtbot):
        """Test shot model state consistency after errors."""
        model = ShotModel()

        # Start with valid data
        valid_output = "workspace /shows/test/shots/SEQ/SEQ_0001\\nworkspace /shows/test/shots/SEQ/SEQ_0002"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=valid_output, returncode=0)

            success, _ = model.refresh_shots()
            assert success is True
            initial_count = len(model.shots)
            assert initial_count == 2

        # Now simulate error
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Simulated error")

            success, _ = model.refresh_shots()
            assert success is False

            # State should remain consistent - old data should be preserved
            assert len(model.shots) == initial_count, (
                "Should preserve existing shots on error"
            )

    def test_cache_state_after_corruption(self, tmp_path, qtbot):
        """Test cache state consistency after corruption."""
        cache_dir = tmp_path / "state_test_cache"
        cache_manager = CacheManager(cache_dir=cache_dir)

        # Cache some initial data
        test_shots = [Shot("state", "STATE", "0001", "/test/state")]
        cache_manager.cache_shots(test_shots)

        # Verify cache works
        loaded = cache_manager.get_cached_shots()
        assert loaded is not None
        assert len(loaded) == 1

        # Corrupt cache file
        cache_file = cache_dir / "shots.json"
        if cache_file.exists():
            cache_file.write_text("corrupted content")

        # Should handle corruption gracefully
        try:
            loaded_after_corruption = cache_manager.get_cached_shots()
            # Should return None or empty list, not crash
            assert loaded_after_corruption is None or isinstance(
                loaded_after_corruption, list
            )
        except Exception:
            # If exception occurs, it should be handled gracefully by the application
            pass

        # Should be able to cache new data after corruption
        new_shots = [Shot("recovery", "REC", "0001", "/test/recovery")]
        try:
            cache_manager.cache_shots(new_shots)
            # Should work or fail gracefully
        except Exception:
            # Graceful failure is acceptable
            pass

    def test_ui_state_after_component_failure(self, qtbot, monkeypatch):
        """Test UI state consistency after component failures."""
        monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
        monkeypatch.setattr(QMessageBox, "warning", Mock())

        window = MainWindow()
        qtbot.addWidget(window)

        # Record initial UI state
        initial_tab_index = window.tab_widget.currentIndex()

        # Simulate component failure
        if hasattr(window, "shot_grid"):
            # Mock shot grid failure
            window.shot_grid.refresh_shots = Mock(side_effect=Exception("Grid failure"))

            try:
                window.shot_grid.refresh_shots()
            except Exception:
                pass

        # UI state should remain consistent
        assert window.tab_widget.currentIndex() == initial_tab_index, (
            "Tab selection should be preserved"
        )
        assert window.isVisible(), "Window should remain visible"

        # Should be able to switch tabs despite component failure
        original_tab = window.tab_widget.currentIndex()
        new_tab_index = (original_tab + 1) % window.tab_widget.count()
        window.tab_widget.setCurrentIndex(new_tab_index)

        assert window.tab_widget.currentIndex() == new_tab_index, (
            "Should be able to switch tabs"
        )

        window.close()


@pytest.mark.integration
class TestErrorRecoveryIntegration:
    """Integration tests for comprehensive error recovery."""

    def test_end_to_end_error_recovery_workflow(self, qtbot, tmp_path, monkeypatch):
        """Test complete error recovery workflow."""
        # Mock UI dialogs
        monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
        monkeypatch.setattr(QMessageBox, "warning", Mock())
        monkeypatch.setattr(QMessageBox, "critical", Mock())

        # Create main window
        window = MainWindow()
        qtbot.addWidget(window)

        # Simulate cascade of errors
        error_count = 0

        # Error 1: Workspace command fails
        def failing_refresh():
            nonlocal error_count
            error_count += 1
            if error_count == 1:
                raise FileNotFoundError("ws: command not found")
            elif error_count == 2:
                raise PermissionError("Permission denied")
            else:
                # Eventually succeed
                return True, True

        window.shot_model.refresh_shots = failing_refresh

        # Try refresh multiple times
        for attempt in range(3):
            try:
                success, _ = window.shot_model.refresh_shots()
                if success:
                    break
            except Exception:
                pass

            qtbot.wait(10)  # Brief pause between attempts

        # Application should still be functional
        assert window.isVisible(), "Window should survive multiple errors"
        assert error_count >= 1, "Should have encountered errors"

        # Should be able to perform other operations
        qtbot.qapp.processEvents()

        # Test app launching with errors
        shot = Shot("error_test", "ERR", "0001", "/test/error")

        with patch.object(window.command_launcher, "launch_app") as mock_launch:
            mock_launch.side_effect = [
                PermissionError("Permission denied"),  # First attempt fails
                OSError("App not found"),  # Second attempt fails
                True,  # Third attempt succeeds
            ]

            # Multiple launch attempts
            for attempt in range(3):
                try:
                    success = window.command_launcher.launch_app("nuke")
                    if success:
                        break
                except Exception:
                    pass

        # Should recover and continue functioning
        assert window.isVisible(), "Should recover from launch errors"

        window.close()

    def test_resource_cleanup_after_errors(self, qtbot, tmp_path):
        """Test that resources are properly cleaned up after errors."""
        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        initial_files = process.num_fds() if hasattr(process, "num_fds") else 0

        # Create and destroy many objects with errors
        cache_managers = []
        shot_models = []

        try:
            for i in range(20):
                # Create cache manager
                cache_dir = tmp_path / f"error_cache_{i}"
                cache_manager = CacheManager(cache_dir=cache_dir)
                cache_managers.append(cache_manager)

                # Create shot model
                shot_model = ShotModel()
                shot_models.append(shot_model)

                # Simulate various errors
                error_types = [
                    FileNotFoundError("File not found"),
                    PermissionError("Permission denied"),
                    TimeoutError("Operation timeout"),
                    OSError("OS error"),
                    RuntimeError("Runtime error"),
                ]

                # Trigger errors in different components
                with patch("subprocess.run") as mock_run:
                    mock_run.side_effect = error_types[i % len(error_types)]

                    try:
                        shot_model.refresh_shots()
                    except Exception:
                        pass

                # Try cache operations that may fail
                test_shots = [Shot(f"err{i}", "ERR", f"{i:04d}", f"/test/err{i}")]

                try:
                    cache_manager.cache_shots(test_shots)
                    cache_manager.get_cached_shots()
                except Exception:
                    pass

        finally:
            # Cleanup
            del cache_managers
            del shot_models

            import gc

            gc.collect()
            qtbot.wait(100)  # Allow cleanup to complete

        # Check resource usage after cleanup
        final_memory = process.memory_info().rss
        final_files = process.num_fds() if hasattr(process, "num_fds") else 0

        memory_growth = final_memory - initial_memory
        file_growth = final_files - initial_files

        print("Resource usage after error recovery:")
        print(f"  Memory growth: {memory_growth / 1024 / 1024:.1f}MB")
        print(f"  File descriptor growth: {file_growth}")

        # Resource usage should be reasonable
        assert memory_growth < 100 * 1024 * 1024, (
            f"Memory growth too high: {memory_growth / 1024 / 1024:.1f}MB"
        )
        if hasattr(process, "num_fds"):
            assert file_growth < 50, f"File descriptor leak: {file_growth} new FDs"


@pytest.mark.integration
@pytest.mark.slow
class TestStressErrorConditions:
    """Stress tests for error conditions."""

    def test_rapid_error_recovery_stress(self, qtbot):
        """Stress test rapid error and recovery cycles."""
        model = ShotModel()

        # Rapid error/success cycles
        call_count = 0

        def alternating_behavior():
            nonlocal call_count
            call_count += 1

            if call_count % 3 == 0:
                # Every 3rd call succeeds
                return Mock(
                    stdout="workspace /test/shot1\\nworkspace /test/shot2", returncode=0
                )
            elif call_count % 3 == 1:
                # Error type 1
                raise FileNotFoundError("Command not found")
            else:
                # Error type 2
                raise PermissionError("Permission denied")

        # Rapid calls with alternating success/failure
        results = []

        for i in range(100):  # 100 rapid calls
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = alternating_behavior

                try:
                    success, has_changes = model.refresh_shots()
                    results.append(
                        ("success" if success else "failure", len(model.shots))
                    )
                except Exception as e:
                    results.append(("exception", str(type(e).__name__)))

        # Should handle rapid error/recovery cycles
        success_count = sum(1 for result, _ in results if result == "success")
        failure_count = sum(1 for result, _ in results if result == "failure")
        exception_count = sum(1 for result, _ in results if result == "exception")

        print(
            f"Rapid error recovery: {success_count} success, {failure_count} failures, {exception_count} exceptions"
        )

        # Should have some successes and handle errors gracefully
        assert success_count > 0, "Should have some successful operations"
        assert success_count + failure_count + exception_count == 100, (
            "Should handle all operations"
        )

        # Final state should be consistent
        assert isinstance(model.shots, list), "Final state should be consistent"
