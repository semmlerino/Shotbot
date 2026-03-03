"""App-specific command handlers for CommandLauncher.

Each handler encapsulates the per-DCC command-building logic used by
launch_with_file.  Adding a new DCC means adding one class and one
dict entry in CommandLauncher._app_handlers.

AppHandler is a Protocol (structural subtyping) — no base class required.

Design notes
------------
_build_app_command is NOT routed through AppHandler because:
  - The nuke branch needs self.current_shot (not in LaunchContext).
  - The 3de/maya branches drive async file search via CommandLauncher
    internal state (_pending_worker, _cache_manager, etc.).
  - The rv branch calls _build_rv_command which emits Qt signals.
All three concerns are tightly coupled to CommandLauncher and are left
there intentionally.  The protocol covers the clean, self-contained case:
launch_with_file.
"""
from __future__ import annotations

import base64
import shlex
from typing import Protocol


class AppHandler(Protocol):
    """Protocol for per-DCC command building in launch_with_file."""

    def build_file_command(
        self,
        base_cmd: str,
        safe_file_path: str,
    ) -> str:
        """Build the full shell command for launch_with_file.

        Args:
            base_cmd: App base command from Config.APPS (e.g. "nuke").
            safe_file_path: Shell-safe, validated file path string.

        Returns:
            Complete shell command string (without ws/rez wrapping).
        """
        ...

    def needs_sgtk_file_to_open(self) -> bool:
        """Return True if this app needs SGTK_FILE_TO_OPEN set before launch."""
        ...


class NukeAppHandler:
    """Handler for Nuke launches."""

    def __init__(self, scripts_dir: str) -> None:
        self._scripts_dir = scripts_dir

    def build_file_command(self, base_cmd: str, safe_file_path: str) -> str:
        nuke_path_export = f"export NUKE_PATH={self._scripts_dir}:$NUKE_PATH && "
        return f"{nuke_path_export}{base_cmd} {safe_file_path}"

    def needs_sgtk_file_to_open(self) -> bool:
        return True


class ThreeDEAppHandler:
    """Handler for 3DE launches."""

    def __init__(self, scripts_dir: str) -> None:
        self._scripts_dir = scripts_dir

    def build_file_command(self, base_cmd: str, safe_file_path: str) -> str:
        tde_scripts_export = (
            f"export PYTHON_CUSTOM_SCRIPTS_3DE4={self._scripts_dir}:"
            "$PYTHON_CUSTOM_SCRIPTS_3DE4 && "
        )
        return f"{tde_scripts_export}{base_cmd} -open {safe_file_path}"

    def needs_sgtk_file_to_open(self) -> bool:
        return True


class MayaAppHandler:
    """Handler for Maya launches."""

    def __init__(self, bootstrap_script: str) -> None:
        self._bootstrap_script = bootstrap_script

    def build_file_command(self, base_cmd: str, safe_file_path: str) -> str:
        encoded = base64.b64encode(self._bootstrap_script.encode()).decode()
        mel_bootstrap = (
            'python("import os,base64;'
            "s=os.environ.get('SHOTBOT_MAYA_SCRIPT','');"
            'exec(base64.b64decode(s).decode()) if s else None")'
        )
        return (
            f"export SHOTBOT_MAYA_SCRIPT={encoded} && "
            f"{base_cmd} -file {safe_file_path} -c {shlex.quote(mel_bootstrap)}"
        )

    def needs_sgtk_file_to_open(self) -> bool:
        return True


class RVAppHandler:
    """Handler for RV launches."""

    def build_file_command(self, base_cmd: str, safe_file_path: str) -> str:
        return f"{base_cmd} {safe_file_path}"

    def needs_sgtk_file_to_open(self) -> bool:
        return False


class GenericAppHandler:
    """Fallback handler for unknown or unregistered DCCs."""

    def build_file_command(self, base_cmd: str, safe_file_path: str) -> str:
        return f"{base_cmd} {safe_file_path}"

    def needs_sgtk_file_to_open(self) -> bool:
        return False
