"""DCC configuration dataclasses.

Defines DCCConfig and CheckboxConfig for DCC section setup,
plus the DEFAULT_DCC_CONFIGS list used throughout the application.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from .scene_file import FileType


@final
@dataclass
class CheckboxConfig:
    """Configuration for a checkbox option."""

    label: str
    tooltip: str
    key: str  # Settings key for persistence
    default: bool = False


@final
@dataclass
class DCCConfig:
    """Configuration for a DCC section."""

    name: str  # Internal name: "3de", "nuke", "maya", "rv"
    display_name: str  # Display name: "3DEqualizer", "Nuke", etc.
    color: str  # Accent color hex
    shortcut: str  # Keyboard shortcut: "3", "N", "M", "R"
    tooltip: str = ""
    checkboxes: list[CheckboxConfig] | None = None
    file_type: FileType | None = None  # Which FileType this DCC uses (None = no files)


# Default DCC configurations
DEFAULT_DCC_CONFIGS = [
    DCCConfig(
        name="3de",
        display_name="3DEqualizer",
        color="#2b4d6f",
        shortcut="3",
        tooltip="Launch 3DE for matchmove/tracking",
        checkboxes=[
            CheckboxConfig(
                label="Open latest 3DE scene (when available)",
                tooltip="Automatically open the latest scene file from the workspace",
                key="open_latest_threede",
                default=True,
            )
        ],
        file_type=FileType.THREEDE,
    ),
    DCCConfig(
        name="maya",
        display_name="Maya",
        color="#4d2b5d",
        shortcut="M",
        tooltip="Launch Maya for 3D work",
        checkboxes=[
            CheckboxConfig(
                label="Open latest Maya scene (when available)",
                tooltip="Automatically open the latest scene file from the workspace",
                key="open_latest_maya",
                default=True,
            )
        ],
        file_type=FileType.MAYA,
    ),
    DCCConfig(
        name="nuke",
        display_name="Nuke",
        color="#5d4d2b",
        shortcut="N",
        tooltip="Launch Nuke for compositing",
        checkboxes=[
            CheckboxConfig(
                label="Open latest scene",
                tooltip="Open the most recent Nuke script from workspace",
                key="open_latest_scene",
                default=True,
            ),
            CheckboxConfig(
                label="Create new file",
                tooltip="Always create a new version of the Nuke script",
                key="create_new_file",
                default=False,
            ),
        ],
        file_type=FileType.NUKE,
    ),
    DCCConfig(
        name="rv",
        display_name="RV",
        color="#2b5d4d",
        shortcut="R",
        tooltip="Launch RV for playback and review",
        file_type=None,
    ),
]
