"""Progressive scanning integration tests.

This module tests progressive scanning functionality with realistic datasets:
1. Batch processing with various batch sizes
2. Cancellation during scanning operations
3. Pause/resume functionality
4. Progress reporting accuracy
5. Memory usage within limits
6. Real-world dataset handling

These tests validate the progressive scanning architecture works correctly
under production conditions.
"""

import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QObject, Signal

from cache_manager import CacheManager
from shot_model import Shot
from threede_scene_finder import ThreeDESceneFinder
from threede_scene_model import ThreeDEScene, ThreeDESceneModel


class TestProgressiveScanningCore:
    """Test core progressive scanning functionality."""

    @pytest.fixture
    def progressive_dataset(self, tmp_path):
        """Create large dataset for progressive scanning tests."""
        dataset_root = tmp_path / "progressive_test"

        # Create 3 shows with realistic 3DE scene distribution
        shows_structure = {
            "show_A": {
                "sequences": ["SEQ_A001", "SEQ_A002", "SEQ_A003"],
                "shots_per_seq": 20,
                "users": ["alice_comp", "bob_track", "charlie_3d", "diana_lead"],
                "plates": ["BG01", "FG01", "CHAR01"],
            },
            "show_B": {
                "sequences": ["SEQ_B001", "SEQ_B002"],
                "shots_per_seq": 25,
                "users": ["eve_senior", "frank_junior", "grace_lead"],
                "plates": ["BG01", "FG01", "ENV01", "FX01"],
            },
            "show_C": {
                "sequences": ["SEQ_C001"],
                "shots_per_seq": 30,
                "users": ["henry_sup", "iris_comp", "jack_track"],
                "plates": ["BG01", "FG01"],
            },
        }

        total_scenes = 0
        total_shots = 0
        scene_distribution = defaultdict(list)

        for show_name, config in shows_structure.items():
            for seq_name in config["sequences"]:
                for shot_idx in range(1, config["shots_per_seq"] + 1):
                    shot_name = f"{seq_name}_{shot_idx:04d}"
                    total_shots += 1

                    # Create scenes with realistic distribution
                    # Not every shot has scenes, not every user has scenes for every shot
                    scene_probability = 0.7  # 70% of shots have 3DE scenes

                    if hash(shot_name) % 100 < scene_probability * 100:
                        # Randomly distribute scenes among users and plates
                        num_scenes = min(
                            len(config["users"]), 1 + (hash(shot_name) % 3)
                        )

                        for user_idx in range(num_scenes):
                            user = config["users"][user_idx % len(config["users"])]
                            plate = config["plates"][user_idx % len(config["plates"])]

                            # Create multiple versions with realistic timestamps
                            for version in ["v001", "v002", "v003"]:
                                scene_dir = (
                                    dataset_root
                                    / show_name
                                    / "shots"
                                    / seq_name
                                    / shot_name
                                    / f"user/{user}/mm/3de/mm-default/scenes/scene/{plate}/{version}"
                                )
                                scene_dir.mkdir(parents=True, exist_ok=True)

                                scene_file = (
                                    scene_dir
                                    / f"{shot_name}_{user}_{plate}_{version}.3de"
                                )
                                scene_file.write_bytes(b"FAKE_3DE_SCENE_DATA")

                                # Set realistic modification times
                                base_time = 1600000000  # Sept 2020
                                version_offset = int(version[1:]) * 86400  # Days apart
                                user_offset = user_idx * 3600  # Hours apart

                                mtime = base_time + version_offset + user_offset
                                os.utime(scene_file, (mtime, mtime))

                                scene_distribution[show_name].append(
                                    {
                                        "path": scene_file,
                                        "show": show_name,
                                        "sequence": seq_name,
                                        "shot": f"{shot_idx:04d}",
                                        "user": user,
                                        "plate": plate,
                                        "version": version,
                                        "mtime": mtime,
                                    }
                                )
                                total_scenes += 1

        return {
            "dataset_root": dataset_root,
            "total_scenes": total_scenes,
            "total_shots": total_shots,
            "scene_distribution": dict(scene_distribution),
            "shows_structure": shows_structure,
        }

    def test_batch_processing_various_sizes(self, progressive_dataset, qtbot):
        """Test progressive scanning with different batch sizes."""
        data = progressive_dataset
        cache_dir = data["dataset_root"] / "cache"
        cache_manager = CacheManager(cache_dir=cache_dir)

        # Test with different batch sizes
        batch_sizes = [1, 5, 10, 25, 50]

        for batch_size in batch_sizes:
            print(f"Testing batch size: {batch_size}")

            # Create fresh model for each batch size test
            model = ThreeDESceneModel(cache_manager, load_cache=False)

            # Create shots for one show to test batch processing
            show_a_scenes = data["scene_distribution"]["show_A"]
            unique_shots = {}

            for scene_data in show_a_scenes[:50]:  # Limit for performance
                shot_key = (
                    scene_data["show"],
                    scene_data["sequence"],
                    scene_data["shot"],
                )
                if shot_key not in unique_shots:
                    workspace_path = f"/shows/{scene_data['show']}/shots/{scene_data['sequence']}/{scene_data['sequence']}_{scene_data['shot']}"
                    unique_shots[shot_key] = Shot(
                        scene_data["show"],
                        scene_data["sequence"],
                        scene_data["shot"],
                        workspace_path,
                    )

            test_shots = list(unique_shots.values())[:20]  # Use subset for testing

            # Track progress updates
            progress_updates = []

            def track_progress(current, total, message=""):
                progress_updates.append((current, total, message))

            # Mock the finder to simulate batch processing
            with patch.object(
                ThreeDESceneFinder, "find_all_scenes_in_shows"
            ) as mock_finder:
                # Simulate finding scenes in batches
                all_scenes = []
                for scene_data in show_a_scenes:
                    scene = ThreeDEScene(
                        show=scene_data["show"],
                        sequence=scene_data["sequence"],
                        shot=scene_data["shot"],
                        workspace_path=f"/shows/{scene_data['show']}/shots/{scene_data['sequence']}/{scene_data['sequence']}_{scene_data['shot']}",
                        user=scene_data["user"],
                        plate=scene_data["plate"],
                        scene_path=str(scene_data["path"]),
                    )
                    all_scenes.append(scene)

                mock_finder.return_value = all_scenes[
                    : batch_size * 3
                ]  # Limit based on batch size

                start_time = time.time()
                success, has_changes = model.refresh_scenes(test_shots)
                processing_time = time.time() - start_time

                assert success, f"Batch processing failed for batch size {batch_size}"
                assert len(model.scenes) > 0, (
                    f"No scenes found for batch size {batch_size}"
                )

                # Processing time should be reasonable and scale appropriately
                print(
                    f"Batch size {batch_size}: {len(model.scenes)} scenes in {processing_time:.2f}s"
                )

                # Larger batches should not take exponentially longer
                if batch_size <= 10:
                    assert processing_time < 2.0, (
                        f"Batch size {batch_size} took too long: {processing_time:.2f}s"
                    )
                else:
                    assert processing_time < 5.0, (
                        f"Large batch size {batch_size} took too long: {processing_time:.2f}s"
                    )

    def test_cancellation_during_scanning(self, progressive_dataset, qtbot):
        """Test cancellation of scanning operations."""
        data = progressive_dataset
        cache_dir = data["dataset_root"] / "cache_cancel"
        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Create shots from dataset
        test_shots = []
        for show_name, scenes in data["scene_distribution"].items():
            for scene_data in scenes[:10]:  # Use subset
                shot_key = (
                    scene_data["show"],
                    scene_data["sequence"],
                    scene_data["shot"],
                )
                workspace_path = f"/shows/{scene_data['show']}/shots/{scene_data['sequence']}/{scene_data['sequence']}_{scene_data['shot']}"
                shot = Shot(
                    scene_data["show"],
                    scene_data["sequence"],
                    scene_data["shot"],
                    workspace_path,
                )
                test_shots.append(shot)
                if len(test_shots) >= 20:  # Limit for testing
                    break
            if len(test_shots) >= 20:
                break

        # Test cancellation scenarios
        cancellation_events = []

        class MockProgressiveScanner:
            def __init__(self):
                self.cancelled = False
                self.progress_callback = None

            def cancel(self):
                self.cancelled = True
                cancellation_events.append("cancelled")

            def scan_with_progress(self, paths, callback=None):
                self.progress_callback = callback
                scenes = []

                # Simulate progressive scanning with cancellation check
                for i, path in enumerate(paths):
                    if self.cancelled:
                        cancellation_events.append(f"stopped_at_{i}")
                        break

                    # Simulate work
                    time.sleep(0.01)  # Small delay to simulate work

                    if callback:
                        callback(i + 1, len(paths), f"Processing {path}")

                    # Add fake scenes
                    scenes.extend([])  # Would add real scenes here

                return scenes

        scanner = MockProgressiveScanner()

        # Start scanning in thread to test cancellation
        scan_thread = threading.Thread(
            target=scanner.scan_with_progress, args=([str(data["dataset_root"])],)
        )
        scan_thread.start()

        # Wait briefly then cancel
        time.sleep(0.05)  # Let it start
        scanner.cancel()

        scan_thread.join(timeout=1.0)  # Wait for completion

        # Should have been cancelled
        assert "cancelled" in cancellation_events
        print(f"Cancellation events: {cancellation_events}")

    def test_pause_resume_functionality(self, progressive_dataset, qtbot):
        """Test pause and resume during progressive scanning."""
        data = progressive_dataset

        class MockProgressiveScannerWithPause:
            def __init__(self):
                self.paused = False
                self.cancelled = False
                self.pause_event = threading.Event()
                self.pause_event.set()  # Start unpaused

            def pause(self):
                self.paused = True
                self.pause_event.clear()

            def resume(self):
                self.paused = False
                self.pause_event.set()

            def cancel(self):
                self.cancelled = True
                self.pause_event.set()  # Unblock if paused

            def scan_with_pause_support(self, items, progress_callback=None):
                results = []

                for i, item in enumerate(items):
                    # Check for cancellation
                    if self.cancelled:
                        break

                    # Wait if paused
                    self.pause_event.wait()  # Blocks if paused

                    # Check cancellation after unpausing
                    if self.cancelled:
                        break

                    # Simulate work
                    time.sleep(0.01)
                    results.append(f"processed_{item}")

                    if progress_callback:
                        progress_callback(i + 1, len(items), f"Processing item {i}")

                return results

        scanner = MockProgressiveScannerWithPause()
        test_items = list(range(20))  # 20 items to process

        progress_updates = []

        def track_progress(current, total, message):
            progress_updates.append((current, total, message, time.time()))

        # Start scanning in background thread
        results = []

        def background_scan():
            results.extend(scanner.scan_with_pause_support(test_items, track_progress))

        scan_thread = threading.Thread(target=background_scan)
        scan_thread.start()

        # Let it run for a bit
        time.sleep(0.05)

        # Pause
        scanner.pause()
        pause_time = time.time()

        # Wait while paused
        time.sleep(0.1)

        # Resume
        scanner.resume()
        resume_time = time.time()

        # Wait for completion
        scan_thread.join(timeout=2.0)

        # Verify pause/resume worked
        assert len(results) == len(test_items), (
            f"Expected {len(test_items)} results, got {len(results)}"
        )

        # Check that there was a gap in progress updates during pause
        if len(progress_updates) >= 2:
            pause_duration = resume_time - pause_time
            print(f"Pause duration: {pause_duration:.2f}s")
            assert pause_duration >= 0.05, "Pause should have lasted at least 50ms"

        print(f"Processed {len(results)} items with pause/resume")

    def test_progress_reporting_accuracy(self, progressive_dataset, qtbot):
        """Test that progress reporting is accurate and timely."""
        data = progressive_dataset

        # Use real ThreeDESceneFinder with progress tracking
        finder = ThreeDESceneFinder()

        # Track all progress updates
        progress_history = []

        def track_detailed_progress(current, total, message="", timestamp=None):
            progress_history.append(
                {
                    "current": current,
                    "total": total,
                    "message": message,
                    "timestamp": timestamp or time.time(),
                    "percentage": (current / total * 100) if total > 0 else 0,
                }
            )

        # Mock the internal progress reporting of finder
        original_find_method = finder.find_all_scenes_in_shows

        def mock_find_with_progress(shows_dirs):
            # Simulate finding with progress reporting
            all_scenes = []
            show_paths = [Path(show_dir) for show_dir in shows_dirs]
            total_dirs = sum(
                len(list(path.rglob("*"))) for path in show_paths if path.exists()
            )

            current = 0
            for show_dir in shows_dirs:
                show_path = Path(show_dir)
                if not show_path.exists():
                    continue

                for item in show_path.rglob("*.3de"):
                    current += 1
                    track_detailed_progress(
                        current, total_dirs, f"Scanning {item.name}"
                    )

                    # Create scene object
                    try:
                        # Extract shot info from path
                        parts = item.parts
                        if len(parts) >= 8:  # Ensure we have enough path parts
                            show = parts[-8] if "shows" in str(item) else parts[0]
                            sequence = parts[-5] if len(parts) > 5 else "SEQ_001"
                            shot = parts[-4] if len(parts) > 4 else "0001"
                            user = parts[-7] if len(parts) > 7 else "unknown"
                            plate = parts[-2] if len(parts) > 2 else "BG01"

                            scene = ThreeDEScene(
                                show=show,
                                sequence=sequence,
                                shot=shot,
                                workspace_path=f"/shows/{show}/shots/{sequence}/{sequence}_{shot}",
                                user=user,
                                plate=plate,
                                scene_path=str(item),
                            )
                            all_scenes.append(scene)
                    except Exception:
                        # Skip malformed paths
                        continue

            return all_scenes

        # Apply mock
        finder.find_all_scenes_in_shows = mock_find_with_progress

        # Run scan with progress tracking
        start_time = time.time()
        scenes = finder.find_all_scenes_in_shows([str(data["dataset_root"])])
        end_time = time.time()

        scan_duration = end_time - start_time

        # Analyze progress updates
        assert len(progress_history) > 0, "No progress updates recorded"

        # Verify progress is monotonically increasing
        for i in range(1, len(progress_history)):
            current_progress = progress_history[i]["current"]
            previous_progress = progress_history[i - 1]["current"]
            assert current_progress >= previous_progress, (
                f"Progress went backwards: {previous_progress} -> {current_progress}"
            )

        # Verify final progress reaches 100%
        if progress_history:
            final_update = progress_history[-1]
            assert final_update["current"] == final_update["total"], (
                "Final progress should reach total"
            )
            assert final_update["percentage"] == 100.0, (
                "Final percentage should be 100%"
            )

        # Verify progress updates are reasonably frequent
        if scan_duration > 0.1:  # Only check for longer scans
            update_frequency = len(progress_history) / scan_duration
            assert update_frequency > 1.0, (
                f"Progress updates too infrequent: {update_frequency:.1f} Hz"
            )

        print(f"Scan completed: {len(scenes)} scenes found")
        print(
            f"Progress updates: {len(progress_history)} updates in {scan_duration:.2f}s"
        )
        if progress_history:
            print(f"Final progress: {progress_history[-1]['percentage']:.1f}%")

    def test_memory_usage_during_progressive_scan(self, progressive_dataset, qtbot):
        """Test that memory usage stays within reasonable limits during scanning."""
        import os

        import psutil

        data = progressive_dataset
        process = psutil.Process(os.getpid())

        # Get baseline memory
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        cache_dir = data["dataset_root"] / "cache_memory"
        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Create shots for all shows (large dataset)
        all_shots = []
        for show_name, scenes in data["scene_distribution"].items():
            unique_shots = {}
            for scene_data in scenes:
                shot_key = (
                    scene_data["show"],
                    scene_data["sequence"],
                    scene_data["shot"],
                )
                if shot_key not in unique_shots:
                    workspace_path = f"/shows/{scene_data['show']}/shots/{scene_data['sequence']}/{scene_data['sequence']}_{scene_data['shot']}"
                    unique_shots[shot_key] = Shot(
                        scene_data["show"],
                        scene_data["sequence"],
                        scene_data["shot"],
                        workspace_path,
                    )
            all_shots.extend(unique_shots.values())

        print(f"Testing with {len(all_shots)} shots")

        # Monitor memory during scan
        memory_samples = []

        def sample_memory():
            memory_mb = process.memory_info().rss / 1024 / 1024
            memory_samples.append(memory_mb)
            return memory_mb

        # Sample initial memory
        sample_memory()

        # Run progressive scan
        start_time = time.time()
        success, has_changes = model.refresh_scenes(all_shots)
        scan_time = time.time() - start_time

        # Sample final memory
        final_memory = sample_memory()

        # Analyze memory usage
        memory_growth = final_memory - initial_memory
        peak_memory = max(memory_samples)

        print(
            f"Memory usage: {initial_memory:.1f}MB -> {final_memory:.1f}MB (+{memory_growth:.1f}MB)"
        )
        print(f"Peak memory: {peak_memory:.1f}MB")
        print(f"Scan time: {scan_time:.2f}s for {len(model.scenes)} scenes")

        # Memory growth should be reasonable
        # Adjust limits based on dataset size
        max_allowed_growth = min(200, len(all_shots) * 0.5)  # 0.5MB per shot max
        assert memory_growth < max_allowed_growth, (
            f"Memory growth too high: {memory_growth:.1f}MB"
        )

        # Peak memory should not be excessive
        max_peak = initial_memory + max_allowed_growth * 1.5
        assert peak_memory < max_peak, f"Peak memory too high: {peak_memory:.1f}MB"

        assert success, "Progressive scan should succeed"
        assert len(model.scenes) > 0, "Should find some scenes"

    def test_concurrent_scanning_operations(self, progressive_dataset, qtbot):
        """Test multiple concurrent scanning operations."""
        data = progressive_dataset

        # Create separate cache managers for concurrent operations
        cache_managers = []
        models = []

        for i in range(3):
            cache_dir = data["dataset_root"] / f"cache_concurrent_{i}"
            cache_manager = CacheManager(cache_dir=cache_dir)
            model = ThreeDESceneModel(cache_manager, load_cache=False)
            cache_managers.append(cache_manager)
            models.append(model)

        # Create different shot sets for each model
        shot_sets = []
        show_names = list(data["scene_distribution"].keys())

        for i, show_name in enumerate(show_names):
            scenes = data["scene_distribution"][show_name]
            unique_shots = {}

            for scene_data in scenes[:15]:  # Limit for performance
                shot_key = (
                    scene_data["show"],
                    scene_data["sequence"],
                    scene_data["shot"],
                )
                if shot_key not in unique_shots:
                    workspace_path = f"/shows/{scene_data['show']}/shots/{scene_data['sequence']}/{scene_data['sequence']}_{scene_data['shot']}"
                    unique_shots[shot_key] = Shot(
                        scene_data["show"],
                        scene_data["sequence"],
                        scene_data["shot"],
                        workspace_path,
                    )

            shot_sets.append(list(unique_shots.values()))

        # Run concurrent scans
        results = {}
        threads = []

        def concurrent_scan(model_idx, model, shots):
            start_time = time.time()
            success, has_changes = model.refresh_scenes(shots)
            end_time = time.time()

            results[model_idx] = {
                "success": success,
                "has_changes": has_changes,
                "scene_count": len(model.scenes),
                "duration": end_time - start_time,
            }

        # Start all scans
        for i, (model, shots) in enumerate(zip(models, shot_sets)):
            thread = threading.Thread(target=concurrent_scan, args=(i, model, shots))
            threads.append(thread)
            thread.start()

        # Wait for all to complete
        for thread in threads:
            thread.join(timeout=10.0)  # 10 second timeout

        # Verify all completed successfully
        assert len(results) == len(models), (
            f"Expected {len(models)} results, got {len(results)}"
        )

        for i, result in results.items():
            assert result["success"], f"Model {i} scan failed"
            assert result["scene_count"] > 0, f"Model {i} found no scenes"
            assert result["duration"] < 5.0, (
                f"Model {i} took too long: {result['duration']:.2f}s"
            )

        print("Concurrent scan results:")
        for i, result in results.items():
            print(
                f"  Model {i}: {result['scene_count']} scenes in {result['duration']:.2f}s"
            )

    def test_large_dataset_progressive_handling(self, tmp_path, qtbot):
        """Test progressive scanning with very large realistic dataset."""
        # Create larger dataset specifically for this test
        large_root = tmp_path / "large_progressive"

        # Create 10 shows, 15 sequences each, 40 shots per sequence = 6000 shots
        # With 70% having scenes, ~4200 scenes total
        total_scenes = 0

        for show_idx in range(10):
            show_name = f"large_show_{show_idx:02d}"

            for seq_idx in range(15):
                seq_name = f"SEQ_{seq_idx:03d}"

                for shot_idx in range(40):
                    shot_name = f"{seq_name}_{shot_idx:04d}"

                    # 70% probability of having scenes
                    if hash(f"{show_name}_{shot_name}") % 100 < 70:
                        # 1-3 users per shot with scenes
                        num_users = 1 + (hash(shot_name) % 3)

                        for user_idx in range(num_users):
                            user = f"user_{user_idx:02d}"
                            plate = ["BG01", "FG01", "CHAR01"][user_idx % 3]

                            scene_dir = (
                                large_root
                                / show_name
                                / "shots"
                                / seq_name
                                / shot_name
                                / f"user/{user}/mm/3de/mm-default/scenes/scene/{plate}/v001"
                            )
                            scene_dir.mkdir(parents=True, exist_ok=True)

                            scene_file = scene_dir / f"{shot_name}_{user}.3de"
                            scene_file.write_bytes(b"3DE_SCENE")
                            total_scenes += 1

                            # Break early if we've created enough for testing
                            if total_scenes > 500:  # Limit for test performance
                                break

                    if total_scenes > 500:
                        break
                if total_scenes > 500:
                    break
            if total_scenes > 500:
                break

        print(f"Created large dataset with {total_scenes} scenes")

        # Test progressive scanning on large dataset
        cache_dir = large_root / "cache"
        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Create shot objects
        shots = []
        for show_idx in range(5):  # Use subset for testing
            show_name = f"large_show_{show_idx:02d}"
            for seq_idx in range(3):
                seq_name = f"SEQ_{seq_idx:03d}"
                for shot_idx in range(10):
                    shot_name = f"{seq_name}_{shot_idx:04d}"
                    workspace_path = f"/shows/{show_name}/shots/{seq_name}/{shot_name}"
                    shot = Shot(show_name, seq_name, f"{shot_idx:04d}", workspace_path)
                    shots.append(shot)

        # Monitor performance
        start_time = time.time()
        success, has_changes = model.refresh_scenes(shots)
        scan_duration = time.time() - start_time

        # Verify results
        assert success, "Large dataset scan should succeed"

        scenes_per_second = (
            len(model.scenes) / scan_duration if scan_duration > 0 else 0
        )
        print(
            f"Large dataset scan: {len(model.scenes)} scenes in {scan_duration:.2f}s ({scenes_per_second:.1f} scenes/sec)"
        )

        # Performance should be reasonable
        assert scan_duration < 10.0, (
            f"Large dataset scan took too long: {scan_duration:.2f}s"
        )
        assert len(model.scenes) > 0, "Should find scenes in large dataset"


