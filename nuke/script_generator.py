"""Generate Nuke scripts with proper Read nodes for plates.

This module has been refactored to use separate modules for templates and detection
while maintaining backward compatibility.
"""

from __future__ import annotations

# Standard library imports
import atexit
import os
import tempfile
from pathlib import Path
from typing import ClassVar, final

# Local application imports
from config import Config
from logging_mixin import get_module_logger
from nuke.media_detector import NukeMediaDetector
from nuke.script_templates import NukeScriptTemplates
from plate_discovery import PlateDiscovery


# Module-level logger for static methods
logger = get_module_logger(__name__)


@final
class NukeScriptGenerator:
    """Generate temporary Nuke scripts with proper Read nodes.

    This class tracks temporary files and ensures they are cleaned up
    on program exit to prevent disk space leaks.
    """

    # Track all temporary files created for cleanup
    _temp_files: ClassVar[set[str]] = set()
    _cleanup_registered: ClassVar[bool] = False


    def __init__(self) -> None:
        """Initialize the generator with helper modules."""
        super().__init__()
        self.templates = NukeScriptTemplates()
        self.detector = NukeMediaDetector()

    @classmethod
    def _register_cleanup(cls) -> None:
        """Register cleanup function to run at program exit."""
        if not cls._cleanup_registered:
            _ = atexit.register(cls._cleanup_temp_files)
            cls._cleanup_registered = True

    @classmethod
    def _cleanup_temp_files(cls) -> None:
        """Clean up all temporary files created during session."""
        for temp_file in cls._temp_files:
            try:
                temp_path = Path(temp_file)
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:  # noqa: BLE001
                pass  # Ignore errors during exit cleanup
        cls._temp_files.clear()

    @classmethod
    def _track_temp_file(cls, filepath: str) -> str:
        """Track a temporary file for cleanup and return its path."""
        cls._register_cleanup()  # Ensure cleanup is registered
        cls._temp_files.add(filepath)
        return filepath

    def _create_script(
        self,
        plate_path: str = "",
        shot_name: str = "",
    ) -> str:
        """Internal method to create Nuke script content.

        Args:
            plate_path: Path to plate sequence (optional)
            shot_name: Name of the shot

        Returns:
            Complete Nuke script content as string

        """
        # Sanitize shot name
        safe_shot_name = self.detector.sanitize_shot_name(shot_name)

        # Convert paths for Nuke
        nuke_plate_path = self.templates.format_frame_sequence(plate_path)

        # Detect media properties
        first_frame, last_frame = NukeMediaDetector.detect_frame_range(plate_path)
        width, height = NukeMediaDetector.detect_resolution(plate_path)
        colorspace, raw_flag = NukeMediaDetector.detect_colorspace(plate_path)

        # Start building script content
        script_parts = [
            self.templates.get_script_header(),
            self.templates.WINDOW_LAYOUT_XML,
            self.templates.get_root_node(
                safe_shot_name, first_frame, last_frame, width, height
            ),
        ]

        # Add plate Read node if path provided
        if plate_path and nuke_plate_path:
            script_parts.append(
                self.templates.get_read_node(
                    nuke_plate_path,
                    safe_shot_name,
                    first_frame,
                    last_frame,
                    width,
                    height,
                    colorspace,
                    raw_flag,
                    xpos=0,
                    ypos=-300,
                )
            )

            # Add Grade node for color correction
            script_parts.append(self.templates.get_grade_node(xpos=0, ypos=-50))

        # Add Viewer node
        script_parts.append(
            self.templates.get_viewer_node(first_frame, last_frame, xpos=0, ypos=100)
        )

        return "\n\n".join(script_parts)

    @staticmethod
    def create_plate_script(plate_path: str, shot_name: str) -> str | None:
        """Create a Nuke script with a proper Read node for the plate.

        Args:
            plate_path: Path to the plate sequence (with #### or %04d pattern)
            shot_name: Name of the shot for the script

        Returns:
            Path to the temporary .nk script, or None if creation failed

        """
        try:
            generator = NukeScriptGenerator()
            script_content = generator._create_script(
                plate_path=plate_path,
                shot_name=shot_name,
            )

            # Create temporary file
            safe_shot_name = generator.detector.sanitize_shot_name(shot_name)
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".nk",
                prefix=f"{safe_shot_name}_plate_",
                delete=False,
                encoding="utf-8",
            ) as tmp_file:
                _ = tmp_file.write(script_content)
                temp_path = tmp_file.name

            # Track the file for cleanup at program exit
            return NukeScriptGenerator._track_temp_file(temp_path)

        except Exception:
            logger.exception("Error creating Nuke script")
            return None

    @staticmethod
    def save_workspace_script(
        script_content: str,
        workspace_path: str,
        shot_name: str,
        version: int | None = None,
        user: str | None = None,
        plate: str = "mm-default",
        pass_name: str = "PL01",
    ) -> str | None:
        """Save a Nuke script in the workspace directory.

        Args:
            script_content: The Nuke script content to save
            workspace_path: Base workspace path for the shot
            shot_name: Shot name (e.g., "BRX_166_0010")
            version: Version number (auto-determined if None)
            user: Username (defaults to current user)
            plate: Plate name (defaults to "mm-default")
            pass_name: Pass name (defaults to "PL01")

        Returns:
            Path to the saved script, or None on error

        """
        try:
            # Local application imports
            from nuke.workspace_manager import NukeWorkspaceManager

            # Get user from environment if not provided
            if user is None:
                user = os.environ.get("USER", Config.DEFAULT_USERNAME)

            # Get the script directory
            script_dir = NukeWorkspaceManager.get_workspace_script_directory(
                workspace_path, user, plate, pass_name
            )

            # Determine version if not provided
            if version is None:
                _, version = NukeWorkspaceManager.get_next_script_path(
                    script_dir, shot_name, plate, pass_name
                )

            # Build the filename
            filename = f"{shot_name}_{plate}_{pass_name}_scene_v{version:03d}.nk"
            script_path = script_dir / filename

            # Save the script
            with script_path.open("w", encoding="utf-8") as f:
                _ = f.write(script_content)

            logger.info(f"Saved Nuke script to workspace: {script_path}")
            return str(script_path)

        except Exception:
            logger.exception("Error saving Nuke script to workspace")
            return None

    @staticmethod
    def create_workspace_plate_script(
        plate_path: str,
        workspace_path: str,
        shot_name: str,
        version: int | None = None,
        user: str | None = None,
        plate_name: str = "mm-default",
        pass_name: str = "PL01",
    ) -> str | None:
        """Create and save a Nuke script with plate in the workspace.

        This is a convenience method that combines create_plate_script
        and save_workspace_script.

        Args:
            plate_path: Path to the plate sequence
            workspace_path: Base workspace path for the shot
            shot_name: Shot name (e.g., "BRX_166_0010")
            version: Version number (auto-determined if None)
            user: Username (defaults to current user)
            plate_name: Plate name (defaults to "mm-default")
            pass_name: Pass name (defaults to "PL01")

        Returns:
            Path to the saved script, or None on error

        """
        # First create the script content
        script_content = NukeScriptGenerator.create_plate_script(plate_path, shot_name)
        if not script_content:
            return None

        # Read the temporary file content
        try:
            with Path(script_content).open(encoding="utf-8") as f:
                content = f.read()
        except Exception:
            logger.exception("Error reading temporary script")
            return None

        # Save to workspace
        saved_path = NukeScriptGenerator.save_workspace_script(
            content, workspace_path, shot_name, version, user, plate_name, pass_name
        )

        # Clean up the temporary file if save was successful
        if saved_path and Path(script_content).exists():
            try:
                Path(script_content).unlink()
                if script_content in NukeScriptGenerator._temp_files:
                    NukeScriptGenerator._temp_files.remove(script_content)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to clean up temp file", exc_info=True)

        return saved_path

    @staticmethod
    def create_plate_directory_script(
        plate_path: str,
        workspace_path: str,
        shot_name: str,
        plate_name: str,
        version: int = 1,
    ) -> str | None:
        """Create Nuke script directly in workspace directory (no temp files).

        Saves to: {workspace}/user/{user}/mm/nuke/scripts/{plate}/
        Filename: {shot}_mm-default_{plate}_scene_v{version:03d}.nk

        This method writes directly to the workspace location with a single file operation,
        ensuring scripts persist across plate version updates.

        Args:
            plate_path: Path to the plate sequence (used to extract metadata)
            workspace_path: Shot workspace path
            shot_name: Shot name (e.g., "DM_066_3580")
            plate_name: Plate name (e.g., "FG01", "BG01")
            version: Version number for the script

        Returns:
            Path to created script or None on error

        """
        try:
            generator = NukeScriptGenerator()

            # Generate script content
            script_content = generator._create_script(
                plate_path=plate_path,
                shot_name=shot_name,
            )

            # Get workspace script directory using PlateDiscovery
            script_dir = PlateDiscovery.get_workspace_script_directory(
                workspace_path, None, plate_name
            )
            if not script_dir:
                logger.error(
                    f"Failed to get workspace script directory for {plate_name} "
                     f"in workspace {workspace_path}"
                )
                return None

            # Build filename
            filename = f"{shot_name}_mm-default_{plate_name}_scene_v{version:03d}.nk"
            output_path = script_dir / filename

            # Write directly (no temp file!)
            with output_path.open("w", encoding="utf-8") as f:
                _ = f.write(script_content)

            logger.info(f"Created Nuke script in workspace: {output_path}")
            return str(output_path)

        except Exception:
            logger.exception("Failed to create workspace script")
            return None

    @staticmethod
    def create_empty_plate_script(
        workspace_path: str,
        shot_name: str,
        plate_name: str,
        version: int = 1,
    ) -> str | None:
        """Create empty Nuke script directly in workspace directory.

        Creates a basic script with Root node but no Read nodes in the
        workspace directory, ensuring it persists independently of plate versions.

        Saves to: {workspace}/user/{user}/mm/nuke/scripts/{plate}/

        Args:
            workspace_path: Shot workspace path
            shot_name: Shot name
            plate_name: Plate name (e.g., "FG01")
            version: Version number

        Returns:
            Path to created script or None on error

        """
        try:
            generator = NukeScriptGenerator()

            # Generate empty script content (no plate)
            script_content = generator._create_script(
                plate_path="",  # Empty plate path = no Read node
                shot_name=shot_name,
            )

            # Get workspace script directory
            script_dir = PlateDiscovery.get_workspace_script_directory(
                workspace_path, None, plate_name
            )
            if not script_dir:
                logger.error(
                    f"Failed to get workspace script directory for {plate_name}"
                )
                return None

            # Build filename
            filename = f"{shot_name}_mm-default_{plate_name}_scene_v{version:03d}.nk"
            output_path = script_dir / filename

            # Write directly
            with output_path.open("w", encoding="utf-8") as f:
                _ = f.write(script_content)

            logger.info(f"Created empty Nuke script in workspace: {output_path}")
            return str(output_path)

        except Exception:
            logger.exception("Failed to create empty workspace script")
            return None

