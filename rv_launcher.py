"""RV plate viewer launcher.

Shared utility for opening plates in RV from shot grid, previous shots,
and 3DE grid views.
"""

from __future__ import annotations

import logging
import subprocess


logger = logging.getLogger(__name__)


def open_plate_in_rv(workspace_path: str) -> None:
    """Open the main plate for a workspace in RV.

    Finds the main plate at the given workspace path and launches RV with
    12fps playback in ping-pong mode.

    Args:
        workspace_path: Filesystem path to the shot workspace.

    """
    from notification_manager import error as notify_error
    from publish_plate_finder import find_main_plate

    plate_path = find_main_plate(workspace_path)

    if plate_path is None:
        logger.warning(f"No plate found for shot at {workspace_path}")
        notify_error("No Plate Found", f"No plate found for shot at {workspace_path}")
        return

    logger.info(f"Opening plate in RV: {plate_path}")
    try:
        from config import Config, RezMode
        from launch.environment_manager import EnvironmentManager

        launch_cmd = ["rv", plate_path, "-fps", "12", "-play", "-eval", "setPlayMode(2)"]

        if Config.REZ_MODE != RezMode.DISABLED:
            env_manager = EnvironmentManager()
            packages = env_manager.get_rez_packages("rv", Config)
            if not packages:
                notify_error(
                    "RV Launch Failed",
                    "RV Rez packages are not configured. Configure Config.REZ_RV_PACKAGES.",
                )
                return
            if not env_manager.should_wrap_with_rez(Config):
                notify_error(
                    "RV Launch Failed",
                    "Rez is required to launch RV, but the 'rez' command was not found on PATH.",
                )
                return
            launch_cmd = ["rez", "env", *packages, "--", *launch_cmd]

        _ = subprocess.Popen(launch_cmd)
    except FileNotFoundError:
        logger.error("RV not found. Please ensure RV is installed and in PATH.")
        notify_error("RV Not Found", "Could not launch RV. Check that RV is installed.")
    except Exception as e:
        logger.exception("Failed to open RV")
        notify_error("RV Launch Failed", f"Failed to open RV: {e}")
