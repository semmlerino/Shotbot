"""Launch system components for application launching.

This package contains focused components for managing application launches:
- EnvironmentManager: Environment detection and configuration
- CommandBuilder: Command assembly and validation
- ProcessExecutor: Process execution and management
- AppHandler: Protocol and per-DCC handler classes
- CommandLauncher: Production launcher orchestrator
- LaunchContext: Value object for launch parameters
- open_plate_in_rv: Utility for opening plates in RV
"""

from launch.app_handlers import (
    AppHandler,
    GenericAppHandler,
    MayaAppHandler,
    NukeAppHandler,
    RVAppHandler,
    ThreeDEAppHandler,
)
from launch.command_builder import CommandBuilder
from launch.command_launcher import CommandLauncher, LaunchContext
from launch.environment_manager import EnvironmentManager
from launch.process_executor import ProcessExecutor
from launch.rv_launcher import open_plate_in_rv


__all__ = [
    "AppHandler",
    "CommandBuilder",
    "CommandLauncher",
    "EnvironmentManager",
    "GenericAppHandler",
    "LaunchContext",
    "MayaAppHandler",
    "NukeAppHandler",
    "ProcessExecutor",
    "RVAppHandler",
    "ThreeDEAppHandler",
    "open_plate_in_rv",
]
