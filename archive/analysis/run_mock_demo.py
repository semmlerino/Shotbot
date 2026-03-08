#!/usr/bin/env python3
"""Interactive demo script for ShotBot mock mode.

This script demonstrates that ShotBot can run without VFX infrastructure.
"""

# Standard library imports
import json
import sys
from pathlib import Path
from typing import TypedDict, cast


class ShotData(TypedDict):
    """Type definition for shot data from JSON."""

    show: str
    seq: str
    shot: str


class DemoData(TypedDict):
    """Type definition for demo_shots.json structure."""

    shots: list[ShotData]


def test_mock_environment() -> bool:
    """Test that mock environment is working."""
    print("=" * 60)
    print("SHOTBOT MOCK MODE DEMONSTRATION")
    print("=" * 60)
    print()

    # 1. Show that mock data is loaded
    demo_shots_path = Path("demo_shots.json")
    with demo_shots_path.open() as f:
        data: DemoData = cast("DemoData", json.load(f))
        shots: list[ShotData] = data["shots"]

    print("✅ Mock Environment Ready!")
    print()
    print(f"📁 Loaded {len(shots)} demo shots from {demo_shots_path.name}:")

    # Group shots by show
    by_show: dict[str, list[str]] = {}
    for shot in shots:
        show: str = shot["show"]
        if show not in by_show:
            by_show[show] = []
        by_show[show].append(f"{shot['seq']}_{shot['shot']}")

    for show in sorted(by_show.keys()):
        print(f"\n  🎬 {show}:")
        for shot_name in by_show[show][:3]:  # Show first 3
            print(f"     - {shot_name}")
        if len(by_show[show]) > 3:
            print(f"     ... and {len(by_show[show]) - 3} more")

    print()
    print("🚀 Mock mode provides:")
    print("   ✓ No 'ws' command required")
    print("   ✓ No VFX filesystem needed")
    print("   ✓ Instant startup (no 2.4s delay)")
    print("   ✓ Works offline")
    print()
    print("📝 To run ShotBot with GUI:")
    print("   uv run python shotbot.py --mock")
    print()
    print("   or set environment variable:")
    print("   SHOTBOT_MOCK=1 uv run python shotbot.py")
    print()

    # 2. Test that the ProcessPoolManager can be mocked
    print("🧪 Testing mock ProcessPoolManager...")

    # Import and mock the ProcessPoolManager
    # Local application imports
    from tests.test_doubles_library import (
        TestProcessPool,
    )

    mock_pool = TestProcessPool()

    # Set up with our demo shots
    outputs: list[str] = [
        f"workspace /shows/{shot['show']}/shots/{shot['seq']}/{shot['seq']}_{shot['shot']}"
        for shot in shots
    ]

    mock_pool.set_outputs(*outputs)

    # Test executing ws -sg
    result = mock_pool.execute_workspace_command("ws -sg")
    lines = result.strip().split("\n")

    print(f"✅ Mock 'ws -sg' returns {len(lines)} shots")
    print(f"   First shot: {lines[0]}")

    print()
    print("=" * 60)
    print("✨ ShotBot is ready to run in mock mode!")
    print("=" * 60)

    return True


if __name__ == "__main__":
    try:
        # Check if PySide6 is available
        try:
            # Third-party imports
            import PySide6

            print(f"✅ PySide6 {PySide6.__version__} is installed")
        except ImportError:
            print("⚠️  PySide6 not found - GUI won't work, but mock mode is configured")
            print("   Install with: pip install PySide6")
        print()

        success = test_mock_environment()

        if success:
            print("\n👉 Ready to run: uv run python shotbot.py --mock")

        sys.exit(0 if success else 1)

    except Exception as e:  # noqa: BLE001
        print(f"❌ Error: {e}")
        # Standard library imports
        import traceback

        traceback.print_exc()
        sys.exit(1)
