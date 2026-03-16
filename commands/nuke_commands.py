"""Nuke command building utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from nuke_launch_handler import NukeLaunchHandler


def build_nuke_environment_prefix(nuke_env: NukeLaunchHandler, app_name: str) -> str:
    """Return the Nuke environment fix prefix string for use in launch commands.

    Args:
        nuke_env: NukeLaunchHandler instance providing environment fixes.
        app_name: The application name (only applies fixes if "nuke")

    Returns:
        Environment fix prefix string (empty if not Nuke or no fixes needed)

    """
    if app_name != "nuke":
        return ""

    env_fixes = nuke_env.get_environment_fixes()
    if not env_fixes:
        return ""

    return env_fixes
