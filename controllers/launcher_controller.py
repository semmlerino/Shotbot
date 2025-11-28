"""Application launcher controller for MainWindow refactoring.

Manages all application launching functionality including regular apps,
scene-based launching, custom launchers, and launch options management.

This controller extracts all launcher-related functionality from MainWindow into
a focused, testable component. It handles:
- Application launching with shot vs scene context
- Launch options management from UI checkboxes
- Custom launcher execution and menu management
- Status updates and notifications
- Progress tracking for launcher operations
"""

from __future__ import annotations

# Standard library imports
from typing import TYPE_CHECKING, Any, Protocol, cast

# Third-party imports
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QMessageBox, QWidget


if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtWidgets import QStatusBar, QWidget

    # Local application imports
    from command_launcher import CommandLauncher
    from launcher.models import CustomLauncher
    from launcher_dialog import LauncherManagerDialog
    from launcher_manager import LauncherManager
    from log_viewer import LogViewer
    from right_panel import RightPanelWidget
    from scene_file import SceneFile
    from shot_model import Shot
    from threede_scene_model import ThreeDEScene

# Runtime imports (needed at runtime)
from datetime import UTC, datetime

from command_launcher import CommandLauncher, LaunchContext
from logging_mixin import LoggingMixin
from notification_manager import NotificationManager, NotificationType
from progress_manager import ProgressManager
from shot_model import Shot


class LauncherTarget(Protocol):
    """Protocol defining the interface required by LauncherController."""

    command_launcher: CommandLauncher
    launcher_manager: LauncherManager | None
    right_panel: RightPanelWidget
    log_viewer: LogViewer
    status_bar: QStatusBar
    custom_launcher_menu: QMenu

    def update_status(self, message: str) -> None:
        """Update status bar with a message."""
        ...


