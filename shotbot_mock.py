#!/usr/bin/env python3
"""ShotBot launcher with EARLY mock injection for development/testing.

This launcher ensures mock ProcessPoolManager is injected BEFORE any imports
that might create singleton instances using the new dependency injection system.
It also detects and uses recreated VFX filesystem if available.
"""

# Standard library imports
import logging
import os
import sys


# CRITICAL: Set mock mode FIRST
os.environ["SHOTBOT_MOCK"] = "1"
_ = os.environ.setdefault("SHOTBOT_MODE", "mock")

# CRITICAL: Set SHOWS_ROOT immediately to ensure Config uses mock path
# This MUST happen before ANY module imports that might load Config
# Respect SHOWS_ROOT if already set (e.g., by run_mock_vfx_env.py)
if "SHOWS_ROOT" not in os.environ:
    # Default to the shows directory within mock VFX structure for consistent paths
    os.environ["SHOWS_ROOT"] = "/tmp/mock_vfx/shows"

# Set up logging immediately
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

logger.info("🚀 Starting ShotBot in MOCK MODE")

# Standard library imports
# Check for recreated VFX structure
from pathlib import Path


MOCK_VFX_PATHS = [
    Path("/tmp/mock_vfx/shows"),
    Path("/tmp/shows"),  # Symlink
    Path.home() / "mock_vfx" / "shows",
]

mock_filesystem_found = False
for mock_path in MOCK_VFX_PATHS:
    if mock_path.exists():
        # Found mock filesystem - just report it (don't override SHOWS_ROOT if already set correctly)
        logger.info(f"🎬 Using mock VFX filesystem at: {mock_path}")
        logger.info(f"   SHOWS_ROOT is: {os.environ.get('SHOWS_ROOT', 'NOT SET')}")
        mock_filesystem_found = True

        # Also check if we have the marker file
        marker = mock_path.parent / "MOCK_VFX_ENVIRONMENT.txt"
        if marker.exists():
            logger.info("   ✅ Valid mock environment detected")
        break

if not mock_filesystem_found:
    # SHOWS_ROOT should already be set correctly by earlier logic
    logger.info(
        "No mock filesystem found. Run tests/recreate_vfx_structure.py to create one."
    )
    logger.info("   The app will work but paths won't exist.")
    logger.info(f"   SHOWS_ROOT is: {os.environ.get('SHOWS_ROOT', 'NOT SET')}")

# NOW we can import the rest of the app
# No need for factory - SHOTBOT_MOCK env var already set above
logger.info("Loading ShotBot application...")

# Local application imports
# Import the original main function
from shotbot import main


# Run the original main but skip the mock injection part
# (since we already did it properly)
if __name__ == "__main__":
    # The main() in shotbot.py will still parse args and check for --mock,
    # but our early injection ensures it works properly

    # For WSL compatibility, set some defaults
    if "WSL" in os.uname().release or "Microsoft" in os.uname().release:
        logger.info("🖥️  WSL detected - using compatibility settings")
        # Use xcb platform for WSL
        _ = os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
        # Ensure display is set
        _ = os.environ.setdefault("DISPLAY", ":0")

    try:
        main()
    except Exception:
        logger.exception("❌ Error running ShotBot")
        # Standard library imports
        import traceback

        traceback.print_exc()
        sys.exit(1)
