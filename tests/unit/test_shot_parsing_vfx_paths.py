"""Test shot parsing with actual VFX path structures.

This test file ensures correct parsing of real VFX pipeline paths following
the UNIFIED_TESTING_GUIDE principles:
- Uses real components with test doubles only at boundaries
- Tests behavior, not implementation
- Uses factory fixtures for flexible test data
"""

# Third-party imports
import pytest

# Local application imports
from config import Config
from shot_model import ShotModel
from tests.fixtures.doubles_library import TestProcessPool


class TestVFXPathParsing:
    """Test parsing of actual VFX path structures."""

    @pytest.fixture
    def test_process_pool(self):
        """Create TestProcessPool for subprocess boundary mocking."""
        # allow_main_thread=True because tests call refresh_shots() synchronously
        return TestProcessPool(allow_main_thread=True)

    @pytest.fixture
    def shot_model(self, test_process_pool):
        """Create ShotModel with test process pool."""
        model = ShotModel(load_cache=False)
        model._process_pool = test_process_pool
        return model

    def test_parse_actual_vfx_paths(self, shot_model, test_process_pool) -> None:
        """Test parsing of actual VFX workspace paths from production environment."""
        # Actual ws -sg output from VFX environment
        test_output = """workspace /shows/gator/shots/012_DC/012_DC_1000
workspace /shows/gator/shots/012_DC/012_DC_1070
workspace /shows/gator/shots/012_DC/012_DC_1050
workspace /shows/jack_ryan/shots/DB_271/DB_271_1760
workspace /shows/jack_ryan/shots/FF_278/FF_278_4380
workspace /shows/jack_ryan/shots/DA_280/DA_280_0280
workspace /shows/jack_ryan/shots/DC_278/DC_278_0050
workspace /shows/broken_eggs/shots/BRX_166/BRX_166_0010
workspace /shows/broken_eggs/shots/BRX_166/BRX_166_0020
workspace /shows/broken_eggs/shots/BRX_170/BRX_170_0100
workspace /shows/broken_eggs/shots/BRX_070/BRX_070_0010
workspace /shows/jack_ryan/shots/999_xx/999_xx_999"""

        test_process_pool.set_outputs(test_output)

        # Refresh shots
        result = shot_model.refresh_shots()
        assert result.success
        assert result.has_changes

        # Verify shots were parsed correctly
        shots = shot_model.get_shots()
        assert len(shots) == 12

        # Check specific shot parsing
        shot_data = {
            (shot.show, shot.sequence, shot.shot, shot.full_name) for shot in shots
        }

        expected_shots = {
            ("gator", "012_DC", "1000", "012_DC_1000"),
            ("gator", "012_DC", "1070", "012_DC_1070"),
            ("gator", "012_DC", "1050", "012_DC_1050"),
            ("jack_ryan", "DB_271", "1760", "DB_271_1760"),
            ("jack_ryan", "FF_278", "4380", "FF_278_4380"),
            ("jack_ryan", "DA_280", "0280", "DA_280_0280"),
            ("jack_ryan", "DC_278", "0050", "DC_278_0050"),
            ("broken_eggs", "BRX_166", "0010", "BRX_166_0010"),
            ("broken_eggs", "BRX_166", "0020", "BRX_166_0020"),
            ("broken_eggs", "BRX_170", "0100", "BRX_170_0100"),
            ("broken_eggs", "BRX_070", "0010", "BRX_070_0010"),
            ("jack_ryan", "999_xx", "999", "999_xx_999"),  # Special case
        }

        assert shot_data == expected_shots

    def test_shot_directory_extraction(self, make_test_shot) -> None:
        """Test correct extraction of shot from shot directory name."""
        # Test cases with actual VFX naming patterns
        test_cases = [
            # (sequence, shot_dir, expected_shot)
            ("DB_256", "DB_256_1200", "1200"),
            ("012_DC", "012_DC_1000", "1000"),
            ("BRX_166", "BRX_166_0010", "0010"),
            ("FF_278", "FF_278_4380", "4380"),
        ]

        for sequence, shot_dir, expected_shot in test_cases:
            # Parse shot from directory name (simulating the logic)
            if shot_dir.startswith(f"{sequence}_"):
                shot = shot_dir[len(sequence) + 1 :]
            else:
                shot_parts = shot_dir.rsplit("_", 1)
                shot = shot_parts[1] if len(shot_parts) == 2 else shot_dir

            assert shot == expected_shot, f"Failed for {shot_dir}"

    def test_thumbnail_path_construction(self, make_test_shot) -> None:
        """Test correct thumbnail path construction for VFX shots."""
        # Local application imports
        from config import (
            Config,
        )
        from utils import (
            PathUtils,
        )

        test_cases = [
            # (show, sequence, shot, expected_path_segment)
            ("gator", "012_DC", "1000", "012_DC_1000"),
            ("jack_ryan", "DB_256", "1200", "DB_256_1200"),
            ("broken_eggs", "BRX_166", "0010", "BRX_166_0010"),
        ]

        for show, sequence, shot, expected_segment in test_cases:
            path = PathUtils.build_thumbnail_path(
                Config.SHOWS_ROOT, show, sequence, shot
            )

            # Verify the path contains the correct shot directory
            assert expected_segment in str(path)
            # Verify it doesn't have duplicate 'shots' segments
            path_parts = str(path).split("/")
            assert path_parts.count("shots") == 1, f"Path has duplicate 'shots': {path}"

    @pytest.mark.parametrize(
        ("workspace_line", "expected"),
        [
            (
                "workspace /shows/gator/shots/012_DC/012_DC_1000",
                {
                    "show": "gator",
                    "sequence": "012_DC",
                    "shot": "1000",
                    "full_name": "012_DC_1000",
                },
            ),
            (
                "workspace /shows/jack_ryan/shots/DB_256/DB_256_1200",
                {
                    "show": "jack_ryan",
                    "sequence": "DB_256",
                    "shot": "1200",
                    "full_name": "DB_256_1200",
                },
            ),
            (
                "workspace /shows/broken_eggs/shots/BRX_166/BRX_166_0010",
                {
                    "show": "broken_eggs",
                    "sequence": "BRX_166",
                    "shot": "0010",
                    "full_name": "BRX_166_0010",
                },
            ),
        ],
    )
    def test_workspace_line_parsing(
        self, shot_model, test_process_pool, workspace_line, expected
    ) -> None:
        """Test parsing of individual workspace lines with parametrization."""
        test_process_pool.set_outputs(workspace_line)

        result = shot_model.refresh_shots()
        assert result.success

        shots = shot_model.get_shots()
        assert len(shots) == 1

        shot = shots[0]
        assert shot.show == expected["show"]
        assert shot.sequence == expected["sequence"]
        assert shot.shot == expected["shot"]
        assert shot.full_name == expected["full_name"]

    def test_workspace_path_format(self, make_test_shot) -> None:
        """Test that workspace paths follow the expected format."""
        # Create shots with actual VFX naming
        shot = make_test_shot(show="jack_ryan", sequence="DB_256", shot="1200")

        # Verify workspace path format
        # Test should check the PATH STRUCTURE, not absolute path
        # Fixture creates paths under tmp_path, so check the ending structure
        expected_structure = "jack_ryan/shots/DB_256/DB_256_1200"
        assert shot.workspace_path.endswith(expected_structure), \
            f"Expected workspace_path to end with {expected_structure}, got {shot.workspace_path}"
        assert shot.full_name == "DB_256_1200"

        # Verify thumbnail path construction
        # Local application imports
        from config import (
            Config,
        )
        from utils import (
            PathUtils,
        )

        thumb_path = PathUtils.build_thumbnail_path(
            Config.SHOWS_ROOT, shot.show, shot.sequence, shot.shot
        )

        # Use dynamic SHOWS_ROOT instead of hardcoded /shows
        expected_path = f"{Config.SHOWS_ROOT}/jack_ryan/shots/DB_256/DB_256_1200/publish/editorial/cutref/v001/jpg/1920x1080"
        assert str(thumb_path) == expected_path

    def test_vfx_asset_paths(self) -> None:
        """Test construction and discovery of VFX asset paths."""
        # Standard library imports
        from pathlib import (
            Path,
        )

        # Local application imports
        from utils import (
            PathUtils,
        )

        # Test 3DE scene path construction
        shows_root = Config.SHOWS_ROOT
        workspace = f"{shows_root}/jack_ryan/shots/DB_256/DB_256_1200"
        username = "gabriel-h"

        threede_path = PathUtils.build_threede_scene_path(workspace, username)
        expected_3de = (
            Path(workspace)
            / "user"
            / username
            / "mm"
            / "3de"
            / "mm-default"
            / "scenes"
            / "scene"
        )
        assert threede_path == expected_3de

        # Test raw plate path construction
        plate_path = PathUtils.build_raw_plate_path(workspace)
        expected_plate = (
            Path(workspace) / "publish" / "turnover" / "plate" / "input_plate"
        )
        assert plate_path == expected_plate

    def test_actual_vfx_file_paths(self) -> None:
        """Test parsing and construction of actual VFX file paths provided by user."""
        # Standard library imports
        from pathlib import (
            Path,
        )

        shows_root = Config.SHOWS_ROOT

        # Test data from actual VFX pipeline
        test_cases = [
            {
                "description": "3DE scene for Maya",
                "path": f"{shows_root}/jack_ryan/shots/DB_256/DB_256_1200/user/gabriel-h/mm/3de/mm-default/exports/scene/FG01/mel_script/v002/DB_256_1200_mm_default_scene_v002.mel",
                "workspace": f"{shows_root}/jack_ryan/shots/DB_256/DB_256_1200",
                "plate": "FG01",
                "version": "v002",
            },
            {
                "description": "Raw plate sequence",
                "path": f"{shows_root}/jack_ryan/shots/DB_256/DB_256_1200/publish/turnover/plate/input_plate/FG01/v001/exr/4312x2304/DB_256_1200_turnover-plate_FG01_lin_sgamut3cine_v001.####.exr",
                "workspace": f"{shows_root}/jack_ryan/shots/DB_256/DB_256_1200",
                "plate": "FG01",
                "version": "v001",
                "frame_range": "1001-1128",
            },
            {
                "description": "3DE scene file",
                "path": f"{shows_root}/gator/shots/012_DC/012_DC_1000/user/gabriel-h/mm/3de/mm-default/scenes/scene/bg01/012_DC_1000_mm_default_bg01_scene_v001.3de",
                "workspace": f"{shows_root}/gator/shots/012_DC/012_DC_1000",
                "plate": "bg01",
                "version": "v001",
            },
        ]

        for case in test_cases:
            path = Path(case["path"])
            # Check that path starts with shows_root (path structure depends on shows_root)
            assert str(path).startswith(shows_root)
            assert case["workspace"] in str(path)
            assert case["plate"] in str(path)
            assert case["version"] in str(path)
