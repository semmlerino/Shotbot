"""Unified Nuke launching handler using existing specialized modules."""

from __future__ import annotations

import logging
from pathlib import Path

from config import Config


logger = logging.getLogger(__name__)


class NukeLaunchHandler:
    """Handles all Nuke-specific launching logic.

    This class provides centralized Nuke launching functionality used by CommandLauncher.
    """

    def __init__(self) -> None:
        """Initialize with all required Nuke modules."""
        super().__init__()

    def get_environment_fixes(self) -> str:
        """Get Nuke-specific environment fixes.

        Returns:
            String containing bash export statements for environment fixes

        """
        if not Config.DCC.NUKE_FIX_OCIO_CRASH:
            return ""

        env_exports: list[str] = []

        # Skip problematic plugin paths by modifying NUKE_PATH at runtime
        if (
            Config.DCC.NUKE_SKIP_PROBLEMATIC_PLUGINS
            and Config.DCC.NUKE_PROBLEMATIC_PLUGIN_PATHS
        ):
            logger.info(
                f"Setting up runtime filter for {len(Config.DCC.NUKE_PROBLEMATIC_PLUGIN_PATHS)} problematic "
                f"plugin paths in NUKE_PATH"
            )

            # Build grep patterns for all problematic paths
            grep_patterns: list[str] = []
            for problematic_path in Config.DCC.NUKE_PROBLEMATIC_PLUGIN_PATHS:
                # Escape special characters for grep
                escaped_path = problematic_path.replace(".", r"\.")
                grep_patterns.append(f'-e "{escaped_path}"')

            grep_pattern_str = " ".join(grep_patterns)

            # Create a bash command that filters NUKE_PATH at runtime
            filter_command = (
                'FILTERED_NUKE_PATH=$(echo "$NUKE_PATH" | tr ":" "\\n" | '
                f'grep -v {grep_pattern_str} | tr "\\n" ":" | sed "s/:$//") && '
                'export NUKE_PATH="$FILTERED_NUKE_PATH"'
            )

            env_exports.append(filter_command)
            logger.debug(f"Generated runtime NUKE_PATH filter: {filter_command}")

        # Set fallback OCIO configuration if the default one might be problematic
        if Config.DCC.NUKE_OCIO_FALLBACK_CONFIG:
            # Check if a fallback config exists
            fallback_config = Config.DCC.NUKE_OCIO_FALLBACK_CONFIG
            if Path(fallback_config).exists():
                env_exports.append(f'export OCIO="{fallback_config}"')
                logger.info(f"Using fallback OCIO config: {fallback_config}")
            else:
                # Unset OCIO to use Nuke's built-in default
                env_exports.append("unset OCIO")
                logger.info("Unsetting OCIO to use Nuke's built-in configuration")

        # Additional stability environment variables
        env_exports.extend(
            [
                "export NUKE_DISABLE_CRASH_REPORTING=1",  # Disable crash reporting to avoid hang
                'export NUKE_TEMP_DIR="/tmp"',  # Ensure temp directory is accessible
                'export NUKE_DISK_CACHE="/tmp/nuke_cache"',  # Set disk cache location
                # Allow ShotGrid Toolkit to bootstrap - needed for colorspace hooks
            ]
        )

        if env_exports:
            env_string = " && ".join(env_exports)
            logger.debug(f"Generated Nuke environment fixes: {env_string}")
            return env_string + " && "

        return ""
