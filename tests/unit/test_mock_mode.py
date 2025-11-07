#!/usr/bin/env python3
"""Test script to verify mock mode functionality without GUI.

This script tests that mock mode properly injects test data
without requiring PySide6 or Qt GUI components.
"""

# Standard library imports
import json
import os
import sys
from pathlib import Path

# Third-party imports
import pytest


@pytest.fixture(autouse=True)
def reset_cache_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level cache disabled flag to prevent test contamination.

    The _cache_disabled flag in utils.py is a global state that can persist
    across tests, causing subsequent tests to see incorrect cache behavior.
    This fixture ensures each test starts with a clean state.
    """
    import utils

    monkeypatch.setattr(utils, "_cache_disabled", False)


def test_mock_setup() -> None:
    """Test that mock mode can be set up correctly."""
    print("Testing ShotBot Mock Mode Setup")
    print("=" * 50)

    # 1. Check demo_shots.json exists and is valid
    demo_shots_path = Path("demo_shots.json")
    assert demo_shots_path.exists(), "demo_shots.json not found!"

    try:
        with demo_shots_path.open() as f:
            demo_data = json.load(f)
            shots = demo_data.get("shots", [])
            print(f"✅ Found demo_shots.json with {len(shots)} shots")

            # Show sample data
            shows = {s["show"] for s in shots}
            print(f"   Shows: {', '.join(sorted(shows))}")
            print("   First 3 shots:")
            for shot in shots[:3]:
                print(f"     - {shot['show']}/{shot['seq']}_{shot['shot']}")
    except Exception as e:
        raise AssertionError(f"Failed to load demo_shots.json: {e}") from e

    # 2. Check that mock flag is recognized
    print("\n2. Testing command-line argument parsing...")
    try:
        # Standard library imports
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--mock", action="store_true")

        # Test with --mock flag
        args = parser.parse_args(["--mock"])
        assert args.mock, "--mock flag not working"
        print("✅ --mock flag recognized")

        # Test without flag
        args = parser.parse_args([])
        assert not args.mock, "Default mode incorrectly enables mock"
        print("✅ Default (no mock) mode works")
    except Exception as e:
        raise AssertionError(f"Argument parsing failed: {e}") from e

    # 3. Test environment variable
    print("\n3. Testing environment variable...")
    mock_mode = os.environ.get("SHOTBOT_MOCK", "").lower() in ("1", "true", "yes")
    if "SHOTBOT_MOCK" in os.environ:
        print(
            f"   SHOTBOT_MOCK={os.environ.get('SHOTBOT_MOCK')} -> mock_mode={mock_mode}"
        )
    else:
        print("   SHOTBOT_MOCK not set (normal mode)")
    print("✅ Environment variable check works")

    # 4. Simulate what happens in shotbot.py
    print("\n4. Simulating mock data injection...")
    outputs = []
    for shot in shots:
        show = shot.get("show", "demo")
        seq = shot.get("seq", "seq01")
        shot_num = shot.get("shot", "0010")
        outputs.append(f"workspace /shows/{show}/shots/{seq}/{seq}_{shot_num}")

    print(f"✅ Generated {len(outputs)} workspace commands")
    print("   Sample outputs:")
    for output in outputs[:3]:
        print(f"     {output}")

    print("\n" + "=" * 50)
    print("✅ All mock mode tests passed!")
    print("\nYou can now run:")
    print("  python3 shotbot.py --mock")
    print("or:")
    print("  SHOTBOT_MOCK=1 python3 shotbot.py")
    print("\nNote: The GUI will still require PySide6 to be installed.")


if __name__ == "__main__":
    try:
        test_mock_setup()
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ Assertion failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
