"""QProcess-based command launcher for executing applications in shot context.

This module provides a QProcess-based replacement for CommandLauncher that
offers better integration with Qt's event loop, improved resource management,
and non-blocking execution capabilities.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from qprocess_manager import ProcessState, QProcessManager

from config import Config
from raw_plate_finder import RawPlateFinder
from shot_model import Shot
from threede_scene_model import ThreeDEScene
from undistortion_finder import UndistortionFinder

logger = logging.getLogger(__name__)


class CommandLauncherWorker(QThread):
    """Worker thread for non-blocking command execution."""

    # Signals
    execution_started = Signal(str, str)  # timestamp, description
    execution_progress = Signal(str, str)  # timestamp, message
    execution_completed = Signal(str, bool)  # timestamp, success
    execution_error = Signal(str, str)  # timestamp, error

    def __init__(
        self,
        process_manager: QProcessManager,
        command: str,
        workspace_path: str,
        description: str = "",
        terminal: bool = True,
        terminal_persist: bool = False,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.process_manager = process_manager
        self.command = command
        self.workspace_path = workspace_path
        self.description = description
        self.terminal = terminal
        self.terminal_persist = terminal_persist
        self._process_id: Optional[str] = None

    def run(self):
        """Execute the command in this thread."""
        timestamp = datetime.now().strftime("%H:%M:%S")

        try:
            # Emit start signal
            self.execution_started.emit(timestamp, self.description or self.command)

            # Execute command with workspace setup
            self._process_id = self.process_manager.execute_ws_command(
                workspace_path=self.workspace_path,
                command=self.command,
                terminal=self.terminal,
                capture_output=not self.terminal,
                timeout_ms=0,  # No timeout for interactive apps
                process_id=f"cmd_{timestamp.replace(':', '')}_{id(self)}",
            )

            if not self._process_id:
                self.execution_error.emit(
                    datetime.now().strftime("%H:%M:%S"), "Failed to start command"
                )
                self.execution_completed.emit(
                    datetime.now().strftime("%H:%M:%S"), False
                )
                return

            # If not terminal mode, wait for completion
            if not self.terminal:
                process_info = self.process_manager.wait_for_process(
                    self._process_id,
                    timeout_ms=300000,  # 5 minute timeout for non-terminal
                )

                if process_info:
                    success = process_info.state == ProcessState.FINISHED
                    if not success and process_info.error:
                        self.execution_error.emit(
                            datetime.now().strftime("%H:%M:%S"), process_info.error
                        )
                else:
                    success = False
                    self.execution_error.emit(
                        datetime.now().strftime("%H:%M:%S"), "Process timeout"
                    )
            else:
                # Terminal processes are considered successful if launched
                success = True

            self.execution_completed.emit(datetime.now().strftime("%H:%M:%S"), success)

        except Exception as e:
            logger.exception(f"Error in command launcher worker: {e}")
            self.execution_error.emit(datetime.now().strftime("%H:%M:%S"), str(e))
            self.execution_completed.emit(datetime.now().strftime("%H:%M:%S"), False)

    def stop(self):
        """Stop the command if running."""
        if self._process_id:
            self.process_manager.terminate_process(self._process_id)
        self.quit()
        self.wait()


class CommandLauncherQProcess(QObject):
    """QProcess-based command launcher for shot context execution.

    Drop-in replacement for CommandLauncher with improved process management
    and non-blocking execution capabilities.
    """

    # Signals (backward compatible)
    command_executed = Signal(str, str)  # timestamp, command
    command_error = Signal(str, str)  # timestamp, error

    # New signals for async operations
    launch_started = Signal(str)  # app_name
    launch_completed = Signal(str, bool)  # app_name, success
    launch_progress = Signal(str, str)  # app_name, message

    def __init__(self, process_manager: Optional[QProcessManager] = None):
        super().__init__()
        self.process_manager = process_manager or QProcessManager()
        self.current_shot: Optional[Shot] = None
        self._active_workers: list[CommandLauncherWorker] = []

    def set_current_shot(self, shot: Optional[Shot]):
        """Set the current shot context."""
        self.current_shot = shot

    def launch_app(
        self,
        app_name: str,
        include_undistortion: bool = False,
        include_raw_plate: bool = False,
        blocking: bool = False,
    ) -> bool:
        """Launch an application in the current shot context.

        Args:
            app_name: Name of the application to launch
            include_undistortion: Whether to include undistortion nodes (Nuke only)
            include_raw_plate: Whether to include raw plate Read node (Nuke only)
            blocking: If True, wait for completion (backward compatibility)

        Returns:
            True if launch was successful/started, False otherwise
        """
        if not self.current_shot:
            self._emit_error("No shot selected")
            return False

        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Build command
        command = Config.APPS[app_name]
        command_parts = [command]

        # Handle raw plate and undistortion for Nuke (integrated approach)
        if app_name == "nuke" and (include_raw_plate or include_undistortion):
            raw_plate_path = None
            undistortion_path = None

            # Get raw plate if requested
            if include_raw_plate:
                raw_plate_path = self._find_raw_plate(
                    self.current_shot.workspace_path, self.current_shot.full_name
                )

            # Get undistortion if requested
            if include_undistortion:
                undistortion_path = self._find_undistortion(
                    self.current_shot.workspace_path, self.current_shot.full_name
                )

            # Generate integrated Nuke script if we have plate or undistortion
            if raw_plate_path or undistortion_path:
                from nuke_script_generator import NukeScriptGenerator

                if raw_plate_path and undistortion_path:
                    # Both plate and undistortion
                    script_path = (
                        NukeScriptGenerator.create_plate_script_with_undistortion(
                            raw_plate_path,
                            str(undistortion_path),
                            self.current_shot.full_name,
                        )
                    )
                    if script_path:
                        command_parts.append(script_path)
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        self.command_executed.emit(
                            timestamp,
                            "Generated integrated Nuke script with plate and undistortion",
                        )
                elif raw_plate_path:
                    # Plate only
                    script_path = NukeScriptGenerator.create_plate_script(
                        raw_plate_path, self.current_shot.full_name
                    )
                    if script_path:
                        command_parts.append(script_path)
                elif undistortion_path:
                    # Undistortion only
                    script_path = (
                        NukeScriptGenerator.create_plate_script_with_undistortion(
                            "", str(undistortion_path), self.current_shot.full_name
                        )
                    )
                    if script_path:
                        command_parts.append(script_path)

        # Build full command
        full_command = " ".join(command_parts)

        # Log the command
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_executed.emit(timestamp, full_command)

        if blocking:
            # Synchronous execution for backward compatibility
            return self._launch_blocking(
                full_command,
                self.current_shot.workspace_path,
                f"Launching {app_name} for {self.current_shot.full_name}",
            )
        else:
            # Asynchronous execution
            self._launch_async(
                app_name,
                full_command,
                self.current_shot.workspace_path,
                f"Launching {app_name} for {self.current_shot.full_name}",
            )
            return True

    def launch_app_with_scene(
        self, app_name: str, scene: ThreeDEScene, blocking: bool = False
    ) -> bool:
        """Launch an application with a specific 3DE scene file.

        Args:
            app_name: Name of the application to launch
            scene: The 3DE scene to open
            blocking: If True, wait for completion

        Returns:
            True if launch was successful/started, False otherwise
        """
        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Build command with scene file
        command = f"{Config.APPS[app_name]} {scene.scene_path}"

        # Log the command
        timestamp = datetime.now().strftime("%H:%M:%S")
        description = f"Scene by: {scene.user}, Plate: {scene.plate}"
        self.command_executed.emit(timestamp, f"{command} ({description})")

        if blocking:
            return self._launch_blocking(
                command,
                scene.workspace_path,
                f"Launching {app_name} with {scene.plate} scene",
            )
        else:
            self._launch_async(
                app_name,
                command,
                scene.workspace_path,
                f"Launching {app_name} with {scene.plate} scene",
            )
            return True

    def launch_app_with_scene_context(
        self,
        app_name: str,
        scene: ThreeDEScene,
        include_undistortion: bool = False,
        include_raw_plate: bool = False,
        blocking: bool = False,
    ) -> bool:
        """Launch an application in the context of a 3DE scene.

        Args:
            app_name: Name of the application to launch
            scene: The 3DE scene providing shot context
            include_undistortion: Whether to include undistortion nodes
            include_raw_plate: Whether to include raw plate Read node
            blocking: If True, wait for completion

        Returns:
            True if launch was successful/started, False otherwise
        """
        if app_name not in Config.APPS:
            self._emit_error(f"Unknown application: {app_name}")
            return False

        # Build command
        command = Config.APPS[app_name]
        command_parts = [command]

        # Handle raw plate and undistortion for Nuke (integrated approach)
        if app_name == "nuke" and (include_raw_plate or include_undistortion):
            raw_plate_path = None
            undistortion_path = None

            # Get raw plate if requested
            if include_raw_plate:
                raw_plate_path = self._find_raw_plate(
                    scene.workspace_path, scene.full_name
                )

            # Get undistortion if requested
            if include_undistortion:
                undistortion_path = self._find_undistortion(
                    scene.workspace_path, scene.full_name
                )

            # Generate integrated Nuke script if we have plate or undistortion
            if raw_plate_path or undistortion_path:
                from nuke_script_generator import NukeScriptGenerator

                if raw_plate_path and undistortion_path:
                    # Both plate and undistortion
                    script_path = (
                        NukeScriptGenerator.create_plate_script_with_undistortion(
                            raw_plate_path, str(undistortion_path), scene.full_name
                        )
                    )
                    if script_path:
                        command_parts.append(script_path)
                elif raw_plate_path:
                    # Plate only
                    script_path = NukeScriptGenerator.create_plate_script(
                        raw_plate_path, scene.full_name
                    )
                    if script_path:
                        command_parts.append(script_path)
                elif undistortion_path:
                    # Undistortion only
                    script_path = (
                        NukeScriptGenerator.create_plate_script_with_undistortion(
                            "", str(undistortion_path), scene.full_name
                        )
                    )
                    if script_path:
                        command_parts.append(script_path)

        # Build full command
        full_command = " ".join(command_parts)

        # Log the command
        timestamp = datetime.now().strftime("%H:%M:%S")
        description = f"Context: {scene.user}'s {scene.plate}"
        self.command_executed.emit(timestamp, f"{full_command} ({description})")

        if blocking:
            return self._launch_blocking(
                full_command,
                scene.workspace_path,
                f"Launching {app_name} in {scene.plate} context",
            )
        else:
            self._launch_async(
                app_name,
                full_command,
                scene.workspace_path,
                f"Launching {app_name} in {scene.plate} context",
            )
            return True

    def launch_app_async(
        self,
        app_name: str,
        include_undistortion: bool = False,
        include_raw_plate: bool = False,
    ) -> None:
        """Launch an application asynchronously.

        This method starts the launch in the background and returns immediately.
        Connect to the launch_completed signal to be notified when done.
        """
        self.launch_app(
            app_name, include_undistortion, include_raw_plate, blocking=False
        )

    def _launch_blocking(
        self, command: str, workspace_path: str, description: str
    ) -> bool:
        """Execute a command synchronously."""
        try:
            # Execute with workspace setup
            process_id = self.process_manager.execute_ws_command(
                workspace_path=workspace_path,
                command=command,
                terminal=True,  # Always use terminal for VFX apps
                capture_output=False,
                timeout_ms=0,  # No timeout for interactive apps
            )

            return process_id is not None

        except Exception as e:
            self._emit_error(f"Failed to launch: {str(e)}")
            return False

    def _launch_async(
        self, app_name: str, command: str, workspace_path: str, description: str
    ):
        """Execute a command asynchronously using a worker thread."""
        # Clean up finished workers
        self._cleanup_finished_workers()

        # Create worker
        worker = CommandLauncherWorker(
            self.process_manager,
            command,
            workspace_path,
            description,
            terminal=True,  # Always use terminal for VFX apps
            parent=self,
        )

        # Connect signals
        worker.execution_started.connect(
            lambda ts, desc: self.launch_started.emit(app_name)
        )
        worker.execution_progress.connect(
            lambda ts, msg: self.launch_progress.emit(app_name, msg)
        )
        worker.execution_completed.connect(
            lambda ts, success: self._on_launch_completed(app_name, success)
        )
        worker.execution_error.connect(self.command_error.emit)

        # Store and start worker
        self._active_workers.append(worker)
        worker.start()

    def _on_launch_completed(self, app_name: str, success: bool):
        """Handle launch completion."""
        self.launch_completed.emit(app_name, success)
        # Schedule cleanup
        QThread.msleep(100)
        self._cleanup_finished_workers()

    def _cleanup_finished_workers(self):
        """Clean up finished worker threads."""
        finished = []
        for worker in self._active_workers:
            if worker.isFinished():
                finished.append(worker)
                worker.deleteLater()

        for worker in finished:
            self._active_workers.remove(worker)

    def _find_raw_plate(self, workspace_path: str, full_name: str) -> Optional[str]:
        """Find raw plate path and emit appropriate messages."""
        raw_plate_path = RawPlateFinder.find_latest_raw_plate(workspace_path, full_name)

        if raw_plate_path:
            if RawPlateFinder.verify_plate_exists(raw_plate_path):
                version = RawPlateFinder.get_version_from_path(raw_plate_path)
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.command_executed.emit(
                    timestamp,
                    f"Found raw plate: {version}/{raw_plate_path.split('/')[-1]}",
                )
                return raw_plate_path
            else:
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.command_executed.emit(
                    timestamp, "Warning: Raw plate path found but no frames exist"
                )
        else:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.command_executed.emit(
                timestamp, "Warning: Raw plate not found for this shot"
            )

        return None

    def _find_undistortion(self, workspace_path: str, full_name: str) -> Optional[Path]:
        """Find undistortion file and emit appropriate messages."""
        undistortion_path = UndistortionFinder.find_latest_undistortion(
            workspace_path, full_name
        )

        if undistortion_path:
            version = UndistortionFinder.get_version_from_path(undistortion_path)
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.command_executed.emit(
                timestamp,
                f"Found undistortion file: {version}/{undistortion_path.name}",
            )
            return undistortion_path
        else:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.command_executed.emit(
                timestamp, "Warning: Undistortion file not found for this shot"
            )
            return None

    def _emit_error(self, error: str):
        """Emit error with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.command_error.emit(timestamp, error)

    def cancel_all(self):
        """Cancel all active launches."""
        for worker in self._active_workers:
            if worker.isRunning():
                worker.stop()
        self._active_workers.clear()

    def cleanup(self):
        """Clean up resources."""
        self.cancel_all()
        if self.process_manager:
            self.process_manager.shutdown()
