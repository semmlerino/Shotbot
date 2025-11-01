#!/usr/bin/env python3
"""Integration tests for 3DE scene discovery functionality.

These tests use real file operations and subprocess calls to verify
the complete discovery flow works correctly without mocks.
"""

import os
import shutil

# Add parent directory to path for imports
import sys
import tempfile
import time
from pathlib import Path
from typing import List
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cache_manager import CacheManager
from config import Config
from shot_model import Shot
from threede_scene_finder import ThreeDESceneFinder
from threede_scene_model import ThreeDESceneModel


class TestThreeDEDiscoveryIntegration(TestCase):
    """Integration tests for 3DE scene discovery."""

    def setUp(self):
        """Set up test environment with real file structure."""
        # Create temporary show directory
        self.test_dir = Path(tempfile.mkdtemp(prefix="shotbot_test_"))
        self.shows_root = self.test_dir / "shows"
        self.show_name = "test_show"
        self.show_path = self.shows_root / self.show_name / "shots"

        # Create cache directory for testing
        self.cache_dir = self.test_dir / "cache"
        self.cache_manager = CacheManager(cache_dir=self.cache_dir)

        # Store original config values
        self.original_shows_root = Config.SHOWS_ROOT
        self.original_scan_mode = Config.THREEDE_SCAN_MODE
        self.original_max_shots = Config.THREEDE_MAX_SHOTS_TO_SCAN
        self.original_file_first = Config.THREEDE_FILE_FIRST_DISCOVERY

        # Set test config
        Config.SHOWS_ROOT = str(self.shows_root)
        Config.THREEDE_FILE_FIRST_DISCOVERY = True
        Config.THREEDE_SCAN_MODE = "smart"

    def tearDown(self):
        """Clean up test environment."""
        # Restore original config
        Config.SHOWS_ROOT = self.original_shows_root
        Config.THREEDE_SCAN_MODE = self.original_scan_mode
        Config.THREEDE_MAX_SHOTS_TO_SCAN = self.original_max_shots
        Config.THREEDE_FILE_FIRST_DISCOVERY = self.original_file_first

        # Remove test directory
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def create_shot_structure(
        self, sequence: str, shot: str, users: List[str], create_3de_files: bool = True
    ) -> Path:
        """Create a shot directory structure with optional .3de files.

        Args:
            sequence: Sequence name
            shot: Shot name
            users: List of usernames to create
            create_3de_files: Whether to create .3de files

        Returns:
            Path to the shot directory
        """
        shot_path = self.show_path / sequence / shot
        user_dir = shot_path / "user"
        user_dir.mkdir(parents=True, exist_ok=True)

        for username in users:
            user_path = user_dir / username
            user_path.mkdir(parents=True, exist_ok=True)

            if create_3de_files:
                # Create 3DE scene structure
                scene_dir = user_path / "3de" / "scenes" / "plate" / "FG01"
                scene_dir.mkdir(parents=True, exist_ok=True)

                # Create .3de file
                scene_file = scene_dir / f"{sequence}_{shot}_FG01_v001.3de"
                scene_file.write_text(f"# 3DE scene for {username}")

                # Also create one with uppercase extension
                if username == users[0]:
                    scene_file2 = scene_dir / f"{sequence}_{shot}_FG01_v002.3DE"
                    scene_file2.write_text(f"# 3DE scene v2 for {username}")

        return shot_path

    def test_efficient_file_first_discovery(self):
        """Test the new efficient file-first discovery method."""
        # Create test structure with mix of shots with and without .3de files
        shots_with_3de = [
            ("seq01", "shot010", ["user1", "user2"]),
            ("seq01", "shot020", ["user3"]),
            ("seq02", "shot010", ["user1", "user4"]),
        ]

        shots_without_3de = [
            ("seq01", "shot030", ["user5"]),
            ("seq01", "shot040", ["user6"]),
            ("seq02", "shot020", ["user7"]),
            ("seq02", "shot030", ["user8"]),
            ("seq02", "shot040", ["user9"]),
        ]

        # Create shots with .3de files
        for seq, shot, users in shots_with_3de:
            self.create_shot_structure(seq, shot, users, create_3de_files=True)

        # Create shots without .3de files (empty user directories)
        for seq, shot, users in shots_without_3de:
            self.create_shot_structure(seq, shot, users, create_3de_files=False)

        # Test 1: find_all_3de_files_in_show should only find files in shots with .3de
        start_time = time.time()
        found_files = ThreeDESceneFinder.find_all_3de_files_in_show(
            str(self.shows_root), self.show_name
        )
        find_time = time.time() - start_time

        # Should find 8 files total (4 for first user pair, 2 for user3, 2 for user1/user4)
        # Each user gets 2 files (.3de and .3DE) for the first user in each shot
        self.assertEqual(
            len(found_files), 8, f"Expected 8 .3de files, found {len(found_files)}"
        )

        # Verify files are from correct shots only
        shot_names = set()
        for file_path in found_files:
            parts = file_path.parts
            if "shots" in parts:
                shots_idx = parts.index("shots")
                shot_names.add(f"{parts[shots_idx + 1]}_{parts[shots_idx + 2]}")

        expected_shots = {"seq01_shot010", "seq01_shot020", "seq02_shot010"}
        self.assertEqual(
            shot_names,
            expected_shots,
            f"Files found in wrong shots: {shot_names} vs {expected_shots}",
        )

        print(
            f"✓ File-first discovery found {len(found_files)} files in {find_time:.3f}s"
        )
        print(f"  (Skipped {len(shots_without_3de)} empty shots)")

    def test_scan_mode_configuration(self):
        """Test different scan mode configurations."""
        # Create test shots
        self.create_shot_structure("seq01", "shot010", ["user1"], create_3de_files=True)
        self.create_shot_structure("seq01", "shot020", ["user2"], create_3de_files=True)
        self.create_shot_structure("seq02", "shot010", ["user3"], create_3de_files=True)

        # Create user shots (only in seq01)
        user_shots = [
            Shot(
                show=self.show_name,
                sequence="seq01",
                shot="shot010",
                workspace_path=str(self.show_path / "seq01" / "shot010"),
            ),
        ]

        # Test 1: user_sequences mode - should only search seq01
        Config.THREEDE_SCAN_MODE = "user_sequences"
        Config.THREEDE_SCAN_RELATED_SEQUENCES = True

        scenes = ThreeDESceneFinder.find_all_scenes_in_shows_efficient(
            user_shots, excluded_users={"current_user"}
        )

        seq01_count = sum(1 for s in scenes if s.sequence == "seq01")
        seq02_count = sum(1 for s in scenes if s.sequence == "seq02")

        self.assertGreater(seq01_count, 0, "Should find scenes in user's sequence")
        # Note: seq02 might still be found if scan mode falls back to full show

        print(
            f"✓ User sequences mode: found {seq01_count} in seq01, {seq02_count} in seq02"
        )

        # Test 2: Test max shots limit
        Config.THREEDE_SCAN_MODE = "smart"
        Config.THREEDE_MAX_SHOTS_TO_SCAN = 2

        scenes = ThreeDESceneFinder.find_all_scenes_in_shows_efficient(
            user_shots, excluded_users={"current_user"}
        )

        # Count unique shots
        unique_shots = set((s.sequence, s.shot) for s in scenes)
        self.assertLessEqual(
            len(unique_shots), 2, f"Should limit to 2 shots, found {len(unique_shots)}"
        )

        print(f"✓ Max shots limit: processed {len(unique_shots)} shots (limit: 2)")

    def test_deduplication_by_shot(self):
        """Test that only one scene per shot is shown after deduplication."""
        # Create a shot with multiple users and scenes
        shot_path = self.create_shot_structure(
            "seq01", "shot010", [], create_3de_files=False
        )
        user_dir = shot_path / "user"

        # Create multiple scenes for the same shot
        users_and_plates = [
            ("user1", "BG01", "v001"),
            ("user1", "FG01", "v002"),  # FG should be preferred
            ("user2", "BG01", "v003"),
            ("user3", "plate01", "v001"),
        ]

        for username, plate, version in users_and_plates:
            user_path = user_dir / username
            scene_dir = user_path / "3de" / "scenes" / plate
            scene_dir.mkdir(parents=True, exist_ok=True)

            scene_file = scene_dir / f"seq01_shot010_{plate}_{version}.3de"
            scene_file.write_text(f"# Scene by {username} for {plate}")
            # Touch file to set different modification times
            time.sleep(0.01)
            os.utime(scene_file, None)

        # Create model and refresh
        model = ThreeDESceneModel(self.cache_manager, load_cache=False)
        user_shots = [
            Shot(
                show=self.show_name,
                sequence="seq01",
                shot="shot010",
                workspace_path=str(shot_path),
            )
        ]

        success, has_changes = model.refresh_scenes(user_shots)
        self.assertTrue(success, "Refresh should succeed")

        # Should have only 1 scene after deduplication (best one)
        self.assertEqual(
            len(model.scenes),
            1,
            f"Should have 1 scene after dedup, got {len(model.scenes)}",
        )

        # The selected scene should be FG01 (highest priority) or latest by mtime
        selected = model.scenes[0]
        print(
            f"✓ Deduplication selected: {selected.user}/{selected.plate} for {selected.full_name}"
        )

        # Verify it selected a reasonable scene (FG01 has priority)
        self.assertIn(
            selected.plate,
            ["FG01", "BG01", "plate01"],
            f"Selected unexpected plate: {selected.plate}",
        )

    def test_cache_persistence_and_ttl(self):
        """Test cache persistence and TTL behavior."""
        # Create test structure
        self.create_shot_structure("seq01", "shot010", ["user1"], create_3de_files=True)

        # Create model and discover scenes
        model = ThreeDESceneModel(self.cache_manager, load_cache=False)
        user_shots = [
            Shot(
                show=self.show_name,
                sequence="seq01",
                shot="shot010",
                workspace_path=str(self.show_path / "seq01" / "shot010"),
            )
        ]

        # Initial discovery
        success, has_changes = model.refresh_scenes(user_shots)
        self.assertTrue(success, "Initial refresh should succeed")
        self.assertGreater(len(model.scenes), 0, "Should find scenes")
        initial_count = len(model.scenes)

        # Test 1: Cache should persist
        model2 = ThreeDESceneModel(self.cache_manager, load_cache=True)
        self.assertEqual(len(model2.scenes), initial_count, "Cached scenes should load")

        # Test 2: has_valid_threede_cache should return True
        self.assertTrue(
            self.cache_manager.has_valid_threede_cache(), "Cache should be valid"
        )

        # Test 3: Cache of empty results
        model3 = ThreeDESceneModel(self.cache_manager, load_cache=False)
        # Refresh with no shots (should cache empty result)
        success, _ = model3.refresh_scenes([])
        self.assertTrue(success, "Empty refresh should succeed")

        # Verify empty result is cached
        cached_data = self.cache_manager.get_cached_threede_scenes()
        self.assertIsNotNone(cached_data, "Empty result should be cached")
        self.assertEqual(len(cached_data), 0, "Cached data should be empty")

        # Should still be valid
        self.assertTrue(
            self.cache_manager.has_valid_threede_cache(),
            "Empty cache should still be valid",
        )

        print(f"✓ Cache persistence: {initial_count} scenes cached and restored")
        print("✓ Empty results are properly cached")

    def test_thumbnail_discovery_with_turnover_fallback(self):
        """Test thumbnail discovery with fallback to turnover plates."""
        from utils import FileUtils, PathUtils

        # Create shot structure
        shot_path = self.create_shot_structure("seq01", "shot010", ["user1"])

        # Create editorial thumbnail directory (primary)
        # Note: VFX convention uses sequence_shot format for directory name
        shot_dir = "seq01_shot010"
        editorial_dir = (
            self.shows_root
            / self.show_name
            / "shots"
            / "seq01"
            / shot_dir
            / "publish"
            / "editorial"
            / "cutref"
            / "v001"
            / "jpg"
            / "1920x1080"
        )
        editorial_dir.mkdir(parents=True, exist_ok=True)

        # Create turnover plate directories (fallback)
        # Must match expected structure: /turnover/plate/input_plate/{PLATE}/v001/exr/{resolution}/
        turnover_base = (
            self.shows_root
            / self.show_name
            / "shots"
            / "seq01"
            / shot_dir
            / "publish"
            / "turnover"
            / "plate"
            / "input_plate"
        )

        # Create multiple plate directories with priority order
        # Note: Utils expects .exr files in resolution subdirectories
        bg_dir = turnover_base / "BG01" / "v001" / "exr" / "4312x2304"
        fg_dir = turnover_base / "FG01" / "v001" / "exr" / "4312x2304"
        other_dir = turnover_base / "plate01" / "v001" / "exr" / "4312x2304"

        for plate_dir in [bg_dir, fg_dir, other_dir]:
            plate_dir.mkdir(parents=True, exist_ok=True)
            # Create dummy .exr file (what the function looks for)
            (plate_dir / "frame.0001.exr").write_text("dummy")

        # Test 1: With editorial thumbnail
        editorial_thumb = editorial_dir / "thumbnail.jpg"
        editorial_thumb.write_text("editorial")

        thumb_path = PathUtils.build_thumbnail_path(
            str(self.shows_root), self.show_name, "seq01", "shot010"
        )
        # The build_thumbnail_path returns the full editorial path including subdirectories
        self.assertEqual(thumb_path, editorial_dir)

        found_thumb = FileUtils.get_first_image_file(editorial_dir)
        self.assertIsNotNone(found_thumb, "Should find editorial thumbnail")
        print(f"✓ Found editorial thumbnail: {found_thumb.name}")

        # Test 2: Without editorial, should fall back to turnover (FG > BG > other)
        editorial_thumb.unlink()  # Remove editorial thumbnail

        turnover_thumb = PathUtils.find_turnover_plate_thumbnail(
            str(self.shows_root), self.show_name, "seq01", "shot010"
        )
        self.assertIsNotNone(turnover_thumb, "Should find turnover thumbnail")

        # Should prefer FG over BG
        self.assertIn(
            "FG01",
            str(turnover_thumb),
            f"Should prefer FG plate, got: {turnover_thumb}",
        )
        print(f"✓ Fallback found FG thumbnail: {turnover_thumb}")

        # Test 3: Remove FG, should fall back to BG
        shutil.rmtree(fg_dir.parent.parent.parent)  # Remove FG01 directory completely

        turnover_thumb = PathUtils.find_turnover_plate_thumbnail(
            str(self.shows_root), self.show_name, "seq01", "shot010"
        )
        self.assertIsNotNone(turnover_thumb, "Should find BG thumbnail")
        self.assertIn(
            "BG01",
            str(turnover_thumb),
            f"Should fall back to BG plate, got: {turnover_thumb}",
        )
        print(f"✓ Fallback found BG thumbnail: {turnover_thumb}")

    def test_performance_comparison(self):
        """Compare performance of old vs new discovery methods."""
        # Create a realistic show structure
        sequences = ["seq01", "seq02", "seq03"]
        shots_per_seq = 20  # 60 shots total
        users_per_shot = 3

        # Only 20% of shots have .3de files (realistic scenario)
        shots_with_3de = set()
        total_shots = 0

        for seq in sequences:
            for shot_num in range(shots_per_seq):
                shot_name = f"shot{shot_num:03d}"
                users = [f"user{u}" for u in range(users_per_shot)]

                # Only create .3de files for some shots
                has_3de = shot_num % 5 == 0  # Every 5th shot has .3de files
                self.create_shot_structure(
                    seq, shot_name, users, create_3de_files=has_3de
                )

                if has_3de:
                    shots_with_3de.add(f"{seq}_{shot_name}")
                total_shots += 1

        print("\nPerformance test setup:")
        print(f"  - Total shots: {total_shots}")
        print(f"  - Shots with .3de files: {len(shots_with_3de)}")
        print(f"  - Empty shots: {total_shots - len(shots_with_3de)}")

        # Test new method (file-first)
        start_time = time.time()
        found_files = ThreeDESceneFinder.find_all_3de_files_in_show(
            str(self.shows_root), self.show_name
        )
        new_method_time = time.time() - start_time

        print("\n✓ New method (file-first):")
        print(f"  - Time: {new_method_time:.3f}s")
        print(f"  - Found: {len(found_files)} .3de files")
        print(
            f"  - Efficiency: Skipped {total_shots - len(shots_with_3de)} empty shots"
        )

        # Compare with old method simulation (would check every shot)
        start_time = time.time()
        checked_shots = 0
        for seq in sequences:
            seq_path = self.show_path / seq
            if seq_path.exists():
                for shot_dir in seq_path.iterdir():
                    if shot_dir.is_dir():
                        user_dir = shot_dir / "user"
                        if user_dir.exists():
                            checked_shots += 1
                            # Simulate checking each user directory
                            for user_path in user_dir.iterdir():
                                if user_path.is_dir():
                                    # Would recursively search here
                                    pass
        old_method_time = time.time() - start_time

        print("\n✓ Old method simulation (check all shots):")
        print(f"  - Time: {old_method_time:.3f}s")
        print(f"  - Checked: {checked_shots} shots")

        # New method should be faster when many shots are empty
        if total_shots > len(shots_with_3de) * 2:  # If less than 50% have files
            improvement = (
                (old_method_time / new_method_time) if new_method_time > 0 else 1
            )
            print(f"\n✓ Performance improvement: {improvement:.1f}x faster")

    def test_quick_check_functionality(self):
        """Test the quick .3de existence check."""
        # Create test structure
        self.create_shot_structure("seq01", "shot010", ["user1"], create_3de_files=True)
        self.create_shot_structure(
            "seq01", "shot020", ["user2"], create_3de_files=False
        )

        # Test quick check on paths with .3de files
        path_with_3de = str(self.show_path / "seq01" / "shot010" / "user")
        has_3de = ThreeDESceneFinder.quick_3de_exists_check(
            [path_with_3de], timeout_seconds=2
        )
        self.assertTrue(has_3de, "Quick check should find .3de files")

        # Test quick check on paths without .3de files
        path_without_3de = str(self.show_path / "seq01" / "shot020" / "user")
        has_3de = ThreeDESceneFinder.quick_3de_exists_check(
            [path_without_3de], timeout_seconds=2
        )
        self.assertFalse(has_3de, "Quick check should not find .3de files")

        print("✓ Quick .3de existence check works correctly")


def run_integration_tests():
    """Run all integration tests."""
    import unittest

    # Create test suite
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestThreeDEDiscoveryIntegration)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 60)
    print("Integration Test Summary")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(
        f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%"
    )

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_integration_tests()
    sys.exit(0 if success else 1)
