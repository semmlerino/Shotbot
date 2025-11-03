#!/usr/bin/env python3
"""Run ShotBot with mock VFX environment, simulating remote workstation.

This script sets up the environment to closely resemble the VFX workstation
by properly mapping paths and using the recreated filesystem structure.
"""

# Standard library imports
import logging
import os
import subprocess
import sys
from pathlib import Path


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(message)s", datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


def setup_mock_vfx_environment() -> bool:
    """Set up environment to simulate VFX workstation."""

    # Check for mock filesystem
    mock_vfx_root = Path("/tmp/mock_vfx")
    if not mock_vfx_root.exists():
        logger.warning("Mock VFX filesystem not found at /tmp/mock_vfx")
        logger.info("🔄 Creating mock VFX environment automatically...")

        # Try to create it automatically
        try:
            structure_file = Path(__file__).parent / "vfx_structure_complete.json"
            if structure_file.exists():
                result = subprocess.run(
                    [
                        sys.executable,
                        "recreate_vfx_structure.py",
                        "vfx_structure_complete.json",
                    ],
                    check=False, cwd=Path(__file__).parent,
                    capture_output=True,
                    text=True,
                )

                if result.returncode == 0:
                    logger.info("✅ Mock VFX environment created successfully")
                else:
                    logger.error(
                        f"❌ Failed to create mock environment: {result.stderr}"
                    )
                    logger.info(
                        "Manual command: python recreate_vfx_structure.py vfx_structure_complete.json"
                    )
                    return False
            else:
                logger.error("❌ vfx_structure_complete.json not found")
                logger.info(
                    "Manual command: python recreate_vfx_structure.py vfx_structure_complete.json"
                )
                return False
        except Exception as e:
            logger.error(f"❌ Error creating mock environment: {e}")
            logger.info(
                "Manual command: python recreate_vfx_structure.py vfx_structure_complete.json"
            )
            return False

    # Check marker file
    marker_file = mock_vfx_root / "MOCK_VFX_ENVIRONMENT.txt"
    if marker_file.exists():
        logger.info(f"✅ Found mock VFX environment at {mock_vfx_root}")
        with marker_file.open() as f:
            for line in f:
                if "Capture host:" in line:
                    logger.info(f"   {line.strip()}")

    # List available shows
    shows_dir = mock_vfx_root / "shows"
    if shows_dir.exists():
        shows = [d.name for d in shows_dir.iterdir() if d.is_dir()]
        logger.info(f"   Available shows: {', '.join(shows)}")

    # Set environment variables
    os.environ["SHOTBOT_MOCK"] = "1"
    os.environ["SHOWS_ROOT"] = str(mock_vfx_root / "shows")
    logger.info(f"✅ Set SHOWS_ROOT={mock_vfx_root / 'shows'}")

    # Check for display
    if os.environ.get("DISPLAY"):
        logger.info(f"✅ Display available: {os.environ['DISPLAY']}")
    else:
        logger.warning("⚠️  No DISPLAY set - UI may not be visible")

    # Check if WSL
    if "microsoft-standard" in os.uname().release.lower():
        logger.info("🖥️  Running in WSL environment")
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    return True


def create_shows_symlink() -> bool:
    """Create /shows symlink for path compatibility."""

    # Try different approaches
    symlink_created = False

    # Option 1: Try /shows directly (may need sudo)
    try:
        shows_link = Path("/shows")
        if not shows_link.exists():
            shows_link.symlink_to("/tmp/mock_vfx/shows")
            logger.info("✅ Created symlink: /shows -> /tmp/mock_vfx/shows")
            symlink_created = True
        elif shows_link.is_symlink():
            logger.info(f"✅ Symlink exists: /shows -> {shows_link.resolve()}")
            symlink_created = True
    except PermissionError:
        logger.debug("Cannot create /shows symlink (permission denied)")

    # Option 2: Update demo_shots.json to use /tmp/mock_vfx paths
    if not symlink_created:
        logger.info("Updating paths for mock environment...")
        demo_shots_file = Path(__file__).parent / "demo_shots.json"
        if demo_shots_file.exists():
            # Standard library imports
            import json

            with demo_shots_file.open() as f:
                demo_data = json.load(f)

            # Update paths to use /tmp/mock_vfx
            updated = False
            for shot in demo_data.get("shots", []):
                if "path" in shot and shot["path"].startswith("/shows/"):
                    shot["path"] = shot["path"].replace(
                        "/shows/", "/tmp/mock_vfx/shows/"
                    )
                    updated = True

            if updated:
                # Save to temporary file
                temp_demo = Path("/tmp/demo_shots_mock.json")
                with temp_demo.open("w") as f:
                    json.dump(demo_data, f, indent=2)
                logger.info(f"✅ Created temporary demo shots: {temp_demo}")

                # Copy to replace original temporarily
                os.system(f"cp {temp_demo} {demo_shots_file}")

    return True


def run_shotbot() -> int:
    """Run ShotBot with mock environment."""

    # Python executable from venv
    python_exe = Path(__file__).parent / "venv" / "bin" / "python"
    if not python_exe.exists():
        python_exe = sys.executable

    # Build command
    cmd = [str(python_exe), "shotbot_mock.py"]

    logger.info("🚀 Launching ShotBot in mock VFX environment...")
    logger.info(f"   Command: {' '.join(cmd)}")

    # Run ShotBot
    try:
        result = subprocess.run(
            cmd,
            check=False, cwd=Path(__file__).parent,
            env=os.environ,
            text=True,
            capture_output=False,  # Let output go to terminal
        )

        if result.returncode == 0:
            logger.info("✅ ShotBot exited successfully")
        else:
            logger.error(f"❌ ShotBot exited with code {result.returncode}")

        return result.returncode

    except KeyboardInterrupt:
        logger.info("\n⚠️  ShotBot interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"❌ Failed to run ShotBot: {e}")
        return 1


def main() -> int:
    """Main entry point."""

    logger.info("=" * 60)
    logger.info("ShotBot Mock VFX Environment Launcher")
    logger.info("=" * 60)

    # Set up environment
    if not setup_mock_vfx_environment():
        return 1

    # Create symlinks/update paths
    if not create_shows_symlink():
        logger.warning(
            "⚠️  Could not create /shows symlink, paths may not work correctly"
        )

    # Run ShotBot
    return run_shotbot()


if __name__ == "__main__":
    sys.exit(main())