class LauncherController(LoggingMixin):
    """Controller for application launching functionality.

    This controller encapsulates all launcher-related functionality that was previously
    part of MainWindow, providing clean separation of concerns and improved
    testability. It manages:
    - Application launching with different contexts (shot vs scene)
    - Launch options management from UI checkboxes
    - Custom launcher execution and menu management
    - Status updates and progress notifications
    - Launcher dialog management

    Attributes:
        window: The target window that implements LauncherTarget protocol
        logger: Logger instance for this controller
        _current_scene: Currently selected 3DE scene (for scene context launching)
        _current_shot: Currently selected shot (for shot context launching)
        _launcher_dialog: Dialog for managing custom launchers
    """

    def __init__(self, window: LauncherTarget) -> None:
        """Initialize the launcher controller.

        Args:
            window: MainWindow implementing LauncherTarget protocol
        """
        super().__init__()
        self.window: LauncherTarget = window

        # Context tracking
        self._current_scene: ThreeDEScene | None = None
        self._current_shot: Shot | None = None

        # UI state
        self._launcher_dialog: LauncherManagerDialog | None = None

        # Setup signal connections
        self._setup_signals()

        self.logger.info(f"🎮 LauncherController initialized (id={id(self)})")

    def _setup_signals(self) -> None:
        """Setup signal connections for launcher functionality."""
        # Connect right panel signals
        # Note: launch_requested emits (app_name: str, options: dict). Options may
        # contain selected_file from Files panel selection.
        self.logger.info(f"🔌 Connecting launch_requested signal (controller id={id(self)})")
        _ = self.window.right_panel.launch_requested.connect(self._on_launch_requested)
        self.logger.info(f"✓ launch_requested connected to {id(self)}._on_launch_requested")
        # Note: Custom launchers not yet implemented in new right panel

        # Connect command launcher signals
        _ = self.window.command_launcher.command_executed.connect(
            self.window.log_viewer.add_command
        )
        _ = self.window.command_launcher.command_error.connect(
            self.window.log_viewer.add_error
        )
        _ = self.window.command_launcher.command_error.connect(self._on_command_error)

        # Connect launcher manager signals (if available)
        if self.window.launcher_manager:
            _ = self.window.launcher_manager.launchers_changed.connect(
                self.update_launcher_menu
            )
            _ = self.window.launcher_manager.launchers_changed.connect(
                self.update_custom_launcher_buttons
            )
            _ = self.window.launcher_manager.execution_started.connect(
                self._on_launcher_started
            )
            _ = self.window.launcher_manager.execution_finished.connect(
                self._on_launcher_finished
            )

        self.logger.debug("Launcher signals connected")

    def _on_launch_requested(
        self, app_name: str, options: dict[str, Any]
    ) -> None:
        """Handle launch request from right panel.

        Extracts selected_file from options if present and passes to launch_app.

        Args:
            app_name: Application to launch
            options: Launch options, may include 'selected_file' SceneFile
        """
        selected_file = options.get("selected_file")
        self.launch_app(app_name, selected_file=selected_file)

    def set_current_shot(self, shot: Shot | None) -> None:
        """Set the current shot context for launching.

        When a shot is selected, the scene context is automatically cleared
        to maintain mutual exclusivity.

        Args:
            shot: Shot to set as current context, or None to clear
        """
        self._current_shot = shot
        # Clear scene context to maintain mutual exclusivity
        if shot:
            self._current_scene = None
            self.logger.info(
                f"🎯 Set current shot: {shot.full_name} (cleared scene context)"
            )
        else:
            self.logger.info("🎯 Cleared current shot")

        # Update command launcher context
        self.window.command_launcher.set_current_shot(shot)

    def set_current_scene(self, scene: ThreeDEScene | None) -> None:
        """Set the current 3DE scene context for launching.

        When a scene is selected, the shot context is automatically cleared
        to maintain mutual exclusivity.

        Args:
            scene: ThreeDEScene to set as current context, or None to clear
        """
        if scene:
            self.logger.info(
                f"🎬 LauncherController.set_current_scene() called with scene: {scene.full_name} (user: {scene.user}, path: {scene.scene_path})"
            )
            # Clear shot context to maintain mutual exclusivity
            self._current_shot = None
            self.window.command_launcher.set_current_shot(None)
        else:
            self.logger.info(
                "🎬 LauncherController.set_current_scene() called with None (clearing scene)"
            )

        self._current_scene = scene
        self.logger.info(
            f"✓ _current_scene is now: {self._current_scene.scene_path if self._current_scene else 'None'}"
        )

    def get_launch_options(self, app_name: str) -> dict[str, bool]:
        """Get app-specific launch options from checkbox states.

        Args:
            app_name: Name of the application being launched

        Returns:
            Dictionary of option names to boolean values
        """
        # Get options directly from right panel
        dcc_options = self.window.right_panel.get_dcc_options(app_name)
        if dcc_options is None:
            return {}

        # Filter to only include boolean options (exclude selected_plate)
        options: dict[str, bool] = {}
        for key, value in dcc_options.items():
            if isinstance(value, bool):
                options[key] = value

        return options

    def _validate_launch_context(self) -> bool:
        """Validate that we have necessary context for launching.

        Returns:
            True if context is valid, False otherwise
        """
        # Have scene or shot context - valid
        if self._current_scene or self._current_shot:
            return True

        # Try to sync context from command_launcher
        if self.window.command_launcher.current_shot:
            self._current_shot = self.window.command_launcher.current_shot
            self.logger.info(f"Re-synced context from command_launcher: {self._current_shot.full_name}")
            self._log_command(f"Re-synced shot context: {self._current_shot.full_name}")
            return True

        # No context available
        self.logger.error("No shot or scene context available for launch")
        self._log_error("No shot selected - please select a shot before launching")
        NotificationManager.warning(
            "No Shot Selected",
            "Please select a shot before launching applications.",
        )
        return False

    def _build_launch_options(self, app_name: str) -> dict[str, Any] | None:
        """Build launch options from UI state and validate.

        Args:
            app_name: Name of the application

        Returns:
            Dictionary of launch options, or None if validation failed
        """
        # Get app-specific options
        options = self.get_launch_options(app_name)

        # Extract individual options
        include_raw_plate = options.get("include_raw_plate", False)
        open_latest_threede = options.get("open_latest_threede", False)
        open_latest_maya = options.get("open_latest_maya", False)
        open_latest_scene = options.get("open_latest_scene", False)
        create_new_file = options.get("create_new_file", False)

        # Note: open_latest_scene takes priority if both are checked
        if open_latest_scene and create_new_file:
            create_new_file = False

        # Get and validate selected plate for Nuke (if applicable)
        selected_plate = None
        if app_name == "nuke":
            nuke_options = self.window.right_panel.get_dcc_options("nuke")
            selected_plate = nuke_options.get("selected_plate") if nuke_options else None

            # Validate plate selection for workspace operations
            if (open_latest_scene or create_new_file) and not selected_plate:
                self.logger.error("No plate selected for Nuke workspace operation")
                self._log_error(
                    "Please select a plate space before launching Nuke with workspace scripts"
                )
                NotificationManager.warning(
                    "No Plate Selected",
                    "Please select a plate space (e.g., FG01, BG01) before launching Nuke.",
                )
                return None

        return {
            "include_raw_plate": include_raw_plate,
            "open_latest_threede": open_latest_threede,
            "open_latest_maya": open_latest_maya,
            "open_latest_scene": open_latest_scene,
            "create_new_file": create_new_file,
            "selected_plate": selected_plate,
        }

    def _execute_launch_with_options(
        self, app_name: str, options: dict[str, Any]
    ) -> bool:
        """Execute launch with the given options.

        Args:
            app_name: Name of the application
            options: Launch options dictionary

        Returns:
            True if launch was successful, False otherwise
        """
        # Build launch context from options
        context = LaunchContext(
            include_raw_plate=options["include_raw_plate"],
            open_latest_threede=options["open_latest_threede"],
            open_latest_maya=options["open_latest_maya"],
            open_latest_scene=options["open_latest_scene"],
            create_new_file=options["create_new_file"],
            selected_plate=options.get("selected_plate"),
        )
        return self.window.command_launcher.launch_app(app_name, context)

    def launch_app(
        self,
        app_name: str,
        captured_shot: Shot | None = None,
        selected_file: SceneFile | None = None,
    ) -> None:
        """Launch an application.

        Args:
            app_name: Name of the application to launch
            captured_shot: Shot context captured at click time to prevent race conditions.
                          If None, falls back to current shot (for backwards compatibility).
            selected_file: Optional file selected from Files panel. If provided, launches
                          this specific file directly.
        """
        # Use captured shot if provided, otherwise fall back to current shot
        # This prevents race conditions where user switches shots during button reset window
        effective_shot = captured_shot if captured_shot is not None else self._current_shot

        # Validate launch context
        if not self._validate_launch_context():
            return

        # Priority 1: User-selected file from Files panel
        if selected_file is not None:
            self.logger.info(f"Using selected file: {selected_file.name}")
            success = self._launch_with_selected_file(app_name, selected_file)
        # Priority 2: Current 3DE scene from scene grid
        elif self._current_scene:
            self.logger.info(f"Using scene context: {self._current_scene.full_name}")
            # Launch with scene context
            if app_name == "3de":
                # For 3DE, use the scene file directly
                success = self._launch_app_with_scene(app_name, self._current_scene)
            else:
                # For other apps, launch in shot context with plate support
                success = self._launch_app_with_scene_context(
                    app_name,
                    self._current_scene,
                )
        else:
            # Shot context path
            self.logger.info("Using shot context (no scene selected)")
            self._log_command("Using shot context (no scene selected)")

            # Sync command_launcher context with captured shot
            if effective_shot:
                self.logger.info(
                    f"Using captured shot context: {effective_shot.full_name}"
                )
                self.window.command_launcher.set_current_shot(effective_shot)
                self._log_command(
                    f"Set shot context: {effective_shot.full_name}"
                )

            # Build and validate launch options
            options = self._build_launch_options(app_name)
            if options is None:
                return  # Validation failed

            # Execute launch
            success = self._execute_launch_with_options(app_name, options)

        # Update UI based on success (Phase 1: Don't show premature success)
        if success:
            # Only update status, don't show success notification yet
            # Notification will be shown when command_executed/command_verified signal arrives
            self.window.update_status(f"Launching {app_name}...")
            self.logger.info(f"Command queued for {app_name}, awaiting execution")
        else:
            # Show error notification immediately for sync failures
            self.window.update_status(f"Failed to launch {app_name}")
            NotificationManager.toast(
                f"Failed to launch {app_name}", NotificationType.ERROR
            )
            # Error details are handled by _on_command_error

    def _launch_app_with_scene(self, app_name: str, scene: ThreeDEScene) -> bool:
        """Launch an application with a specific 3DE scene.

        Args:
            app_name: Name of the application to launch
            scene: 3DE scene to open

        Returns:
            True if launch was successful, False otherwise
        """
        if self.window.command_launcher.launch_app_with_scene(app_name, scene):
            self.window.update_status(f"Launched {app_name} with {scene.user}'s scene")
            return True
        self.window.update_status(f"Failed to launch {app_name} with scene")
        return False

    def _launch_with_selected_file(
        self, app_name: str, scene_file: SceneFile
    ) -> bool:
        """Launch an application with a user-selected file from Files panel.

        Args:
            app_name: Name of the application to launch
            scene_file: SceneFile selected by user in Files panel

        Returns:
            True if launch was successful, False otherwise
        """
        from pathlib import Path

        # Get workspace path from current shot
        if not self._current_shot:
            self.logger.error("No shot context for selected file launch")
            return False

        workspace_path = self._current_shot.workspace_path

        # Launch using the file path
        file_path = Path(scene_file.path)
        if self.window.command_launcher.launch_with_file(
            app_name, file_path, workspace_path
        ):
            self.window.update_status(
                f"Launched {app_name} with {scene_file.name}"
            )
            return True
        self.window.update_status(f"Failed to launch {app_name} with file")
        return False

    def _launch_app_with_scene_context(
        self, app_name: str, scene: ThreeDEScene
    ) -> bool:
        """Launch an application in the context of a 3DE scene (without the scene file itself).

        Args:
            app_name: Name of the application to launch
            scene: 3DE scene providing the context

        Returns:
            True if launch was successful, False otherwise
        """
        # Check if we should include raw plate for Nuke
        include_raw_plate = False
        if app_name == "nuke":
            nuke_options = self.window.right_panel.get_dcc_options("nuke")
            include_raw_plate = bool(
                nuke_options and nuke_options.get("include_raw_plate", False)
            )

        # Launch with scene context
        return self.window.command_launcher.launch_app_with_scene_context(
            app_name,
            scene,
            include_raw_plate,
        )

    def execute_custom_launcher(self, launcher_id: str) -> None:
        """Execute a custom launcher.

        Args:
            launcher_id: ID of the custom launcher to execute
        """
        if not self.window.launcher_manager:
            return
        launcher = self.window.launcher_manager.get_launcher(launcher_id)
        if not launcher:
            self.window.update_status(f"Launcher not found: {launcher_id}")
            return

        # Check if we have a current scene selected
        if self._current_scene:
            # Create a Shot object from the scene for context
            shot = Shot(
                show=self._current_scene.show,
                sequence=self._current_scene.sequence,
                shot=self._current_scene.shot,
                workspace_path=self._current_scene.workspace_path,
            )
        else:
            # Get current shot
            current_shot = self.window.command_launcher.current_shot
            if not current_shot:
                self.window.update_status("No shot or scene selected")
                NotificationManager.warning(
                    "No Context Selected",
                    "Please select a shot or 3DE scene before launching custom commands.",
                )
                return
            shot = current_shot

        # Execute the launcher
        if not self.window.launcher_manager:
            return
        success = self.window.launcher_manager.execute_in_shot_context(
            launcher_id, shot
        )

        if success:
            self.window.update_status(f"Launched '{launcher.name}'")
            # Log the execution
            self._log_command(f"Custom launcher: {launcher.name}")
        else:
            self.window.update_status(f"Failed to launch '{launcher.name}'")
            self._log_error(
                f"Failed to launch custom launcher: {launcher.name}"
            )

    def update_custom_launcher_buttons(self) -> None:
        """Update the custom launcher buttons in the launcher panel.

        Note: Custom launchers not yet implemented in new right panel.
        """
        # Skip if using simplified launcher
        if not self.window.launcher_manager:
            return

        # Note: Custom launchers UI not yet implemented in RightPanelWidget
        # Get all launchers (for potential future use)
        _launchers = self.window.launcher_manager.list_launchers()
        self.logger.debug(f"Custom launchers available: {len(_launchers)}")

    def enable_custom_launcher_buttons(self, _enabled: bool) -> None:
        """Enable or disable all custom launcher buttons.

        Args:
            enabled: Whether to enable or disable the buttons
        """
        # Custom launcher buttons are now managed by the launcher panel
        # and automatically enabled/disabled when shot is set

    def show_launcher_manager(self) -> None:
        """Show the launcher manager dialog."""
        if not self.window.launcher_manager:
            _ = QMessageBox.information(
                cast(
                    "QWidget", cast("object", self.window)
                ),  # Cast through object for Protocol
                "Custom Launchers",
                ("Custom launchers are not available when using simplified launcher mode.\n"
                 "Set USE_SIMPLIFIED_LAUNCHER=false to use custom launchers.")
            )
            return

        if self._launcher_dialog is None:
            from launcher_dialog import LauncherManagerDialog

            self._launcher_dialog = LauncherManagerDialog(
                self.window.launcher_manager, cast("QWidget", cast("object", self.window))
            )

        # At this point, _launcher_dialog is guaranteed to be not None
        self._launcher_dialog.show()
        self._launcher_dialog.raise_()
        self._launcher_dialog.activateWindow()

    def update_launcher_menu(self) -> None:
        """Update the custom launcher menu with available launchers."""
        # Clear existing menu items
        self.window.custom_launcher_menu.clear()

        # Skip if using simplified launcher
        if not self.window.launcher_manager:
            return

        # Get all launchers grouped by category
        launchers = self.window.launcher_manager.list_launchers()

        if not launchers:
            # Add disabled placeholder
            no_launchers_action = QAction(
                "No custom launchers", cast("QWidget", cast("object", self.window))
            )
            no_launchers_action.setEnabled(False)
            self.window.custom_launcher_menu.addAction(no_launchers_action)
            return

        # Group by category
        categories: dict[str, list[CustomLauncher]] = {}
        for launcher in launchers:
            category = launcher.category or "custom"
            if category not in categories:
                categories[category] = []
            categories[category].append(launcher)

        # Add menu items
        for category in sorted(categories.keys()):
            category_launchers = categories[category]

            if len(categories) > 1:
                # Add category as submenu if multiple categories
                category_menu = self.window.custom_launcher_menu.addMenu(
                    category.title()
                )
                for launcher in category_launchers:
                    action = QAction(
                        launcher.name, cast("QWidget", cast("object", self.window))
                    )
                    action.setToolTip(launcher.description)
                    action.setData(launcher.id)
                    _ = action.triggered.connect(
                        lambda _=False,
                        lid=launcher.id: self.execute_custom_launcher(lid),
                    )
                    category_menu.addAction(action)
            else:
                # Add directly to main menu if only one category
                for launcher in category_launchers:
                    action = QAction(
                        launcher.name, cast("QWidget", cast("object", self.window))
                    )
                    action.setToolTip(launcher.description)
                    action.setData(launcher.id)
                    _ = action.triggered.connect(
                        lambda _=False,
                        lid=launcher.id: self.execute_custom_launcher(lid),
                    )
                    self.window.custom_launcher_menu.addAction(action)

    def update_launcher_menu_availability(self, has_context: bool) -> None:
        """Update launcher menu availability based on context.

        Args:
            has_context: Whether there is a current shot or scene context
        """
        for action in self.window.custom_launcher_menu.actions():
            submenu = action.menu()
            if submenu is not None:  # pyright: ignore[reportUnnecessaryComparison]  # PySide6 stubs incorrectly type menu() as QObject (non-optional), but it can be None at runtime
                # Type checker doesn't know menu() returns QMenu, use cast for testability
                # In production, this will always be QMenu; in tests, mocks work fine
                submenu_typed = cast("QMenu", submenu)
                # Submenu - enable/disable all actions in submenu
                for sub_action in submenu_typed.actions():
                    sub_action.setEnabled(has_context)
            else:
                # Regular action
                action.setEnabled(has_context)

    def _on_command_error(self, _timestamp: str, error: str) -> None:
        """Handle command launcher errors with notifications.

        Args:
            timestamp: Timestamp of the error
            error: Error message
        """
        # Extract error details for better user feedback
        if "not found" in error.lower() or "no such file" in error.lower():
            NotificationManager.error(
                "Application Not Found",
                "The requested application could not be found.",
                f"Details: {error}",
            )
        elif "permission" in error.lower():
            NotificationManager.error(
                "Permission Denied",
                "You don't have permission to run this application.",
                f"Details: {error}",
            )
        elif "no shot selected" in error.lower():
            NotificationManager.warning(
                "No Shot Selected",
                "Please select a shot before launching an application.",
            )
        else:
            NotificationManager.error(
                "Launch Failed", "Failed to launch application.", f"Details: {error}"
            )

        # Also show in status bar briefly
        NotificationManager.info(f"Error: {error}", 5000)

    def _on_launcher_started(self, launcher_id: str) -> None:
        """Handle custom launcher start with progress indication.

        Args:
            launcher_id: ID of the launcher that started
        """
        if not self.window.launcher_manager:
            return
        launcher = self.window.launcher_manager.get_launcher(launcher_id)
        launcher_name = launcher.name if launcher else "Custom command"
        _ = ProgressManager.start_operation(f"Launching {launcher_name}")

    def _on_launcher_finished(self, _launcher_id: str, success: bool) -> None:
        """Handle custom launcher completion with notifications.

        Args:
            launcher_id: ID of the launcher that finished
            success: Whether the launcher completed successfully
        """
        ProgressManager.finish_operation(success=success)

        if success:
            NotificationManager.toast(
                "Custom command completed successfully", NotificationType.SUCCESS
            )
        else:
            NotificationManager.toast("Custom command failed", NotificationType.ERROR)

    def _log_command(self, message: str) -> None:
        """Log command with current timestamp.

        Args:
            message: Command message to log
        """
        timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
        self.window.log_viewer.add_command(timestamp, message)

    def _log_error(self, message: str) -> None:
        """Log error with current timestamp.

        Args:
            message: Error message to log
        """
        timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
        self.window.log_viewer.add_error(timestamp, message)

    # ============================================================================
    # Properties - Single Source of Truth for Context State
    # ============================================================================

    @property
    def current_scene(self) -> ThreeDEScene | None:
        """Get the currently selected 3DE scene.

        This is the single source of truth for scene context.
        Other code should query this property rather than maintaining
        their own copies.

        Returns:
            Currently selected ThreeDEScene or None
        """
        return self._current_scene

    @property
    def current_shot(self) -> Shot | None:
        """Get the currently selected shot.

        This is the single source of truth for shot context.
        Other code should query this property rather than maintaining
        their own copies.

        Returns:
            Currently selected Shot or None
        """
        return self._current_shot
