"""Build shell commands with environment configuration.

This module provides the EnvironmentCommandBuilder class which wraps
commands with environment settings from LauncherEnvironment config.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from launcher.models import LauncherEnvironment


class EnvironmentCommandBuilder:
    """Build shell commands with environment wrapping.

    Applies LauncherEnvironment settings in order:
    1. source_files - sourced before command
    2. command_prefix - prepended to command
    3. type="rez" - wrapped with rez env

    Example:
        >>> builder = EnvironmentCommandBuilder()
        >>> env = LauncherEnvironment(type="rez", packages=["nuke-16"])
        >>> builder.build_command("nuke", env)
        "rez env nuke-16 -- bash -ilc 'nuke'"
    """

    def build_command(
        self,
        base_command: str,
        environment: LauncherEnvironment,
    ) -> str:
        """Wrap command with environment configuration.

        Args:
            base_command: Original command to execute (after variable substitution)
            environment: LauncherEnvironment config with type, packages, etc.

        Returns:
            Shell command string with environment setup applied.
            If no environment settings, returns base_command unchanged.
        """
        # 1. Source files first (sets up environment variables)
        parts: list[str] = [
            f"source {shlex.quote(source_file)}"
            for source_file in environment.source_files
        ]

        # 2. Command prefix (e.g., "cd /workspace" or "export VAR=value")
        if environment.command_prefix:
            parts.append(environment.command_prefix)

        # 3. Build final command (with rez wrapping if needed)
        if environment.type == "rez" and environment.packages:
            packages_str = " ".join(environment.packages)
            quoted_cmd = shlex.quote(base_command)
            parts.append(f"rez env {packages_str} -- bash -ilc {quoted_cmd}")
        else:
            parts.append(base_command)

        return " && ".join(parts)
