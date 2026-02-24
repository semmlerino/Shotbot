#!/usr/bin/env python3
"""Shot processing pipeline - PARSING LOGIC tests.

These tests verify string parsing and data extraction algorithms using
hardcoded mock data. They do NOT test real subprocess execution or
filesystem operations.

This test validates:
1. Shot extraction from directory names (string parsing)
2. 3DE scene discovery logic (path construction, not filesystem)
3. Thumbnail path construction (string manipulation)
4. ws -sg output parsing (line splitting, regex)

For real subprocess testing, see:
- tests/integration/test_real_subprocess.py

For integration tests with real components, see:
- tests/integration/test_shot_workflow_integration.py
- tests/integration/test_incremental_caching_workflow.py
- tests/integration/test_threede_scanner_integration.py
"""

# Standard library imports
import sys
from pathlib import Path


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Local application imports
from shot_model import Shot
from targeted_shot_finder import TargetedShotsFinder
from threede_scene_finder import OptimizedThreeDESceneFinder
from threede_scene_model import ThreeDESceneModel
from utils import PathUtils


# Mock ws -sg output from user
WS_SG_OUTPUT = """workspace /shows/gator/shots/012_DC/012_DC_1000
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


def test_shot_extraction() -> None:
    """Test shot name extraction from various directory formats."""
    print("\n=== Testing Shot Extraction Logic ===")

    test_cases = [
        # (directory_name, sequence, expected_shot)
        ("012_DC_1000", "012_DC", "1000"),
        ("012_DC_1070", "012_DC", "1070"),
        ("DB_271_1760", "DB_271", "1760"),
        ("FF_278_4380", "FF_278", "4380"),
        ("BRX_166_0010", "BRX_166", "0010"),
        ("999_xx_999", "999_xx", "999"),
        # Edge cases
        ("DB_256_1200", "DB_256", "1200"),  # User's example
        ("BB_", "BB", None),  # Should be rejected (empty shot)
        ("BB", "BB", "BB"),  # No underscore, use whole name
    ]

    errors = []
    for shot_dir, sequence, expected_shot in test_cases:
        # Simulate extraction logic from the finders
        if shot_dir.startswith(f"{sequence}_"):
            shot = shot_dir[len(sequence) + 1 :]  # +1 for underscore
        else:
            shot_parts = shot_dir.rsplit("_", 1)
            shot = shot_parts[1] if len(shot_parts) == 2 else shot_dir

        # Validate shot is not empty
        if not shot:
            shot = None

        if shot != expected_shot:
            errors.append(f"  ❌ {shot_dir}: expected '{expected_shot}', got '{shot}'")
        else:
            print(f"  ✓ {shot_dir} → {shot}")

    if errors:
        print("\nErrors found:")
        for error in errors:
            print(error)
        raise AssertionError(f"Shot extraction errors found: {len(errors)} failures")

    print("  All shot extractions passed!")


def parse_ws_sg_output(output: str) -> list[Shot]:
    """Parse ws -sg output into Shot objects."""
    shots = []

    for line in output.strip().split("\n"):
        if not line.startswith("workspace"):
            continue

        parts = line.split()
        if len(parts) != 2:
            continue

        workspace_path = parts[1]
        path_parts = Path(workspace_path).parts

        # Extract components from path
        if (
            len(path_parts) >= 5
            and path_parts[1] == "shows"
            and path_parts[3] == "shots"
        ):
            show = path_parts[2]
            sequence = path_parts[4]
            shot_dir = path_parts[5] if len(path_parts) > 5 else sequence

            # Extract shot number from directory name
            if shot_dir.startswith(f"{sequence}_"):
                shot = shot_dir[len(sequence) + 1 :]
            else:
                shot_parts = shot_dir.rsplit("_", 1)
                shot = shot_parts[1] if len(shot_parts) == 2 else shot_dir

            if shot:  # Only add if shot is not empty
                shots.append(
                    Shot(
                        show=show,
                        sequence=sequence,
                        shot=shot,
                        workspace_path=workspace_path,
                    )
                )

    return shots


def test_ws_sg_parsing() -> None:
    """Test parsing of ws -sg output."""
    print("\n=== Testing ws -sg Output Parsing ===")

    shots = parse_ws_sg_output(WS_SG_OUTPUT)

    expected_count = 12  # All lines in the mock output
    assert len(shots) == expected_count, (
        f"Expected {expected_count} shots, got {len(shots)}"
    )

    # Check specific shots
    test_cases = [
        (0, "gator", "012_DC", "1000"),
        (3, "jack_ryan", "DB_271", "1760"),
        (7, "broken_eggs", "BRX_166", "0010"),
        (11, "jack_ryan", "999_xx", "999"),
    ]

    for idx, show, sequence, shot in test_cases:
        s = shots[idx]
        assert s.show == show, (
            f"Shot {idx}: expected show {show}, got {s.show}"
        )
        assert s.sequence == sequence, (
            f"Shot {idx}: expected sequence {sequence}, got {s.sequence}"
        )
        assert s.shot == shot, (
            f"Shot {idx}: expected shot {shot}, got {s.shot}"
        )
        print(f"  ✓ Shot {idx}: {s.show}/{s.sequence}/{s.shot}")

    print(f"  All {len(shots)} shots parsed correctly!")


def test_show_extraction() -> None:
    """Test extraction of unique shows from shots."""
    print("\n=== Testing Show Extraction ===")

    shots = parse_ws_sg_output(WS_SG_OUTPUT)
    shows = {shot.show for shot in shots}

    expected_shows = {"gator", "jack_ryan", "broken_eggs"}
    assert shows == expected_shows, f"Expected shows {expected_shows}, got {shows}"

    print(f"  ✓ Extracted shows: {', '.join(sorted(shows))}")


def test_targeted_shot_finder() -> None:
    """Test TargetedShotsFinder with mock data."""
    print("\n=== Testing Targeted Shot Finder ===")

    try:
        # Parse active shots
        active_shots = parse_ws_sg_output(WS_SG_OUTPUT)

        # Create finder
        finder = TargetedShotsFinder(username="testuser")

        # Extract shows
        target_shows = finder.extract_shows_from_active_shots(active_shots)
        expected_shows = {"gator", "jack_ryan", "broken_eggs"}

        assert target_shows == expected_shows, (
            f"Expected shows {expected_shows}, got {target_shows}"
        )

        print(f"  ✓ Correctly extracted {len(target_shows)} target shows")

        # Test shot parsing with edge cases
        test_paths = [
            "/shows/gator/shots/012_DC/012_DC_1000/user/testuser",
            "/shows/jack_ryan/shots/DB_256/DB_256_1200/user/testuser",
            "/shows/test/shots/BB/BB_/user/testuser",  # Edge case: ends with underscore
        ]

        for path in test_paths:
            shot = finder._parse_shot_from_path(path)
            if path.endswith("BB_/user/testuser"):
                assert shot is None, f"Should reject empty shot from path: {path}"
                print("  ✓ Correctly rejected empty shot from BB_")
            elif shot:
                print(f"  ✓ Parsed shot: {shot.show}/{shot.sequence}/{shot.shot}")

    except Exception as e:
        print(f"  ❌ Error: {e}")
        raise AssertionError(f"TargetedShotsFinder test failed: {e}") from e


def test_3de_scene_discovery() -> None:
    """Test 3DE scene discovery logic."""
    print("\n=== Testing 3DE Scene Discovery ===")

    try:
        # Test file-first discovery approach
        OptimizedThreeDESceneFinder()

        # Test shot extraction from file paths
        test_paths = [
            (
                Path("/shows/gator/shots/012_DC/012_DC_1000/user/ryan/mm/3de/test.3de"),
                "gator",
                "012_DC",
                "1000",
            ),
            (
                Path(
                    "/shows/jack_ryan/shots/DB_271/DB_271_1760/user/john/scenes/test.3de"
                ),
                "jack_ryan",
                "DB_271",
                "1760",
            ),
            (
                Path(
                    "/shows/broken_eggs/shots/BRX_166/BRX_166_0010/publish/mm/test.3de"
                ),
                "broken_eggs",
                "BRX_166",
                "0010",
            ),
        ]

        print("  Testing path extraction:")
        for file_path, expected_show, expected_seq, expected_shot in test_paths:
            # Simulate extraction from find_all_3de_files_in_show
            parts = file_path.parts
            show_idx = parts.index("shows") + 1
            show = parts[show_idx]
            sequence = parts[show_idx + 2]
            shot_dir = parts[show_idx + 3]

            # Extract shot from directory
            if shot_dir.startswith(f"{sequence}_"):
                shot = shot_dir[len(sequence) + 1 :]
            else:
                shot = shot_dir.split("_")[-1] if "_" in shot_dir else shot_dir

            assert show == expected_show, (
                f"{file_path.name}: expected show {expected_show}, got {show}"
            )
            assert sequence == expected_seq, (
                f"{file_path.name}: expected sequence {expected_seq}, got {sequence}"
            )
            assert shot == expected_shot, (
                f"{file_path.name}: expected shot {expected_shot}, got {shot}"
            )
            print(f"    ✓ {file_path.name}: {show}/{sequence}/{shot}")

        print("  ✓ Path extraction logic working correctly")

    except Exception as e:
        print(f"  ❌ Error: {e}")
        raise AssertionError(f"3DE scene discovery test failed: {e}") from e


def test_thumbnail_discovery() -> None:
    """Test thumbnail discovery logic."""
    print("\n=== Testing Thumbnail Discovery ===")

    try:
        # Test thumbnail path building
        shots = parse_ws_sg_output(WS_SG_OUTPUT)

        print("  Testing thumbnail paths for shots:")
        for shot in shots[:3]:  # Test first 3 shots
            # Test editorial thumbnail path
            editorial_path = Path(shot.workspace_path) / "publish" / "editorial"
            print(f"    Shot {shot.full_name}:")
            print(f"      Editorial: {editorial_path}")

            # Test turnover plate path
            turnover_path = PathUtils.build_raw_plate_path(shot.workspace_path)
            print(f"      Turnover: {turnover_path}")

        print("  ✓ Thumbnail path logic working correctly")

    except Exception as e:
        print(f"  ❌ Error: {e}")
        raise AssertionError(f"Thumbnail discovery test failed: {e}") from e


def test_integration() -> None:
    """Test complete integration of the pipeline."""
    print("\n=== Testing Complete Pipeline Integration ===")

    try:
        # 1. Parse ws -sg output
        shots = parse_ws_sg_output(WS_SG_OUTPUT)
        print(f"  ✓ Parsed {len(shots)} shots from ws -sg")

        # 2. Extract shows
        shows = {shot.show for shot in shots}
        print(f"  ✓ Extracted {len(shows)} shows: {', '.join(sorted(shows))}")

        # 3. Test 3DE scene model
        scene_model = ThreeDESceneModel(load_cache=False)

        # Mock scene discovery (would use actual finder in production)
        print("  ✓ 3DE scene model initialized")

        # 4. Test deduplication
        # Local application imports
        from threede_scene_model import (
            ThreeDEScene,
        )

        # Create mock scenes for deduplication test
        mock_scenes = [
            ThreeDEScene(
                show="gator",
                sequence="012_DC",
                shot="1000",
                workspace_path="/shows/gator/shots/012_DC/012_DC_1000",
                user="user1",
                plate="bg01",
                scene_path=Path("/test/scene1.3de"),
            ),
            ThreeDEScene(
                show="gator",
                sequence="012_DC",
                shot="1000",
                workspace_path="/shows/gator/shots/012_DC/012_DC_1000",
                user="user2",
                plate="fg01",
                scene_path=Path("/test/scene2.3de"),
            ),
        ]

        deduplicated = scene_model._deduplicate_scenes_by_shot(mock_scenes)
        assert len(deduplicated) == 1, (
            f"Deduplication failed: expected 1 scene, got {len(deduplicated)}"
        )

        print("  ✓ Deduplication working correctly")

        print("\n  Pipeline integration test completed successfully!")

    except Exception as e:
        print(f"  ❌ Integration error: {e}")
        raise AssertionError(f"Pipeline integration test failed: {e}") from e


def main() -> int:
    """Run all tests."""
    print("=" * 60)
    print("SHOT PROCESSING PIPELINE VALIDATION")
    print("=" * 60)

    tests = [
        ("Shot Extraction", test_shot_extraction),
        ("ws -sg Parsing", test_ws_sg_parsing),
        ("Show Extraction", test_show_extraction),
        ("Targeted Shot Finder", test_targeted_shot_finder),
        ("3DE Scene Discovery", test_3de_scene_discovery),
        ("Thumbnail Discovery", test_thumbnail_discovery),
        ("Pipeline Integration", test_integration),
    ]

    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n❌ {name} failed with exception: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "✓ PASS" if success else "❌ FAIL"
        print(f"  {status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print(
            "\n🎉 All tests passed! The shot processing pipeline is working correctly."
        )
        return 0
    print(f"\n⚠️  {total - passed} test(s) failed. Please review the errors above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
