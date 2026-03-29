"""Launch request dataclass for unified launch API."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from type_definitions import ThreeDEScene


@dataclass(frozen=True)
class LaunchContext:
    """Value object encapsulating application launch parameters.

    This immutable dataclass simplifies CommandLauncher's API by grouping
    related launch options together, reducing parameter coupling.

    Attributes:
        open_latest_threede: Whether to open latest 3DE scene file (3DE only)
        open_latest_maya: Whether to open latest Maya scene file (Maya only)
        open_latest_scene: Whether to open latest Nuke script (Nuke only)
        create_new_file: Whether to create a new version (Nuke only)
        selected_plate: Selected plate space for Nuke workspace scripts
        sequence_path: Image sequence path for RV playback (RV only)

    """

    open_latest_threede: bool = False
    open_latest_maya: bool = False
    open_latest_scene: bool = False
    create_new_file: bool = False
    selected_plate: str | None = None
    sequence_path: str | None = None


@dataclass(frozen=True)
class PendingLaunch:
    """Groups non-worker pending state for async file searches."""

    app_name: str
    context: LaunchContext
    command: str


class LaunchPhase(enum.Enum):
    """Explicit state machine phases for CommandLauncher's async launch lifecycle."""

    IDLE = "idle"
    VERIFYING_APP = "verifying_app"
    SEARCHING_FILES = "searching_files"
    EXECUTING = "executing"


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
