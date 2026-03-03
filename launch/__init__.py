"""Launch system components for application launching.

This package contains focused components for managing application launches:
- EnvironmentManager: Environment detection and configuration
- CommandBuilder: Command assembly and validation
- ProcessExecutor: Process execution and management
- AppHandler: Protocol and per-DCC handler classes
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
from launch.environment_manager import EnvironmentManager
from launch.process_executor import ProcessExecutor


__all__ = [
    "AppHandler",
    "CommandBuilder",
    "EnvironmentManager",
    "GenericAppHandler",
    "MayaAppHandler",
    "NukeAppHandler",
    "ProcessExecutor",
    "RVAppHandler",
    "ThreeDEAppHandler",
]
