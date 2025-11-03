"""Generate Nuke scripts with proper Read nodes for plates and undistortion.

This module has been refactored to use separate modules for templates, detection,
and undistortion parsing while maintaining backward compatibility.
"""

from __future__ import annotations

# Standard library imports
import atexit
import os
import tempfile
from pathlib import Path
from typing import ClassVar

# Local application imports
from logging_mixin import get_module_logger
from nuke_media_detector import NukeMediaDetector
from nuke_script_templates import NukeScriptTemplates
from nuke_undistortion_parser import NukeUndistortionParser
from plate_discovery import PlateDiscovery


# Module-level logger for static methods
logger = get_module_logger(__name__)


class NukeScriptGenerator:
    """Generate temporary Nuke scripts with proper Read nodes.

    This class tracks temporary files and ensures they are cleaned up
    on program exit to prevent disk space leaks.
    """

    # Track all temporary files created for cleanup
    _temp_files: ClassVar[set[str]] = set()
    _cleanup_registered: ClassVar[bool] = False

    # Backward compatibility: expose WINDOW_LAYOUT_XML as class attribute
    WINDOW_LAYOUT_XML = NukeScriptTemplates.WINDOW_LAYOUT_XML

    # onCreate Python script for undistortion loader
    UNDISTORTION_ONCREATE_SCRIPT = """import nuke
import os
import sys
import re

try:
    print('DEBUG: Starting undistortion import...')
    print(f'DEBUG: Python version: {sys.version}')

    undist_file = r"{undist_file}"
    print(f'DEBUG: Looking for undistortion file: {undist_file}')

    if os.path.exists(undist_file):
        print('DEBUG: File exists, attempting to source...')
        try:
            # Source the undistortion file
            nuke.scriptSource(undist_file)
            print('DEBUG: Successfully sourced undistortion file')

            # Get all imported nodes and sanitize their names
            imported_nodes = nuke.selectedNodes()
            print(f'DEBUG: Found {len(imported_nodes)} imported nodes')

            # Sanitize node names - replace illegal characters
            for node in imported_nodes:
                try:
                    original_name = node.name()
                    # Replace hyphens and other illegal characters with underscores
                    # Nuke node names can only contain letters, numbers, and underscores
                    sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '_', original_name)
                    if sanitized_name != original_name:
                        # Find a unique name if the sanitized name already exists
                        base_name = sanitized_name
                        counter = 1
                        while nuke.exists(sanitized_name):
                            sanitized_name = f'{base_name}_{counter}'
                            counter += 1
                        node.setName(sanitized_name)
                        print(f'DEBUG: Renamed node from {original_name} to ' +
                              f'{sanitized_name}')
                except Exception as rename_ex:
                    print(f'DEBUG: Could not rename node {node}: {rename_ex}')
                    continue

            # Now try to connect imported nodes to Read_Plate
            try:
                read_plate = nuke.toNode('Read_Plate')
                if imported_nodes and read_plate:
                    for node in imported_nodes:
                        if hasattr(node, 'maxInputs') and node.maxInputs() > 0:
                            if hasattr(node, 'input') and node.input(0) is None:
                                try:
                                    node.setInput(0, read_plate)
                                    print(f'DEBUG: Connected {node.name()} to ' +
                                          'Read_Plate')
                                    break
                                except Exception as ex:
                                    print(f'DEBUG: Could not connect ' +
                                          f'{node.name()}: {ex}')
                else:
                    print('DEBUG: No nodes to connect or Read_Plate not found')
            except Exception as connect_ex:
                print(f'DEBUG: Error during node connection: {connect_ex}')

            # Success - just log it, no popup
            print(f'INFO: Undistortion imported successfully from {undist_file}')
        except Exception as e:
            print(f'ERROR: Failed to source undistortion: {e}')
            import traceback
            traceback.print_exc()
            # No popup on error, just log it
            print(f'ERROR: Could not import undistortion from {undist_file}: {str(e)}')
    else:
        print(f'WARNING: Undistortion file not found: {undist_file}')
        # No popup, just log warning
except Exception as e:
    print(f'ERROR: Unexpected error in Python executor: {e}')
    import traceback
    traceback.print_exc()"""

    def __init__(self) -> None:
        """Initialize the generator with helper modules."""
        super().__init__()
        self.templates = NukeScriptTemplates()
        self.detector = NukeMediaDetector()
        self.parser = NukeUndistortionParser()

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
                    print(f"Cleaned up temporary file: {temp_file}")
            except Exception as e:
                print(f"Warning: Could not delete temp file {temp_file}: {e}")
        cls._temp_files.clear()

    @classmethod
    def _track_temp_file(cls, filepath: str) -> str:
        """Track a temporary file for cleanup and return its path."""
        cls._register_cleanup()  # Ensure cleanup is registered
        cls._temp_files.add(filepath)
        return filepath

    @staticmethod
    def _escape_path(path: str) -> str:
        """Escape file path for Nuke script.

        Nuke uses forward slashes even on Windows.
        """
        return NukeScriptTemplates.escape_path(path)

    def _create_script(
        self,
        plate_path: str = "",
        undistortion_path: str = "",
        shot_name: str = "",
        script_type: str = "standard",
    ) -> str:
        """Internal method to create Nuke script content.

        Args:
            plate_path: Path to plate sequence (optional)
            undistortion_path: Path to undistortion file (optional)
            shot_name: Name of the shot
            script_type: Type of script ("standard", "loader", "with_undistortion")

        Returns:
            Complete Nuke script content as string
        """
        # Sanitize shot name
        safe_shot_name = self.detector.sanitize_shot_name(shot_name)

        # Convert paths for Nuke
        nuke_plate_path = self.templates.format_frame_sequence(plate_path)

        # Detect media properties using backward-compatible methods
        first_frame, last_frame = NukeScriptGenerator._detect_frame_range(plate_path)
        width, height = NukeScriptGenerator._detect_resolution(plate_path)
        colorspace, raw_flag = NukeScriptGenerator._detect_colorspace(plate_path)

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

        # Handle different script types
        if script_type == "loader" and undistortion_path:
            # Create loader script with Python onCreate
            nuke_undist_path = self.templates.escape_path(undistortion_path)

            # Prepare the onCreate script for the NoOp node
            backslash = chr(92)  # Avoid backslash in f-string
            quote = chr(34)  # Avoid quote escaping in f-string
            formatted_oncreate_script = (
                self.UNDISTORTION_ONCREATE_SCRIPT.replace(
                    chr(10), backslash + "n"
                )  # Replace newlines with \n
                .replace(quote, backslash + quote)  # Escape quotes
                .format(undist_file=nuke_undist_path)
            )

            # Add NoOp node with Python script
            script_parts.append(
                self.templates.get_noop_node(
                    "PythonExecutor",
                    "Python Script Loader\\nImports undistortion nodes",
                    200,
                    -300,
                    oncreate_script=formatted_oncreate_script,
                )
            )

            # Add note about undistortion source
            script_parts.append(
                self.templates.get_sticky_note(
                    f"Undistortion imported from:\\n{nuke_undist_path}",
                    200,
                    -300,
                    "Note_Undistortion_Source",
                )
            )

        elif script_type == "with_undistortion" and undistortion_path:
            # Parse and import undistortion nodes
            imported_nodes = self.parser.parse_undistortion_file(
                undistortion_path, ypos_offset=-200
            )

            if imported_nodes:
                logger.info("Successfully imported undistortion nodes into script")
                # Fix the first node to connect to Read_Plate (if it exists)
                if plate_path and nuke_plate_path:
                    # Connect first undistortion node to Read_Plate
                    imported_nodes = imported_nodes.replace(
                        "inputs 0",
                        "inputs 1",
                        1,
                    )
                    logger.debug("Connected first undistortion node to Read_Plate")

                script_parts.append(imported_nodes)
                script_parts.append(
                    self.templates.get_sticky_note(
                        (f"Undistortion imported from:\\n"
                        f"{self.templates.escape_path(undistortion_path)}"),
                        200,
                        -300,
                        "Note_Undistortion_Source",
                    )
                )
            else:
                # Fallback to reference if import failed
                logger.warning(

                        f"Failed to import undistortion nodes from {undistortion_path}, "
                        "creating reference note instead"

                )
                escaped_undist_path = self.templates.escape_path(undistortion_path)
                script_parts.append(
                    self.templates.get_sticky_note(
                        (f"UNDISTORTION AVAILABLE\\nFile > Import Script:\\n"
                        f"{escaped_undist_path}"),
                        200,
                        -300,
                        "Note_Undistortion",
                        color="0xff8800ff",
                        font_size=16,
                    )
                )

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
                script_type="standard",
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

        except Exception as e:
            print(f"Error creating Nuke script: {e}")
            return None

    @staticmethod
    def create_loader_script(
        plate_path: str,
        undistortion_path: str,
        shot_name: str,
    ) -> str | None:
        """Create a minimal Nuke loader script that uses Nuke's Python API.

        This method creates a simple script that loads both the plate and undistortion
        using Nuke's built-in scriptSource() command.

        Args:
            plate_path: Path to the plate sequence
            undistortion_path: Path to undistortion .nk file
            shot_name: Name of the shot

        Returns:
            Path to the temporary loader script, or None on error
        """
        try:
            generator = NukeScriptGenerator()
            script_content = generator._create_script(
                plate_path=plate_path,
                undistortion_path=undistortion_path,
                shot_name=shot_name,
                script_type="loader",
            )

            # Create temporary file
            safe_shot_name = generator.detector.sanitize_shot_name(shot_name)
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".nk",
                prefix=f"{safe_shot_name}_loader_",
                delete=False,
                encoding="utf-8",
            ) as tmp_file:
                _ = tmp_file.write(script_content)
                temp_path = tmp_file.name

            # Track temp file for cleanup
            _ = NukeScriptGenerator._track_temp_file(temp_path)

            print(f"Created Nuke loader script: {temp_path}")
            print(f"  Plate: {plate_path}")
            print(f"  Undistortion: {undistortion_path}")

            return temp_path

        except Exception as e:
            print(f"Error creating loader script: {e}")
            return None

    @staticmethod
    def create_plate_script_with_undistortion(
        plate_path: str,
        undistortion_path: str | None,
        shot_name: str,
    ) -> str | None:
        """Create a Nuke script with plate and optional undistortion.

        This version properly imports the undistortion nodes from the .nk file
        and integrates them into the compositing graph.

        Args:
            plate_path: Path to the plate sequence (can be empty)
            undistortion_path: Path to undistortion .nk file (optional)
            shot_name: Name of the shot

        Returns:
            Path to the temporary .nk script
        """
        try:
            generator = NukeScriptGenerator()
            script_content = generator._create_script(
                plate_path=plate_path or "",
                undistortion_path=undistortion_path or "",
                shot_name=shot_name,
                script_type="with_undistortion",
            )

            # Create temporary file
            safe_shot_name = generator.detector.sanitize_shot_name(shot_name)
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".nk",
                prefix=f"{safe_shot_name}_comp_",
                delete=False,
                encoding="utf-8",
            ) as tmp_file:
                _ = tmp_file.write(script_content)
                temp_path = tmp_file.name

            # Track the file for cleanup at program exit
            return NukeScriptGenerator._track_temp_file(temp_path)

        except Exception as e:
            print(f"Error creating Nuke script with undistortion: {e}")
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
            from nuke_workspace_manager import NukeWorkspaceManager

            # Get user from environment if not provided
            if user is None:
                user = os.environ.get("USER", "gabriel-h")

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

            print(f"Saved Nuke script to workspace: {script_path}")
            return str(script_path)

        except Exception as e:
            print(f"Error saving Nuke script to workspace: {e}")
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
        except Exception as e:
            print(f"Error reading temporary script: {e}")
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
            except Exception:
                pass  # Non-critical error

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
                script_type="standard",
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

        except Exception as e:
            logger.error(f"Failed to create workspace script: {e}")
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
                script_type="standard",
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

        except Exception as e:
            logger.error(f"Failed to create empty workspace script: {e}")
            return None

    # Backward compatibility: Static method aliases for detection functions
    @staticmethod
    def _detect_frame_range(plate_path: str) -> tuple[int, int]:
        """Backward compatibility wrapper for frame range detection."""
        return NukeMediaDetector.detect_frame_range(plate_path)

    @staticmethod
    def _detect_colorspace(plate_path: str) -> tuple[str, bool]:
        """Backward compatibility wrapper for colorspace detection."""
        return NukeMediaDetector.detect_colorspace(plate_path)

    @staticmethod
    def _detect_resolution(plate_path: str) -> tuple[int, int]:
        """Backward compatibility wrapper for resolution detection."""
        return NukeMediaDetector.detect_resolution(plate_path)
