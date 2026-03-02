"""RV plate viewer launcher.

Shared utility for opening plates in RV from shot grid, previous shots,
and 3DE grid views.
"""

from __future__ import annotations

import logging
import shlex
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
        # Use bash -ilc to inherit shell environment where Rez adds RV to PATH
        # RV settings: 12fps, auto-play, ping-pong mode (setPlayMode(2))
        safe_path = shlex.quote(plate_path)
        rv_cmd = f"rv {safe_path} -fps 12 -play -eval 'setPlayMode(2)'"
        _ = subprocess.Popen(["bash", "-ilc", rv_cmd])
    except FileNotFoundError:
        logger.error("RV not found. Please ensure RV is installed and in PATH.")
        notify_error("RV Not Found", "Could not launch RV. Check that RV is installed.")
    except Exception as e:
        logger.exception("Failed to open RV")
        notify_error("RV Launch Failed", f"Failed to open RV: {e}")
