"""Integration tests for complete 3DE scene discovery workflow.

Following UNIFIED_TESTING_GUIDE:
- Integration Test Pattern (line 186)
- Use real components with test doubles at boundaries (line 189)
- Only mock the system boundary (line 193)
"""

from __future__ import annotations

# Standard library imports
from unittest.mock import patch

# Third-party imports
import pytest


pytestmark = [
    pytest.mark.qt,  # CRITICAL: Qt state must be serialized
    pytest.mark.real_subprocess,  # Uses find command for 3DE discovery
]


class TestThreeDEDiscoveryIntegration:
    """Integration tests for the complete 3DE discovery workflow.

    Tests the full pipeline from file discovery through scene creation,
    ensuring the filtering bug is truly fixed.
    """

    @pytest.fixture
    def temp_vfx_structure(self, tmp_path):
        """Create a realistic VFX directory structure with 3DE files."""
        shows_root = tmp_path / "shows"

        # Create structure matching production
        shots_data = [
            # User's assigned shots
            ("gator", "013_DC", "2120", "gabriel-h"),
            ("jack_ryan", "MA_074", "0340", "gabriel-h"),
            # Other users' work on assigned shots
            ("gator", "013_DC", "2120", "sarah-b"),
            ("jack_ryan", "MA_074", "0340", "tony-a"),
            # Other users' work on NON-assigned shots (CRITICAL TEST)
            ("gator", "019_JF", "1060", "tony-a"),
            ("jack_ryan", "DM_062", "3220", "ryan-p"),
            ("jack_ryan", "DM_062", "3280", "ryan-p"),
            ("broken_eggs", "BRX_119", "0010", "alex-k"),
            ("broken_eggs", "BRX_170", "0100", "mike-d"),
            # Published files
            ("jack_ryan", "MA_074", "0340", "published-mm"),
        ]

        # Shots with published matchmove (publish/mm directory exists)
        # These shots will be included in discovery results
        shots_with_published_mm = {
            ("gator", "013_DC", "2120"),
            ("jack_ryan", "MA_074", "0340"),
            ("gator", "019_JF", "1060"),
            ("jack_ryan", "DM_062", "3220"),
            ("jack_ryan", "DM_062", "3280"),
            ("broken_eggs", "BRX_119", "0010"),
            ("broken_eggs", "BRX_170", "0100"),
        }

        created_files = []
        for show, seq, shot, user in shots_data:
            shot_dir = f"{seq}_{shot}"
            if user.startswith("published"):
                # Published files go in publish directory
                dept = user.split("-")[1]
                file_path = (
                    shows_root
                    / show
                    / "shots"
                    / seq
                    / shot_dir
                    / "publish"
                    / dept
                    / "3de"
                    / f"{seq}_{shot}_{dept}.3de"
                )
            else:
                # User files go in user directory
                file_path = (
                    shows_root
                    / show
                    / "shots"
                    / seq
                    / shot_dir
                    / "user"
                    / user
                    / "mm"
                    / "3de"
                    / f"{seq}_{shot}_scene.3de"
                )

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text("# Mock 3DE file")
            created_files.append((file_path, show, seq, shot, user))

            # Create publish/mm directory for shots with published matchmove
            if (show, seq, shot) in shots_with_published_mm:
                publish_mm_dir = (
                    shows_root / show / "shots" / seq / shot_dir / "publish" / "mm"
                )
                publish_mm_dir.mkdir(parents=True, exist_ok=True)

        return shows_root, created_files

    @pytest.fixture
    def make_user_shots(self, temp_vfx_structure):
        """Factory for creating user's assigned shots."""
        # Standard library imports
        from collections import (
            namedtuple,
        )

        Shot = namedtuple("Shot", ["workspace_path", "show", "sequence", "shot"])
        shows_root, _ = temp_vfx_structure

        def _make():
            # User has shots assigned across multiple shows
            # Use the actual temp directory paths
            return [
                Shot(
                    f"{shows_root}/gator/shots/013_DC/013_DC_2120",
                    "gator",
                    "013_DC",
                    "2120",
                ),
                Shot(
                    f"{shows_root}/jack_ryan/shots/MA_074/MA_074_0340",
                    "jack_ryan",
                    "MA_074",
                    "0340",
                ),
                Shot(
                    f"{shows_root}/broken_eggs/shots/BRX_119/BRX_119_0010",
                    "broken_eggs",
                    "BRX_119",
                    "0010",
                ),
            ]

        return _make

    def test_parallel_discovery_finds_all_scenes(
        self, temp_vfx_structure, make_user_shots
    ) -> None:
        """Test that parallel discovery finds ALL scenes from other users.

        This is the main integration test that verifies the fix works end-to-end.
        """
        shows_root, _created_files = temp_vfx_structure
        user_shots = make_user_shots()

        # Local application imports
        from config import (
            Config,
        )
        from threede.scene_discovery_coordinator import (
            SceneDiscoveryCoordinator,
        )

        # Set up excluded users (current user)
        excluded_users = {"gabriel-h"}

        # Mock the shows_root to use our temp structure
        with patch.object(Config, "SHOWS_ROOT", str(shows_root)):
            # Run the actual discovery
            scenes = SceneDiscoveryCoordinator.find_all_scenes_in_shows(
                user_shots,
                excluded_users,
                progress_callback=None,
                cancel_flag=lambda: False,
            )

        # CRITICAL ASSERTION: Should find ALL scenes except gabriel-h's
        # With the bug: Would find only 1 (published-mm on MA_074_0340)
        # With the fix: Should find 6+ scenes from other users (shots with publish/mm)
        found_users = {scene.user for scene in scenes}

        assert len(scenes) >= 6, f"Should find at least 6 scenes, found {len(scenes)}"
        assert "gabriel-h" not in found_users, "Should exclude current user"

        # Verify scenes from NON-assigned shots are included
        non_assigned_scenes = [
            s
            for s in scenes
            if (s.sequence, s.shot) not in [("013_DC", "2120"), ("MA_074", "0340")]
        ]
        assert len(non_assigned_scenes) > 0, (
            "Should include scenes from non-assigned shots"
        )

        # Verify workspace paths are correctly set
        for scene in scenes:
            assert scene.workspace_path, "Every scene should have a workspace path"
            expected_path = f"{shows_root}/{scene.show}/shots/{scene.sequence}/{scene.sequence}_{scene.shot}"
            assert scene.workspace_path == expected_path

    def test_scene_filtering_with_real_parser(self, temp_vfx_structure) -> None:
        """Test scene filtering using the real SceneParser component."""
        # Local application imports
        from threede.scene_parser import (
            SceneParser,
        )

        shows_root, created_files = temp_vfx_structure
        parser = SceneParser()
        excluded_users = {"gabriel-h"}

        parsed_scenes = []
        for file_path, show, _seq, _shot, _user in created_files:
            show_path = shows_root / show
            result = parser.parse_3de_file_path(
                file_path, show_path, show, excluded_users
            )
            if result:
                parsed_scenes.append(result)

        # Should parse all scenes except gabriel-h's (2 files)
        assert len(parsed_scenes) == 8, (
            f"Should parse 8 scenes, got {len(parsed_scenes)}"
        )

        # Verify excluded user's files were filtered
        for parsed in parsed_scenes:
            _, _, _, _, user, _ = parsed
            assert user != "gabriel-h", "gabriel-h should be filtered out"

    def test_end_to_end_with_filesystem_scanner(self, temp_vfx_structure) -> None:
        """Test complete end-to-end with FileSystemScanner."""
        # Local application imports
        from threede.filesystem_scanner import (
            FileSystemScanner,
        )

        shows_root, _created_files = temp_vfx_structure
        scanner = FileSystemScanner()
        excluded_users = {"gabriel-h"}

        all_results = []
        for show in ["gator", "jack_ryan", "broken_eggs"]:
            results = scanner.find_all_3de_files_in_show_targeted(
                str(shows_root), show, excluded_users
            )
            all_results.extend(results)

        # Should find files from all users except gabriel-h
        assert len(all_results) > 0, "Should find some 3DE files"

        # Verify structure of results
        for result in all_results:
            file_path, show, _sequence, _shot, user, _plate = result
            assert user != "gabriel-h", "Excluded user should be filtered"
            assert file_path.exists(), "File path should exist"

    @pytest.mark.parametrize(
        ("show", "expected_min_scenes"),
        [
            ("gator", 2),  # sarah-b and tony-a
            ("jack_ryan", 3),  # tony-a, ryan-p (2 shots), published-mm
            ("broken_eggs", 2),  # alex-k and mike-d
        ],
    )
    def test_per_show_discovery(
        self, temp_vfx_structure, make_user_shots, show, expected_min_scenes
    ) -> None:
        """Test discovery for individual shows (GUIDE line 143 - parametrization)."""
        shows_root, _ = temp_vfx_structure
        user_shots = [s for s in make_user_shots() if s.show == show]

        if not user_shots:
            # Create a dummy shot for shows user isn't assigned to
            # Standard library imports
            from collections import (
                namedtuple,
            )

            Shot = namedtuple("Shot", ["workspace_path", "show", "sequence", "shot"])
            user_shots = [
                Shot(f"{shows_root}/{show}/shots/dummy/dummy_001", show, "dummy", "001")
            ]

        # Local application imports
        from config import (
            Config,
        )
        from threede.scene_discovery_coordinator import (
            SceneDiscoveryCoordinator,
        )

        with patch.object(Config, "SHOWS_ROOT", str(shows_root)):
            scenes = SceneDiscoveryCoordinator.find_all_scenes_in_shows(
                user_shots,
                {"gabriel-h"},
                progress_callback=None,
                cancel_flag=lambda: False,
            )

        show_scenes = [s for s in scenes if s.show == show]
        assert len(show_scenes) >= expected_min_scenes, (
            f"Show {show} should have at least {expected_min_scenes} scenes, "
            f"found {len(show_scenes)}"
        )
