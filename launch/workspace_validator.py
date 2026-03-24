"""Standalone workspace validation for pre-launch checks.

Extracted from :class:`launch.command_launcher.CommandLauncher` so that
workspace validation logic is reusable and independently testable.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path


logger = logging.getLogger(__name__)


def validate_workspace(workspace_path: str, app_name: str) -> str | None:
    """Validate workspace is accessible before launching an application.

    Performs pre-flight checks (advisory):
    1. Workspace directory exists
    2. Workspace path is a directory (not a file)
    3. User has read and execute permissions

    Note:
        Permission checks are advisory only due to TOCTOU (time-of-check to
        time-of-use) race conditions. Permissions could change between check
        and actual use. These checks provide early user feedback but don't
        guarantee success.

        Disk space is NOT checked - VFX production storage always has
        sufficient space, and the statvfs() call can block for 10+ seconds
        on slow NFS mounts, causing UI freezes.

    Args:
        workspace_path: Path to the workspace directory.
        app_name: Name of the application (for error messages).

    Returns:
        ``None`` if validation passes, or an error message string if it fails.
    """
    ws_path = Path(workspace_path)

    if not ws_path.exists():
        return f"Cannot launch {app_name}: Workspace path does not exist: {workspace_path}"

    if not ws_path.is_dir():
        return f"Cannot launch {app_name}: Workspace path is not a directory: {workspace_path}"

    if not os.access(workspace_path, os.R_OK | os.X_OK):
        return f"Cannot launch {app_name}: No read/execute permission for: {workspace_path}"

    return None
