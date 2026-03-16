"""Nuke integration components for script generation and launching.

This package contains focused components for Nuke workflow management:
- NukeLaunchHandler: Centralized Nuke-specific launching logic
- NukeMediaDetector: Detection utilities for media properties
- NukeScriptGenerator: Temporary and workspace Nuke script generation
- NukeScriptTemplates: Template builders for Nuke script components
- NukeWorkspaceManager: Nuke script management in VFX pipeline workspace
- SimpleNukeLauncher: Simple Nuke launcher for opening existing scripts
"""

from nuke.launch_handler import NukeLaunchHandler
from nuke.media_detector import NukeMediaDetector
from nuke.script_generator import NukeScriptGenerator
from nuke.script_templates import NukeScriptTemplates
from nuke.simple_launcher import SimpleNukeLauncher
from nuke.workspace_manager import NukeWorkspaceManager


__all__ = [
    "NukeLaunchHandler",
    "NukeMediaDetector",
    "NukeScriptGenerator",
    "NukeScriptTemplates",
    "NukeWorkspaceManager",
    "SimpleNukeLauncher",
]
