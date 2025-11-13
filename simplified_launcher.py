"""Simplified launcher for VFX applications and commands.

This module consolidates process management from 2,872 lines across 4 components
into a single, streamlined class (~500 lines total).

Replaces:
- command_launcher.py (1,160 lines)
- launcher_manager.py (656 lines)
- process_pool_manager.py complexity (651 lines)
- persistent_terminal_manager.py (405 lines)
"""

from __future__ import annotations

# Standard library imports
import os
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, final

# Third-party imports
from PySide6.QtCore import QObject, Signal

# Local application imports
from config import Config
from launch.environment_manager import EnvironmentManager
from logging_mixin import LoggingMixin
from maya_latest_finder_refactored import MayaLatestFinder
from nuke_launch_handler import NukeLaunchHandler


if TYPE_CHECKING:
    # Local application imports
    from shot_model import Shot
    from threede_scene_model import ThreeDEScene


# Module-level constants
_SIGTERM_WAIT_SECONDS = 0.5  # Wait time between SIGTERM and SIGKILL


@final
class SimplifiedLauncher(LoggingMixin, QObject):
    """Simplified launcher replacing complex process management stack.

    Features:
    - Launch VFX applications (3de, nuke, maya, rv) with shot context
    - Execute workspace commands with 30-minute TTL caching
    - Support custom user-defined launchers
    - Direct subprocess execution without excessive abstraction layers
    """

    # Signals for UI updates
    command_executed = Signal(str, str)  # timestamp, command
    command_error = Signal(str, str)  # timestamp, error
    process_started = Signal(str, int)  # command, pid
    process_finished = Signal(str, int)  # command, return_code

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the simplified launcher.

        Args:
            parent: Optional parent QObject for proper Qt ownership
        """
        super().__init__(parent)

        # Cache for workspace commands with 30-minute TTL
        self._ws_cache: dict[
            str, tuple[str, float]
        ] = {}  # command -> (result, timestamp)
        self._ws_cache_ttl = Config.WS_CACHE_TTL
        self._cache_lock = threading.Lock()  # Thread-safe cache access

        # Track active processes for cleanup
        self._active_processes: dict[int, subprocess.Popen[str]] = {}
        self._process_lock = threading.Lock()  # Thread-safe process tracking

        # Current shot context
        self.current_shot: Shot | None = None

        # Initialize Nuke handler for consolidated Nuke functionality
        self.nuke_handler = NukeLaunchHandler()

        # Initialize environment manager for terminal detection and environment setup
        self.env_manager = EnvironmentManager()

        self.logger.info("SimplifiedLauncher initialized with 30-minute cache TTL")

    def set_current_shot(self, shot: Shot | None) -> None:
        """Set the current shot context."""
        self.current_shot = shot
        if shot:
            self.logger.info(f"Shot context set to: {shot.full_name}")

    # ========== Core VFX App Launching ==========

    def launch_vfx_app(
        self,
        app_name: str,
        shot: Shot | None = None,
        scene: ThreeDEScene | None = None,
        **options: bool | str | list[str],
    ) -> bool:
        """Launch a VFX application with optional shot/scene context.

        Args:
            app_name: Application name (3de, nuke, maya, rv)
            shot: Shot context (uses self.current_shot if not provided)
            scene: Optional 3DE scene to open
            **options: Additional options like open_latest, include_plate, etc.

        Returns:
            True if launch was successful, False otherwise
        """
        # Use provided shot or fall back to current
        shot = shot or self.current_shot
        if not shot and app_name != "rv":  # RV doesn't need shot context
            self._emit_error("No shot selected")
            return False

        # Validate app name
        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Log launch attempt with context
        self.logger.info(
            f"Launching {app_name} for {shot.full_name if shot else 'no shot'} "
            f"(open_latest={options.get('open_latest', False)}, "
            f"include_plate={options.get('include_plate', False)})"
        )

        # Special handling for Nuke using NukeLaunchHandler
        if app_name == "nuke" and shot:
            # NukeLaunchHandler returns complete command with environment fixes
            nuke_options = {
                "open_latest_scene": bool(options.get("open_latest")),
                "create_new_file": bool(options.get("create_new_file")),
                "include_raw_plate": bool(options.get("include_plate")),
            }

            base_command = Config.APPS[app_name]
            command, log_messages = self.nuke_handler.prepare_nuke_command(
                shot, base_command, nuke_options
            )

            # Log messages from handler
            for msg in log_messages:
                self.logger.info(msg)

            # Get environment fixes as bash commands
            env_fixes = self.nuke_handler.get_environment_fixes()
            if env_fixes:
                # Prepend environment fixes to command
                command = f"{env_fixes}{command}"

            # Use basic environment for shot context
            env = {
                "SHOT": shot.full_name,
                "SHOT_WORKSPACE": str(shot.workspace_path),
                "SHOW": shot.show,
            }

            timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
            self.command_executed.emit(
                timestamp, f"Launching {app_name} with command: {command[:100]}..."
            )

            return self._execute_in_terminal(command, env)

        # Build command based on app and options (for non-Nuke apps)
        command = self._build_app_command(app_name, shot, scene, options)

        # Get environment for the app
        env = self._get_app_environment(app_name, shot)

        # Log what we're doing
        timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
        self.command_executed.emit(
            timestamp, f"Launching {app_name} with command: {command[:100]}..."
        )

        # Execute in terminal
        return self._execute_in_terminal(command, env)

    def _build_app_command(
        self,
        app_name: str,
        shot: Shot | None,
        scene: ThreeDEScene | None,
        options: dict[str, bool | str | list[str]],
    ) -> str:
        """Build the command line for launching an application.

        This consolidates the logic from the massive launch_app method.
        """
        base_command = Config.APPS[app_name]
        command_parts = [base_command]

        # Handle app-specific options
        if app_name == "3de":
            if scene and scene.scene_path:
                # Open specific scene
                command_parts.append(f"-open {self._quote_path(scene.scene_path)}")
            elif options.get("open_latest") and shot:
                # Find and open latest 3DE scene
                latest = self._find_latest_scene(shot.workspace_path, "3de")
                if latest:
                    command_parts.append(f"-open {self._quote_path(latest)}")

        elif app_name == "nuke":
            # Nuke command building is now handled in launch_vfx_app
            # This clause is kept for consistency but returns base command
            return base_command

        elif app_name == "maya":
            if options.get("open_latest") and shot:
                # Find and open latest Maya scene
                latest = self._find_latest_scene(shot.workspace_path, "maya")
                if latest:
                    command_parts.append(f"-file {self._quote_path(latest)}")

        elif app_name == "rv":
            # RV can work without shot context
            files = options.get("files")
            if files and isinstance(files, list):
                command_parts.extend([self._quote_path(file) for file in files])

        return " ".join(command_parts)

    def _get_app_environment(self, _app_name: str, shot: Shot | None) -> dict[str, str]:
        """Get environment variables for launching an application."""
        env: dict[str, str] = {}

        # Set shot context if available
        if shot:
            env["SHOT"] = shot.full_name
            env["SHOT_WORKSPACE"] = str(shot.workspace_path)
            env["SHOW"] = shot.show

        # App-specific environment
        # Note: Nuke environment is now handled directly in launch_vfx_app
        # using NukeLaunchHandler.get_environment_fixes()

        return env

    # ========== Workspace Command Execution ==========

    def execute_ws_command(
        self,
        command: str = "ws -sg",
        cache: bool = True,
        timeout: int = 30,
    ) -> str:
        """Execute workspace command with 30-minute TTL cache.

        Args:
            command: Command to execute (default: "ws -sg")
            cache: Whether to use cache (default: True)
            timeout: Command timeout in seconds (default: 30)

        Returns:
            Command output as string
        """
        # Check cache first
        if cache:
            cached = self._cache_get(command)
            if cached is not None:
                self.logger.debug(f"Cache hit for command: {command}")
                return cached

        self.logger.info(f"Executing workspace command: {command}")

        try:
            # Execute with interactive bash (required for ws function)
            result = subprocess.run(
                ["/bin/bash", "-i", "-c", command],
                check=False, capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode != 0:
                self.logger.error(f"Command failed: {result.stderr}")
                return ""

            output = result.stdout

            # Cache the result
            if cache and output:
                self._cache_set(command, output)
                self.logger.debug(f"Cached result for {command} (30 min TTL)")

            return output

        except subprocess.TimeoutExpired:
            self.logger.error(f"Command timed out after {timeout}s: {command}")
            return ""
        except Exception as e:
            self.logger.error(f"Failed to execute command: {e}")
            return ""

    # ========== Custom Launcher Support ==========

    def launch_custom_command(
        self,
        command: str,
        name: str = "Custom",
        environment: dict[str, str] | None = None,
        use_terminal: bool = True,
    ) -> bool:
        """Launch a custom user-defined command.

        Args:
            command: Command to execute
            name: Display name for the command
            environment: Additional environment variables
            use_terminal: Whether to show in terminal

        Returns:
            True if launch was successful
        """
        timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
        self.command_executed.emit(timestamp, f"Launching {name}: {command}")

        env = environment or {}

        if use_terminal:
            return self._execute_in_terminal(command, env)
        return self._execute_background(command, env)

    # ========== Terminal Execution ==========

    def _execute_in_terminal(self, command: str, env: dict[str, str]) -> bool:
        """Execute command in a visible terminal window.

        This method is thread-safe and handles:
        - Terminal emulator detection and selection
        - Environment variable merging
        - Process tracking and cleanup
        - Signal emission for command execution status

        Args:
            command: Shell command to execute
            env: Environment variables to set for the process

        Returns:
            True if command was successfully started in terminal,
            False if terminal launch failed.

        Thread Safety:
            Thread-safe through _process_lock for process tracking.
            Multiple threads can call this concurrently.

        Raises:
            No exceptions raised - all errors logged and return False.
        """
        proc = None  # Track process for cleanup in case of errors
        try:
            # Determine terminal emulator
            terminal_cmd = self._get_terminal_command(command)

            # Merge environment
            full_env = {**os.environ, **env}

            # Launch process
            proc = subprocess.Popen(
                terminal_cmd,
                env=full_env,
                start_new_session=True,
                text=True,
            )

            # Track process (thread-safe)
            with self._process_lock:
                self._active_processes[proc.pid] = proc
            self.process_started.emit(command, proc.pid)

            self.logger.info(f"Launched process {proc.pid}: {command[:50]}...")
            return True

        except FileNotFoundError as e:
            error_msg = (
                f"Terminal emulator not found: {e}. "
                f"Please install a supported terminal (gnome-terminal, konsole, xterm)."
            )
            self.logger.error(error_msg)
            self._emit_error(error_msg)
            # Clean up proc if created but not tracked
            if proc is not None:
                try:
                    proc.kill()
                    proc.close()  # pyright: ignore[reportAttributeAccessIssue]
                except Exception:
                    pass
            return False
        except Exception as e:
            error_msg = f"Failed to launch command in terminal: {e}"
            self.logger.error(error_msg)
            self._emit_error(error_msg)
            # Clean up proc if created but not tracked
            if proc is not None:
                try:
                    proc.kill()
                    proc.close()  # pyright: ignore[reportAttributeAccessIssue]
                except Exception:
                    pass
            return False

    def _execute_background(self, command: str, env: dict[str, str]) -> bool:
        """Execute command in background (no terminal)."""
        try:
            full_env = {**os.environ, **env}

            proc = subprocess.Popen(
                command,
                shell=True,
                env=full_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                text=True,
            )

            # Track process (thread-safe)
            with self._process_lock:
                self._active_processes[proc.pid] = proc
            self.process_started.emit(command, proc.pid)

            return True

        except Exception as e:
            self.logger.error(f"Failed to launch in background: {e}")
            return False

    def _get_terminal_command(self, command: str) -> list[str]:
        """Get the terminal emulator command for the current system.

        Uses EnvironmentManager for consistent terminal detection.

        Args:
            command: The command to execute in the terminal

        Returns:
            List of command arguments for subprocess.Popen
        """
        # Use EnvironmentManager to detect available terminal
        terminal = self.env_manager.detect_terminal()

        if terminal == "gnome-terminal":
            return ["gnome-terminal", "--", "bash", "-c", command]
        if terminal == "konsole":
            return ["konsole", "-e", "bash", "-c", command]
        if terminal == "xterm":
            return ["xterm", "-e", "bash", "-c", command]
        if terminal == "x-terminal-emulator":
            return ["x-terminal-emulator", "-e", "bash", "-c", command]
        # Fallback to direct execution if no terminal found
        self.logger.warning("No terminal emulator found, executing directly")
        return ["bash", "-c", command]

    # ========== Helper Methods ==========

    def _find_latest_scene(
        self, workspace_path: Path | str, app_type: str
    ) -> Path | None:
        """Find the latest scene file for a given application type."""
        workspace = Path(workspace_path)

        # Special handling for Nuke - use VFX workspace structure
        if app_type == "nuke" and self.current_shot:
            return self._find_latest_nuke_workspace_script(workspace)

        # Special handling for Maya - use MayaLatestFinder for correct path structure
        if app_type == "maya":
            maya_finder = MayaLatestFinder()
            shot_name = self.current_shot.full_name if self.current_shot else None
            return maya_finder.find_latest_maya_scene(str(workspace), shot_name)

        # Generic handling for other applications (3DE)
        patterns = {
            "3de": ("3de", "*.3de"),
            "nuke": ("nuke", "*.nk"),  # Fallback for non-workspace Nuke files
        }

        if app_type not in patterns:
            return None

        subdir, pattern = patterns[app_type]
        search_dir = workspace / subdir

        if not search_dir.exists():
            return None

        # Find all matching files
        files = list(search_dir.glob(f"**/{pattern}"))

        if not files:
            return None

        # Return most recent file
        return max(files, key=lambda f: f.stat().st_mtime)

    def _find_latest_nuke_workspace_script(self, workspace_path: Path) -> Path | None:
        """Find the latest Nuke script in VFX workspace structure.

        DEPRECATED: This method is replaced by NukeLaunchHandler's workspace management.
        Kept only for backward compatibility if needed.
        """
        # Delegate to NukeLaunchHandler's workspace manager
        if not self.current_shot:
            return None

        script_dir = self.nuke_handler.workspace_manager.get_workspace_script_directory(
            str(workspace_path)
        )
        return self.nuke_handler.workspace_manager.find_latest_nuke_script(
            script_dir, self.current_shot.full_name
        )

    # ========== Cache Management ==========

    def _cache_get(self, command: str) -> str | None:
        """Get cached result if still valid (thread-safe).

        Args:
            command: Command to look up in cache

        Returns:
            Cached result if valid, None if cache miss or expired
        """
        with self._cache_lock:
            if command not in self._ws_cache:
                self.logger.debug(f"Cache miss for command: {command[:50]}...")
                return None

            result, timestamp = self._ws_cache[command]

            # Check if cache is still valid (30 minutes)
            age = time.time() - timestamp
            if age < self._ws_cache_ttl:
                self.logger.debug(f"Cache hit for command: {command[:50]}... (age: {age:.1f}s)")
                return result

            # Cache expired
            del self._ws_cache[command]
            self.logger.debug(f"Cache expired for command: {command[:50]}... (age: {age:.1f}s)")
            return None

    def _cache_set(self, command: str, result: str) -> None:
        """Cache a workspace command result (thread-safe).

        Args:
            command: Command that was executed
            result: Command output to cache
        """
        with self._cache_lock:
            self._ws_cache[command] = (result, time.time())
            self.logger.debug(f"Cached result for command: {command[:50]}... (TTL: {self._ws_cache_ttl}s)")

    def clear_cache(self) -> None:
        """Clear the workspace command cache (thread-safe)."""
        with self._cache_lock:
            self._ws_cache.clear()
        self.logger.info("Cleared workspace command cache")

    # ========== Process Management ==========

    def cleanup_processes(self) -> None:
        """Clean up finished processes from tracking (thread-safe)."""
        finished_pids: list[int] = []

        # Snapshot under lock
        with self._process_lock:
            processes_snapshot = list(self._active_processes.items())

        # Check processes outside lock (poll() could block)
        for pid, proc in processes_snapshot:
            poll = proc.poll()
            if poll is not None:
                finished_pids.append(pid)
                # Safely handle proc.args (could be list or string)
                try:
                    if isinstance(proc.args, list):
                        cmd_str = " ".join(str(arg) for arg in proc.args)
                    else:
                        cmd_str = str(proc.args)
                    self.process_finished.emit(cmd_str[:50], poll)
                except Exception:
                    self.process_finished.emit(f"PID {pid}", poll)

        # Remove finished processes under lock
        if finished_pids:
            with self._process_lock:
                for pid in finished_pids:
                    if pid in self._active_processes:
                        proc = self._active_processes[pid]
                        del self._active_processes[pid]
                        # Close subprocess to release file descriptors
                        try:
                            proc.close()  # pyright: ignore[reportAttributeAccessIssue]
                        except Exception:
                            pass
            self.logger.debug(f"Cleaned up {len(finished_pids)} finished processes")

    def terminate_all_processes(self) -> None:
        """Terminate all active processes with SIGKILL fallback (thread-safe).

        Uses two-phase termination:
        1. Send SIGTERM to all processes (graceful)
        2. Wait _SIGTERM_WAIT_SECONDS
        3. Send SIGKILL to any remaining processes (forced)
        """
        # Snapshot under lock
        with self._process_lock:
            processes_snapshot = list(self._active_processes.items())

        if not processes_snapshot:
            self.logger.debug("No active processes to terminate")
            return

        self.logger.info(f"Terminating {len(processes_snapshot)} active processes")

        # First attempt: graceful termination (SIGTERM)
        for pid, proc in processes_snapshot:
            try:
                proc.terminate()
                self.logger.info(f"Sent SIGTERM to process {pid}")
            except Exception as e:
                self.logger.warning(f"Failed to terminate process {pid}: {e}")

        # Wait briefly for graceful termination
        time.sleep(_SIGTERM_WAIT_SECONDS)

        # Second attempt: force kill any remaining processes (SIGKILL)
        killed_count = 0
        for pid, proc in processes_snapshot:
            if proc.poll() is None:  # Still running
                try:
                    proc.kill()
                    killed_count += 1
                    self.logger.info(f"Sent SIGKILL to process {pid}")
                except Exception as e:
                    self.logger.warning(f"Failed to kill process {pid}: {e}")

        if killed_count > 0:
            self.logger.info(f"Force killed {killed_count} processes that didn't respond to SIGTERM")

        # Clear tracking dictionary under lock
        with self._process_lock:
            for proc in self._active_processes.values():
                try:
                    proc.close()  # pyright: ignore[reportAttributeAccessIssue]
                except Exception:
                    pass
            self._active_processes.clear()

        self.logger.info("Process termination complete")

    # ========== Utility Methods ==========

    def _quote_path(self, path: Path | str) -> str:
        """Quote a file path for shell execution."""
        path_str = str(path)

        # Check for shell-unsafe characters
        if any(c in path_str for c in [" ", "'", '"', "$", "&", "|", ";", "(", ")"]):
            # Use single quotes and escape any single quotes in the path
            # In bash, to include a single quote in a single-quoted string, you need to:
            # end the quote, add an escaped single quote, then start the quote again
            escaped = path_str.replace("'", "'\\''")
            return f"'{escaped}'"

        return path_str

    def _command_exists(self, command: str) -> bool:
        """Check if a command exists on the system.

        Returns:
            True if command exists (which returns exit code 0), False otherwise
        """
        try:
            result = subprocess.run(
                ["which", command],
                capture_output=True,
                check=False,
            )
            # Fix: Check exit code instead of always returning True
            # which returns 0 if command found, non-zero if not found
            return result.returncode == 0
        except Exception:
            return False

    def _emit_error(self, error: str) -> None:
        """Emit an error signal with timestamp."""
        timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
        self.command_error.emit(timestamp, error)
        self.logger.error(error)

    # ========== ProcessPoolInterface Implementation ==========

    def batch_execute(
        self,
        commands: list[str],
        _cache_ttl: int = 30,
        _session_type: str = "workspace",
    ) -> dict[str, str | None]:
        """Execute multiple commands in parallel.

        Implementation for ProcessPoolInterface protocol.
        """
        results: dict[str, str | None] = {}
        for command in commands:
            try:
                result = self.execute_ws_command(command, cache=True, timeout=30)
                results[command] = result
            except Exception as e:
                self.logger.error(f"Failed to execute {command}: {e}")
                results[command] = None
        return results

    def invalidate_cache(self, pattern: str | None = None) -> None:
        """Invalidate command cache.

        Implementation for ProcessPoolInterface protocol.
        """
        if pattern:
            # Remove entries matching pattern
            keys_to_remove = [k for k in self._ws_cache if pattern in k]
            for key in keys_to_remove:
                del self._ws_cache[key]
            self.logger.info(
                f"Invalidated {len(keys_to_remove)} cache entries matching '{pattern}'"
            )
        else:
            # Clear all
            self.clear_cache()

    def shutdown(self) -> None:
        """Shutdown the process pool.

        Implementation for ProcessPoolInterface protocol.
        """
        self.terminate_all_processes()
        self.clear_cache()
        self.logger.info("SimplifiedLauncher shutdown complete")

    def get_metrics(self) -> dict[str, int]:
        """Get performance metrics.

        Implementation for ProcessPoolInterface protocol.
        """
        return {
            "cache_size": len(self._ws_cache),
            "active_processes": len(self._active_processes),
            "cache_ttl_seconds": self._ws_cache_ttl,
        }

    # ========== Test Isolation ==========

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing. INTERNAL USE ONLY.

        This method clears all state and resets the launcher instance.
        It should only be used in test cleanup to ensure test isolation.

        Note: SimplifiedLauncher is not a true singleton (multiple instances allowed),
        but this method is provided for consistency with project conventions and to
        support test cleanup patterns.

        Per CLAUDE.md guidelines, all singleton-like classes should implement this
        method for test isolation, even if they don't maintain class-level state.
        Tests should create fresh instances rather than reusing/resetting existing ones.

        TODO: Add tests for:
          - Thread-safe cache operations under concurrent access
          - Process cleanup during shutdown
          - Two-phase termination (SIGTERM → SIGKILL)
          - EnvironmentManager integration for terminal detection
          - Resource cleanup in error paths (_execute_in_terminal)
        """
        # SimplifiedLauncher doesn't use class-level state, only instance state.
        # Instance cleanup is handled via terminate_all_processes() and clear_cache()
        # which should be called explicitly when shutting down an instance.

    # ========== Backward Compatibility ==========

    def launch_app_with_scene(self, app_name: str, scene: ThreeDEScene) -> bool:
        """Launch app with scene context (backward compatibility)."""
        return self.launch_vfx_app(app_name, scene=scene)

    def launch_app(
        self,
        app_name: str,
        include_raw_plate: bool = False,
        open_latest_threede: bool = False,
        open_latest_maya: bool = False,
        open_latest_scene: bool = False,
        create_new_file: bool = False,
    ) -> bool:
        """Launch app with options (backward compatibility)."""
        options = {
            "include_plate": include_raw_plate,
            "open_latest": open_latest_threede or open_latest_maya or open_latest_scene,
            "create_new": create_new_file,
        }
        # Don't pass shot/scene as they conflict with method signature
        return self.launch_vfx_app(app_name, shot=None, scene=None, **options)