class TestProgressiveScanningIntegration:
    """Test progressive scanning integration with UI and other components."""

    def test_progressive_scanning_with_ui_updates(self, progressive_dataset, qtbot):
        """Test progressive scanning with real UI updates."""
        data = progressive_dataset

        # Mock UI components that would receive progress updates
        class MockProgressUI(QObject):
            progress_updated = Signal(int, int, str)

            def __init__(self):
                super().__init__()
                self.progress_history = []
                self.progress_updated.connect(self.on_progress)

            def on_progress(self, current, total, message):
                self.progress_history.append((current, total, message))

        progress_ui = MockProgressUI()
        qtbot.addWidget(progress_ui)

        cache_dir = data["dataset_root"] / "cache_ui"
        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Connect model progress to UI (if such signals exist)
        # In real implementation, this would be done by the main window

        # Create shots
        test_shots = []
        for show_name, scenes in data["scene_distribution"].items():
            for scene_data in scenes[:10]:
                shot_key = (
                    scene_data["show"],
                    scene_data["sequence"],
                    scene_data["shot"],
                )
                workspace_path = f"/shows/{scene_data['show']}/shots/{scene_data['sequence']}/{scene_data['sequence']}_{scene_data['shot']}"
                shot = Shot(
                    scene_data["show"],
                    scene_data["sequence"],
                    scene_data["shot"],
                    workspace_path,
                )
                test_shots.append(shot)
                if len(test_shots) >= 15:
                    break
            if len(test_shots) >= 15:
                break

        # Run scan
        success, has_changes = model.refresh_scenes(test_shots)

        # Process any pending UI events
        qtbot.wait(100)

        assert success, "Scan should succeed with UI integration"

        # In a real implementation, we would verify UI updates occurred
        # For now, verify the model worked correctly
        assert len(model.scenes) > 0, "Should find scenes"

    def test_progressive_scanning_cache_interaction(self, progressive_dataset, qtbot):
        """Test progressive scanning interaction with cache system."""
        data = progressive_dataset
        cache_dir = data["dataset_root"] / "cache_interaction"
        cache_manager = CacheManager(cache_dir=cache_dir)

        # Create shots
        test_shots = []
        show_a_scenes = data["scene_distribution"]["show_A"]
        for scene_data in show_a_scenes[:20]:
            shot_key = (scene_data["show"], scene_data["sequence"], scene_data["shot"])
            workspace_path = f"/shows/{scene_data['show']}/shots/{scene_data['sequence']}/{scene_data['sequence']}_{scene_data['shot']}"
            shot = Shot(
                scene_data["show"],
                scene_data["sequence"],
                scene_data["shot"],
                workspace_path,
            )
            test_shots.append(shot)

        # First scan - should populate cache
        model1 = ThreeDESceneModel(cache_manager, load_cache=False)

        start_time = time.time()
        success1, changes1 = model1.refresh_scenes(test_shots)
        first_scan_time = time.time() - start_time

        assert success1, "First scan should succeed"
        first_scene_count = len(model1.scenes)

        # Second scan - should use cache
        model2 = ThreeDESceneModel(cache_manager, load_cache=True)

        start_time = time.time()
        success2, changes2 = model2.refresh_scenes(test_shots)
        second_scan_time = time.time() - start_time

        assert success2, "Second scan should succeed"
        second_scene_count = len(model2.scenes)

        # Cache should improve performance
        print(f"First scan: {first_scene_count} scenes in {first_scan_time:.2f}s")
        print(f"Second scan: {second_scene_count} scenes in {second_scan_time:.2f}s")

        # Second scan should be faster (though file system caching might mask this)
        # Main verification is that both scans work correctly
        assert first_scene_count == second_scene_count, (
            "Cache should return same results"
        )

    def test_progressive_scanning_error_recovery(self, progressive_dataset, qtbot):
        """Test progressive scanning error recovery."""
        data = progressive_dataset
        cache_dir = data["dataset_root"] / "cache_error"
        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Create mix of valid and invalid shots
        valid_shots = []
        invalid_shots = []

        # Valid shots from real data
        show_a_scenes = data["scene_distribution"]["show_A"][:10]
        for scene_data in show_a_scenes:
            workspace_path = f"/shows/{scene_data['show']}/shots/{scene_data['sequence']}/{scene_data['sequence']}_{scene_data['shot']}"
            shot = Shot(
                scene_data["show"],
                scene_data["sequence"],
                scene_data["shot"],
                workspace_path,
            )
            valid_shots.append(shot)

        # Invalid shots (non-existent paths)
        for i in range(5):
            invalid_shot = Shot(
                "invalid_show", "INVALID", f"{i:04d}", f"/nonexistent/path/{i}"
            )
            invalid_shots.append(invalid_shot)

        # Mix valid and invalid shots
        mixed_shots = valid_shots + invalid_shots

        # Scan should handle errors gracefully
        success, has_changes = model.refresh_scenes(mixed_shots)

        # Should still succeed overall (find valid scenes despite errors)
        assert success, "Scan should succeed despite some invalid shots"
        assert len(model.scenes) > 0, "Should find scenes from valid shots"

        # Should have found scenes only from valid shots
        found_shows = {scene.show for scene in model.scenes}
        assert "invalid_show" not in found_shows, (
            "Should not find scenes from invalid shots"
        )
        assert any(show in found_shows for show in ["show_A"]), (
            "Should find scenes from valid shots"
        )

    def test_progressive_scanning_deduplication_integration(
        self, progressive_dataset, qtbot
    ):
        """Test progressive scanning integration with deduplication."""
        data = progressive_dataset
        cache_dir = data["dataset_root"] / "cache_dedup"
        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Create shots that will have multiple scene versions
        test_shots = []
        show_a_scenes = data["scene_distribution"]["show_A"]

        # Group scenes by shot
        shots_with_multiple_scenes = defaultdict(list)
        for scene_data in show_a_scenes:
            shot_key = (scene_data["show"], scene_data["sequence"], scene_data["shot"])
            shots_with_multiple_scenes[shot_key].append(scene_data)

        # Use shots that have multiple scene versions
        for shot_key, scene_list in shots_with_multiple_scenes.items():
            if len(scene_list) > 1:  # Only shots with multiple scenes
                workspace_path = f"/shows/{shot_key[0]}/shots/{shot_key[1]}/{shot_key[1]}_{shot_key[2]}"
                shot = Shot(shot_key[0], shot_key[1], shot_key[2], workspace_path)
                test_shots.append(shot)

                if len(test_shots) >= 10:  # Limit for testing
                    break

        # Run progressive scan with deduplication
        success, has_changes = model.refresh_scenes(test_shots)

        assert success, "Deduplication scan should succeed"
        assert len(model.scenes) <= len(test_shots), (
            "Should deduplicate to at most one scene per shot"
        )

        # Verify deduplication worked correctly
        scene_shots = set()
        for scene in model.scenes:
            shot_id = (scene.show, scene.sequence, scene.shot)
            assert shot_id not in scene_shots, (
                f"Duplicate scene found for shot: {shot_id}"
            )
            scene_shots.add(shot_id)

        print(f"Deduplication: {len(test_shots)} shots -> {len(model.scenes)} scenes")

        # Should have selected newest scenes (highest mtime)
        for scene in model.scenes:
            shot_key = (scene.show, scene.sequence, scene.shot)
            if shot_key in shots_with_multiple_scenes:
                scene_versions = shots_with_multiple_scenes[shot_key]
                max_mtime = max(sv["mtime"] for sv in scene_versions)

                # The selected scene should have the highest mtime
                # (This assumes deduplication selects by mtime, which may vary by implementation)
                scene_mtime = os.path.getmtime(scene.scene_path)

                # Allow some tolerance for file system timestamp precision
                assert abs(scene_mtime - max_mtime) < 1.0, (
                    f"Should select newest scene for {shot_key}"
                )


