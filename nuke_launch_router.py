"""Router that routes Nuke launches to the appropriate handler.

This module analyzes launch options and routes to the appropriate launcher:
- SimpleNukeLauncher: For opening/creating workspace scripts
- NukeLaunchHandler: For environment fixes and script generation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from logging_mixin import LoggingMixin
from nuke_launch_handler import NukeLaunchHandler
from simple_nuke_launcher import SimpleNukeLauncher


if TYPE_CHECKING:
    from shot_model import Shot


class NukeLaunchRouter(LoggingMixin):
    """Routes Nuke launches to simple or complex handler based on options."""

    def __init__(self) -> None:
        """Initialize with both launchers."""
        super().__init__()
        self.simple_launcher: SimpleNukeLauncher = SimpleNukeLauncher()
        self.complex_launcher: NukeLaunchHandler = NukeLaunchHandler()

        # Usage tracking for metrics
        self.simple_launches: int = 0
        self.complex_launches: int = 0

    def prepare_nuke_command(
        self,
        shot: Shot,
        base_command: str,
        options: dict[str, bool],
        selected_plate: str | None = None,
    ) -> tuple[str, list[str]]:
        """Route to appropriate launcher based on options.

        Decision logic:
        - With workspace options (open_latest_scene or create_new_file): Route to simple launcher
        - No options: Open empty Nuke

        Args:
            shot: Current shot context
            base_command: Base Nuke command
            options: Dictionary of launch options
            selected_plate: Selected plate space (e.g., "FG01", "BG01")

        Returns:
            Tuple of (command, log_messages)
        """
        # Extract options
        open_latest_scene = options.get("open_latest_scene", False)
        create_new_file = options.get("create_new_file", False)
        has_workspace_options = open_latest_scene or create_new_file

        if has_workspace_options:
            # Workspace workflow: open/create script
            return self._route_to_simple(
                shot=shot,
                base_command=base_command,
                selected_plate=selected_plate,
                open_latest=open_latest_scene,
                create_new=create_new_file,
            )

        # No options selected - just open empty Nuke
        self.simple_launches += 1
        self.logger.info("No options selected, opening empty Nuke")
        return base_command, ["Opening empty Nuke (no options selected)"]

    def _route_to_simple(
        self,
        shot: Shot,
        base_command: str,
        selected_plate: str | None,
        open_latest: bool,
        create_new: bool,
    ) -> tuple[str, list[str]]:
        """Route to simple launcher for basic open/create operations.

        Args:
            shot: Current shot context
            base_command: Base command (usually "nuke")
            selected_plate: Selected plate
            open_latest: Whether to open latest script
            create_new: Whether to create new version

        Returns:
            Tuple of (command, log_messages). Returns empty command ("") on error
            to prevent launch - caller should check for empty command.
        """
        if not selected_plate:
            log_messages = ["Error: No plate selected. Please select a plate space."]
            self.logger.error("No plate selected for simple workflow")
            # Return empty command to signal failure - prevents launching empty Nuke
            return "", log_messages

        self.simple_launches += 1
        self.logger.info(
            f"🚀 Using SIMPLE launcher for {shot.full_name} plate {selected_plate}"
        )
        self.logger.info(f"   open_latest={open_latest}, create_new={create_new}")

        if create_new:
            # Create new version takes priority
            return self.simple_launcher.create_new_version(shot, selected_plate)
        if open_latest:
            # Open latest (create v001 if missing)
            return self.simple_launcher.open_latest_script(
                shot, selected_plate, create_if_missing=True
            )
        # Shouldn't reach here, but handle gracefully
        return base_command, ["Opening empty Nuke"]

    def get_environment_fixes(self) -> str:
        """Get Nuke-specific environment fixes.

        Delegates to complex launcher which handles environment setup.

        Returns:
            String containing bash export statements for environment fixes
        """
        return self.complex_launcher.get_environment_fixes()

    def log_usage_stats(self) -> None:
        """Log usage statistics for simple vs complex workflows."""
        total = self.simple_launches + self.complex_launches
        if total == 0:
            return

        simple_pct = (self.simple_launches / total) * 100
        complex_pct = (self.complex_launches / total) * 100

        self.logger.info("=" * 60)
        self.logger.info("Nuke Launcher Usage Statistics")
        self.logger.info("=" * 60)
        self.logger.info(f"Simple workflow:  {self.simple_launches:3d} launches ({simple_pct:5.1f}%)")
        self.logger.info(f"Complex workflow: {self.complex_launches:3d} launches ({complex_pct:5.1f}%)")
        self.logger.info(f"Total launches:   {total:3d}")
        self.logger.info("=" * 60)
