"""Simplified Nuke launcher for the common workflow: open the latest script.

This module handles the 90% use case where users just want to open their latest
Nuke script without any fancy script generation or media loading. It's literally
just `nuke <filepath>` - no over-engineering.

For complex cases (generating scripts with plates), use NukeLaunchHandler.
"""

from __future__ import annotations

import os
import shlex
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from logging_mixin import LoggingMixin


if TYPE_CHECKING:
    from shot_model import Shot


class SimpleNukeLauncher(LoggingMixin):
    """Simple Nuke launcher for opening existing scripts.

    This class handles the most common workflow: open the latest Nuke script
    for a selected shot and plate. If no script exists, it just opens Nuke.

    For complex workflows (generating scripts, loading plates), use NukeLaunchHandler.
    """

    def open_latest_script(
        self,
        shot: Shot,
        plate: str,
        create_if_missing: bool = False,
    ) -> tuple[str, list[str]]:
        """Open the latest Nuke script for a shot and plate.

        Args:
            shot: Current shot context
            plate: Plate name (e.g., "FG01", "BG01")
            create_if_missing: If True, create v001 when no scripts exist.
                             If False, just open empty Nuke.

        Returns:
            Tuple of (nuke_command, log_messages)

        """
        log_messages: list[str] = []

        # Build script directory path
        user = os.environ.get("USER", "gabriel-h")
        script_dir = (
            Path(shot.workspace_path)
            / "user"
            / user
            / "mm"
            / "nuke"
            / "scripts"
            / "mm-default"
            / "scene"
            / plate
        )

        # Find all scripts matching the pattern
        pattern = f"{shot.full_name}_mm-default_{plate}_scene_v*.nk"

        try:
            if script_dir.exists():
                scripts = sorted(script_dir.glob(pattern))

                if scripts:
                    # Found existing scripts - open the latest one
                    latest_script = scripts[-1]
                    safe_path = shlex.quote(str(latest_script))
                    command = f"nuke {safe_path}"
                    log_messages.append(f"Opening: {latest_script.name}")
                    self.logger.info(f"Opening latest Nuke script: {latest_script}")
                    return command, log_messages

            # No scripts found
            if create_if_missing:
                # Create v001 via Nuke's API (triggers hooks/templates)
                log_messages.append(f"No existing scripts found for {plate}")
                log_messages.append("Creating v001 via Nuke's API...")
                command = self._create_script_via_nuke_api(shot, plate, script_dir, version=1)
                log_messages.append(f"Will create: {shot.full_name}_mm-default_{plate}_scene_v001.nk")
                log_messages.append("Note: Nuke will run onCreate hooks and apply templates")
                return command, log_messages
            # Just open empty Nuke and let user save manually
            log_messages.append(f"No scripts found for {plate}")
            log_messages.append("Opening empty Nuke (save manually to create v001)")
            return "nuke", log_messages

        except (OSError, PermissionError) as e:
            self.logger.error(f"Error accessing script directory {script_dir}: {e}")
            log_messages.append(f"Error: Could not access script directory: {e}")
            log_messages.append("Opening empty Nuke")
            return "nuke", log_messages

    def _create_script_via_nuke_api(
        self,
        shot: Shot,
        plate: str,
        script_dir: Path,
        version: int,
    ) -> str:
        """Generate Nuke command that creates a script via Nuke's Python API.

        This launches Nuke with a startup script that:
        1. Sets environment variables for show/shot context
        2. Creates and saves a new file using nuke.scriptSaveAs()
        3. Triggers all onCreate hooks and templates with proper context
        4. Cleans up the temporary startup script after execution

        Args:
            shot: Current shot context
            plate: Plate name
            script_dir: Directory to save script in
            version: Version number

        Returns:
            Nuke command string with startup script

        """
        # Ensure directory exists
        script_dir.mkdir(parents=True, exist_ok=True)

        # Build filename
        filename = f"{shot.full_name}_mm-default_{plate}_scene_v{version:03d}.nk"
        script_path = script_dir / filename

        # Get user
        user = os.environ.get("USER", "unknown")

        # Create temp file first so we can reference its path in the script
        fd, temp_script = tempfile.mkstemp(suffix=".py", prefix="nuke_create_")

        # Create a temporary Python script that Nuke will execute on startup
        # The script cleans itself up after execution
        startup_script = f"""import nuke
import os

# Set up show/shot context environment variables BEFORE calling hooks
# This ensures onCreate and onSave hooks have proper context
os.environ["SHOW"] = {shot.show!r}
os.environ["SEQUENCE"] = {shot.sequence!r}
os.environ["SHOT"] = {shot.shot!r}
os.environ["SHOT_NAME"] = {shot.full_name!r}
os.environ["WORKSPACE"] = {shot.workspace_path!r}
os.environ["PLATE"] = {plate!r}
os.environ["USER"] = {user!r}

# Ensure directory exists
script_dir = {str(script_dir)!r}
os.makedirs(script_dir, exist_ok=True)

# Check if SGTK engine is already running to prevent double registration
# SGTK bootstraps on Nuke startup via nuke_tools init.py, and scriptNew()
# can trigger hooks that attempt to re-register. Set flag to prevent this.
try:
    import sgtk
    if sgtk.platform.current_engine():
        # Engine already running - set flag to prevent re-registration attempts
        os.environ["SGTK_BOOTSTRAP_DONE"] = "1"
        print("SGTK engine already running, flagged to prevent re-registration")
except ImportError:
    pass  # SGTK not available, proceed normally

# Set up new script
nuke.scriptNew()

# Save the script (triggers onCreate hooks and templates WITH context)
script_path = {str(script_path)!r}
nuke.scriptSaveAs(script_path, overwrite=False)

print(f"Created new Nuke script: {{script_path}}")
print(f"Context: SHOW={{os.environ['SHOW']}} SHOT={{os.environ['SHOT_NAME']}} PLATE={{os.environ['PLATE']}}")

# Clean up this temporary startup script
try:
    os.remove({temp_script!r})
except OSError:
    pass  # Ignore cleanup failures (file may be locked on Windows)
"""

        # Write startup script using the file descriptor from mkstemp
        with os.fdopen(fd, "w") as f:
            _ = f.write(startup_script)

        # Build Nuke command WITHOUT -t flag (keeps GUI open)
        safe_temp = shlex.quote(temp_script)
        command = f"nuke {safe_temp}"

        self.logger.info(
            f"Generated Nuke startup script to create: {script_path}"
        )
        self.logger.info(
            f"Context: SHOW={shot.show} SHOT={shot.full_name} PLATE={plate}"
        )
        self.logger.debug(f"Startup script: {temp_script}")

        return command

    def create_new_version(
        self,
        shot: Shot,
        plate: str,
    ) -> tuple[str, list[str]]:
        """Create a new version of the Nuke script (increments version number).

        Args:
            shot: Current shot context
            plate: Plate name

        Returns:
            Tuple of (nuke_command, log_messages)

        """
        log_messages: list[str] = []

        # Build script directory path
        user = os.environ.get("USER", "gabriel-h")
        script_dir = (
            Path(shot.workspace_path)
            / "user"
            / user
            / "mm"
            / "nuke"
            / "scripts"
            / "mm-default"
            / "scene"
            / plate
        )

        # Find highest version
        pattern = f"{shot.full_name}_mm-default_{plate}_scene_v*.nk"
        next_version = 1

        try:
            if script_dir.exists():
                scripts = sorted(script_dir.glob(pattern))
                if scripts:
                    # Extract version from last script
                    import re

                    version_match = re.search(r"_v(\d{3})\.nk$", scripts[-1].name)
                    if version_match:
                        next_version = int(version_match.group(1)) + 1

            # Create new version via Nuke's API (triggers hooks/templates)
            command = self._create_script_via_nuke_api(shot, plate, script_dir, next_version)
            filename = f"{shot.full_name}_mm-default_{plate}_scene_v{next_version:03d}.nk"
            log_messages.append(f"Creating new version: v{next_version:03d}")
            log_messages.append(f"Will create: {filename}")
            log_messages.append("Note: Nuke will run onCreate hooks and apply templates")
            self.logger.info(f"Creating Nuke script version {next_version} via API")
            return command, log_messages

        except (OSError, PermissionError) as e:
            self.logger.error(f"Failed to create new version: {e}")
            log_messages.append(f"Error: Could not create new version: {e}")
            log_messages.append("Opening empty Nuke")
            return "nuke", log_messages
