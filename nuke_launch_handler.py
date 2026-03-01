"""Unified Nuke launching handler using existing specialized modules."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from config import Config
from logging_mixin import LoggingMixin
from nuke_script_generator import NukeScriptGenerator
from plate_discovery import PlateDiscovery


if TYPE_CHECKING:
    from shot_model import Shot


class NukeLaunchHandler(LoggingMixin):
    """Handles all Nuke-specific launching logic.

    This class provides centralized Nuke launching functionality used by CommandLauncher.
    """

    def __init__(self) -> None:
        """Initialize with all required Nuke modules."""
        super().__init__()
        # These are stored as classes since they use static methods
        self.script_generator: type[NukeScriptGenerator] = NukeScriptGenerator

    def prepare_nuke_command(
        self,
        shot: Shot,
        base_command: str,
        options: dict[str, bool],
        selected_plate: str | None = None,
    ) -> tuple[str, list[str]]:
        """Prepare Nuke command with all options.

        Args:
            shot: Current shot context
            base_command: Base Nuke command
            options: Dictionary of launch options:
                - open_latest_scene: Open latest existing script
                - create_new_file: Create new script version
            selected_plate: Selected plate space (e.g., "FG01", "BG01")

        Returns:
            Tuple of (command, log_messages)

        """
        log_messages: list[str] = []
        command = base_command

        # Validate plate selection for workspace operations
        if (options.get("open_latest_scene") or options.get("create_new_file")) and not selected_plate:
            log_messages.append("Error: No plate selected. Please select a plate space to continue.")
            return command, log_messages

        # Handle workspace script operations
        if options.get("open_latest_scene") or options.get("create_new_file"):
            command, msgs = self._handle_workspace_scripts(shot, command, options, selected_plate)
            log_messages.extend(msgs)

        # Apply environment fixes
        if Config.NUKE_FIX_OCIO_CRASH:
            log_messages.append(
                "Applying Nuke environment fixes to prevent OCIO plugin crashes..."
            )

        return command, log_messages

    def _handle_workspace_scripts(
        self,
        shot: Shot,
        command: str,
        options: dict[str, bool],
        selected_plate: str | None,
    ) -> tuple[str, list[str]]:
        """Handle workspace script creation/opening.

        Args:
            shot: Current shot context
            command: Current command string
            options: Launch options
            selected_plate: Selected plate space (e.g., "FG01")

        Returns:
            Tuple of (updated_command, log_messages)

        """
        log_messages: list[str] = []

        # Validate plate selection
        if not selected_plate:
            log_messages.append("Error: No plate selected")
            return command, log_messages

        # Note: open_latest_scene takes priority
        if options.get("open_latest_scene") and options.get("create_new_file"):
            options["create_new_file"] = False

        if options.get("open_latest_scene"):
            # Try to find existing script for selected plate
            existing_scripts = PlateDiscovery.find_existing_scripts(
                shot.workspace_path, shot.full_name, selected_plate
            )

            if existing_scripts:
                # Open latest script
                latest_script, latest_version = existing_scripts[-1]
                safe_script_path = shlex.quote(str(latest_script))
                command = f"{command} {safe_script_path}"
                log_messages.append(
                    f"Opening existing Nuke script: {latest_script.name} (v{latest_version:03d})"
                )
            else:
                # No existing script, create v001
                log_messages.append(
                    f"No existing scripts found for {selected_plate}, creating v001..."
                )
                saved_path = self._create_new_workspace_script(
                    shot, version=1, selected_plate=selected_plate
                )
                if saved_path:
                    command = f"{command} {shlex.quote(saved_path)}"
                    log_messages.append(
                        f"Created new Nuke script: {Path(saved_path).name}"
                    )
                else:
                    log_messages.append("Failed to create Nuke script")
                    return command, log_messages

        elif options.get("create_new_file"):
            # Get next version for selected plate
            version = PlateDiscovery.get_next_script_version(
                shot.workspace_path, shot.full_name, selected_plate
            )

            log_messages.append(
                f"Creating new Nuke script for {selected_plate}: v{version:03d}"
            )

            saved_path = self._create_new_workspace_script(
                shot, version=version, selected_plate=selected_plate
            )
            if saved_path:
                command = f"{command} {shlex.quote(saved_path)}"
                log_messages.append(
                    f"Created and opening new Nuke script: v{version:03d}"
                )
            else:
                log_messages.append("Failed to create Nuke script")

        return command, log_messages

    def _create_new_workspace_script(
        self,
        shot: Shot,
        version: int,
        selected_plate: str | None,
    ) -> str | None:
        """Create a new workspace script in plate directory.

        Args:
            shot: Current shot context
            version: Version number for the script
            selected_plate: Selected plate space (e.g., "FG01")

        Returns:
            Path to created script or None if failed

        """
        # Validate plate selection
        if not selected_plate:
            self.logger.error("No plate selected for Nuke script creation")
            return None

        # Create empty script directly in plate directory
        return self.script_generator.create_empty_plate_script(
            shot.workspace_path,
            shot.full_name,
            selected_plate,
            version=version,
        )

    def get_environment_fixes(self) -> str:
        """Get Nuke-specific environment fixes.

        Returns:
            String containing bash export statements for environment fixes

        """
        if not Config.NUKE_FIX_OCIO_CRASH:
            return ""

        env_exports: list[str] = []

        # Skip problematic plugin paths by modifying NUKE_PATH at runtime
        if (
            Config.NUKE_SKIP_PROBLEMATIC_PLUGINS
            and Config.NUKE_PROBLEMATIC_PLUGIN_PATHS
        ):
            self.logger.info(
                f"Setting up runtime filter for {len(Config.NUKE_PROBLEMATIC_PLUGIN_PATHS)} problematic "
                 f"plugin paths in NUKE_PATH"
            )

            # Build grep patterns for all problematic paths
            grep_patterns: list[str] = []
            for problematic_path in Config.NUKE_PROBLEMATIC_PLUGIN_PATHS:
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
            self.logger.debug(f"Generated runtime NUKE_PATH filter: {filter_command}")

        # Set fallback OCIO configuration if the default one might be problematic
        if Config.NUKE_OCIO_FALLBACK_CONFIG:
            # Check if a fallback config exists
            fallback_config = Config.NUKE_OCIO_FALLBACK_CONFIG
            if Path(fallback_config).exists():
                env_exports.append(f'export OCIO="{fallback_config}"')
                self.logger.info(f"Using fallback OCIO config: {fallback_config}")
            else:
                # Unset OCIO to use Nuke's built-in default
                env_exports.append("unset OCIO")
                self.logger.info("Unsetting OCIO to use Nuke's built-in configuration")

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
            self.logger.debug(f"Generated Nuke environment fixes: {env_string}")
            return env_string + " && "

        return ""
