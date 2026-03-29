"""Launch system components for application launching.

This package contains focused components for managing application launches:
- EnvironmentManager: Environment detection and configuration
- Command builders: Command assembly and validation (module-level functions)
- ProcessExecutor: Process execution and management
- AppHandler: Protocol and per-DCC handler classes
- CommandLauncher: Production launcher orchestrator
- LaunchContext: Value object for launch parameters
- HeadlessMode: Headless operation support for CI/CD and testing
"""

from launch.app_handlers import (
    AppHandler,
    GenericAppHandler,
    MayaAppHandler,
    NukeAppHandler,
    RVAppHandler,
    ThreeDEAppHandler,
)
from launch.command_builder import (
    add_logging,
    apply_nuke_environment_fixes,
    build_workspace_command,
    get_nuke_fix_summary,
    validate_path,
    wrap_for_background,
    wrap_with_rez,
)
from launch.command_launcher import CommandLauncher
from launch.environment_manager import EnvironmentManager
from launch.headless_mode import HeadlessMode
from launch.launch_request import LaunchContext
from launch.process_executor import ProcessExecutor


__all__ = [
    "AppHandler",
    "CommandLauncher",
    "EnvironmentManager",
    "GenericAppHandler",
    "HeadlessMode",
    "LaunchContext",
    "MayaAppHandler",
    "NukeAppHandler",
    "ProcessExecutor",
    "RVAppHandler",
    "ThreeDEAppHandler",
    "add_logging",
    "apply_nuke_environment_fixes",
    "build_workspace_command",
    "get_nuke_fix_summary",
    "validate_path",
    "wrap_for_background",
    "wrap_with_rez",
]
