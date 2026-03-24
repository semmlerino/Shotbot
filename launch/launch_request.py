"""Launch request dataclass for unified launch API."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from launch.command_launcher import LaunchContext
    from type_definitions import ThreeDEScene


@dataclass(frozen=True)
class LaunchRequest:
    """Unified launch request carrying all context needed for any launch type.

    The dispatcher in ``CommandLauncher.launch()`` inspects which optional
    fields are set to determine the launch path:

    - *scene* set → scene-file launch (``launch_app_opening_scene_file`` path)
    - *file_path* set → explicit-file launch (``launch_with_file`` path)
    - neither → standard app launch (``launch_app`` path)

    Attributes:
        app_name: Application to launch (e.g. "3de", "maya", "nuke", "rv").
        workspace_path: Explicit workspace path. Required for file launches;
            for standard launches the current shot's workspace is used.
        file_path: Specific file to open (DCC section file dialog).
        scene: 3DE scene object for scene-file launches.
        context: Launch options (checkboxes, plate selection, etc.).
    """

    app_name: str
    workspace_path: str | None = None
    file_path: Path | None = None
    scene: ThreeDEScene | None = None
    context: LaunchContext | None = None