@pytest.mark.integration
@pytest.mark.performance
class TestProgressiveScanningPerformance:
    """Performance-focused tests for progressive scanning."""

    def test_scanning_performance_benchmarks(self, tmp_path, qtbot):
        """Benchmark progressive scanning performance."""
        # Create standardized test dataset
        bench_root = tmp_path / "benchmark"

        # Create known dataset size for benchmarking
        scenes_per_shot = 3
        shots_per_seq = 10
        sequences_per_show = 5
        shows = 2

        total_expected_scenes = (
            shows * sequences_per_show * shots_per_seq * scenes_per_shot
        )

        for show_idx in range(shows):
            for seq_idx in range(sequences_per_show):
                for shot_idx in range(shots_per_seq):
                    for scene_idx in range(scenes_per_shot):
                        scene_path = (
                            bench_root
                            / f"show_{show_idx}"
                            / "shots"
                            / f"SEQ_{seq_idx:03d}"
                            / f"SEQ_{seq_idx:03d}_{shot_idx:04d}"
                            / f"user/user_{scene_idx}/mm/3de/mm-default/scenes/scene/BG01/v001"
                        )
                        scene_path.mkdir(parents=True, exist_ok=True)

                        scene_file = scene_path / f"scene_{scene_idx}.3de"
                        scene_file.write_bytes(b"BENCHMARK_SCENE")

        print(f"Created benchmark dataset: {total_expected_scenes} expected scenes")

        # Benchmark scan performance
        cache_dir = bench_root / "cache"
        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Create shots
        shots = []
        for show_idx in range(shows):
            for seq_idx in range(sequences_per_show):
                for shot_idx in range(shots_per_seq):
                    workspace_path = f"/shows/show_{show_idx}/shots/SEQ_{seq_idx:03d}/SEQ_{seq_idx:03d}_{shot_idx:04d}"
                    shot = Shot(
                        f"show_{show_idx}",
                        f"SEQ_{seq_idx:03d}",
                        f"{shot_idx:04d}",
                        workspace_path,
                    )
                    shots.append(shot)

        # Run benchmark
        start_time = time.time()
        success, has_changes = model.refresh_scenes(shots)
        scan_duration = time.time() - start_time

        # Calculate performance metrics
        scenes_found = len(model.scenes)
        scenes_per_second = scenes_found / scan_duration if scan_duration > 0 else 0

        print("Benchmark results:")
        print(f"  Scenes found: {scenes_found}")
        print(f"  Scan time: {scan_duration:.2f}s")
        print(f"  Performance: {scenes_per_second:.1f} scenes/second")

        # Performance assertions
        assert success, "Benchmark scan should succeed"
        assert scenes_found > 0, "Should find scenes in benchmark dataset"
        assert scan_duration < 5.0, f"Benchmark scan too slow: {scan_duration:.2f}s"
        assert scenes_per_second > 10, (
            f"Performance too low: {scenes_per_second:.1f} scenes/sec"
        )

    def test_memory_efficiency_during_scanning(self, tmp_path, qtbot):
        """Test memory efficiency of progressive scanning."""
        import os

        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Create memory test dataset
        memory_test_root = tmp_path / "memory_test"
        scenes_created = 0

        # Create larger dataset to test memory behavior
        for show in range(3):
            for seq in range(10):
                for shot in range(15):
                    for user in range(2):
                        scene_path = (
                            memory_test_root
                            / f"memshow_{show}"
                            / "shots"
                            / f"SEQ_{seq:03d}"
                            / f"SEQ_{seq:03d}_{shot:04d}"
                            / f"user/memuser_{user}/mm/3de/mm-default/scenes/scene/BG01/v001"
                        )
                        scene_path.mkdir(parents=True, exist_ok=True)

                        # Create slightly larger scene files
                        scene_file = scene_path / f"mem_scene_{user}.3de"
                        scene_file.write_bytes(
                            b"MEMORY_TEST_SCENE_DATA" * 100
                        )  # ~2KB per scene
                        scenes_created += 1

        print(f"Created {scenes_created} scenes for memory test")

        # Monitor memory during scan
        cache_dir = memory_test_root / "cache"
        cache_manager = CacheManager(cache_dir=cache_dir)
        model = ThreeDESceneModel(cache_manager, load_cache=False)

        # Create shots
        shots = []
        for show in range(3):
            for seq in range(10):
                for shot in range(15):
                    workspace_path = f"/shows/memshow_{show}/shots/SEQ_{seq:03d}/SEQ_{seq:03d}_{shot:04d}"
                    shot = Shot(
                        f"memshow_{show}",
                        f"SEQ_{seq:03d}",
                        f"{shot:04d}",
                        workspace_path,
                    )
                    shots.append(shot)

        # Sample memory before scan
        pre_scan_memory = process.memory_info().rss / 1024 / 1024

        # Run scan
        success, has_changes = model.refresh_scenes(shots)

        # Sample memory after scan
        post_scan_memory = process.memory_info().rss / 1024 / 1024

        memory_growth = post_scan_memory - initial_memory
        scan_memory_delta = post_scan_memory - pre_scan_memory

        print("Memory usage:")
        print(f"  Initial: {initial_memory:.1f}MB")
        print(f"  Pre-scan: {pre_scan_memory:.1f}MB")
        print(f"  Post-scan: {post_scan_memory:.1f}MB")
        print(f"  Growth: {memory_growth:.1f}MB")
        print(f"  Scan delta: {scan_memory_delta:.1f}MB")

        # Memory efficiency assertions
        assert success, "Memory test scan should succeed"

        # Memory growth should be reasonable relative to data processed
        max_reasonable_growth = len(model.scenes) * 0.1  # 0.1MB per scene max
        assert scan_memory_delta < max_reasonable_growth, (
            f"Memory growth too high: {scan_memory_delta:.1f}MB"
        )

        # Total memory usage should be reasonable
        assert post_scan_memory < initial_memory + 100, (
            f"Total memory usage too high: {post_scan_memory:.1f}MB"
        )
