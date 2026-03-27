"""Main window for ShotBot — signal wiring, controller coordination, and lifecycle."""

from __future__ import annotations

# Standard library imports
import os
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, final

# Third-party imports
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from typing_compat import override
from ui.qt_widget_mixin import (
    require_main_thread,
)


if TYPE_CHECKING:
    # Third-party imports
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QCloseEvent

    # Local application imports
    from type_definitions import Shot
    from ui.settings_dialog import SettingsDialog
    from workers.startup_coordinator import StartupCoordinator

# Runtime imports (needed at runtime)
# Local application imports
from app_services import build_infrastructure, build_models
from config import Config, is_mock_mode
from controllers.filter_coordinator import FilterCoordinator
from controllers.shot_selection_controller import (
    ShotSelectionController,  # Refactored shot selection management
)
from controllers.startup_orchestrator import StartupOrchestrator
from controllers.threede_controller import (
    ThreeDEController,  # Refactored 3DE scene management
)
from controllers.thumbnail_size_manager import ThumbnailSizeManager
from launch.launch_request import LaunchRequest
from logging_mixin import LoggingMixin, get_module_logger
from managers.notification_manager import NotificationManager
from managers.progress_manager import ProgressManager
from timeout_config import TimeoutConfig
from ui.log_viewer import LogViewer
from ui.menu_builder import build_menu
from ui.qt_widget_mixin import QtWidgetMixin
from ui.right_panel import RightPanelWidget  # New redesigned right panel
from ui.tab_factory import build_tabs


# Set up logger for this module
logger = get_module_logger(__name__)


@final
class MainWindow(QtWidgetMixin, LoggingMixin, QMainWindow):
    """Main application window and primary controller.

    Orchestrates the three-tab interface (My Shots, Other 3DE, Previous Shots),
    owns the DCC section panel (RightPanelWidget), and delegates user actions to
    ``command_launcher``. Signal routing follows a controller/delegate pattern:
    shot-grid signals connect to ``ShotSelectionController``, 3DE signals to
    ``ThreeDEController``, and launch signals to ``CommandLauncher``.
    """

    # Lifecycle signal: emitted when the window begins closing, before widgets
    # are torn down.  Controllers listen to this instead of polling a flag.
    closing_started: ClassVar[Signal] = Signal()

    @require_main_thread
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        cache_dir: Path | None = None,
    ) -> None:
        # Initialization order matters — see app_services.py and controllers/startup_orchestrator.py

        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QApplication as QApplicationType

        app_instance = QCoreApplication.instance()
        if app_instance is None:
            msg = "MainWindow: No QApplication instance found"
            raise RuntimeError(msg)

        # Additional safety check for QApplication type (relaxed for tests)
        # In test environments, QCoreApplication is acceptable since pytest-qt may create it
        import sys

        is_test_environment = "pytest" in sys.modules or "unittest" in sys.modules

        if not is_test_environment and not isinstance(app_instance, QApplicationType):
            msg = (
                "MainWindow: QCoreApplication instance is not a QApplication. "
                f"Type: {type(app_instance)}"
            )
            raise RuntimeError(msg)

        super().__init__(parent)

        # Build infrastructure and models via factories
        infra = build_infrastructure(cache_dir, parent=self)
        models = build_models(infra, parent=self)

        # Store infrastructure references
        self._process_pool = infra.process_pool
        self.thumbnail_cache = infra.thumbnail_cache
        self.shot_cache = infra.shot_cache
        self.scene_disk_cache = infra.scene_disk_cache
        self.latest_file_cache = infra.latest_file_cache
        self.cache_coordinator = infra.cache_coordinator
        self.pin_manager = infra.pin_manager
        self.hide_manager = infra.hide_manager
        self.notes_manager = infra.notes_manager
        self.file_pin_manager = infra.file_pin_manager
        self.refresh_coordinator = infra.refresh_coordinator
        self.settings_manager = infra.settings_manager
        self.settings_controller = infra.settings_controller
        self.settings_dialog: SettingsDialog | None = None

        # Store model references
        self.shot_model = models.shot_model
        self.threede_scene_model = models.threede_scene_model
        self.threede_item_model = models.threede_item_model
        self.previous_shots_model = models.previous_shots_model
        self.command_launcher = models.command_launcher

        self._closing = False  # Track shutdown state
        self._session_warmer: StartupCoordinator | None = None
        self._last_selected_shot_name: str | None = None
        self._setup_ui()
        self._init_controllers()
        self._setup_menu()
        self._connect_signals()
        self.settings_controller.load_settings()
        self.filter_coordinator.restore_sort_orders()

        # Skip initial load in test environments if requested
        if not os.environ.get("SHOTBOT_NO_INITIAL_LOAD"):
            startup = StartupOrchestrator(self, self._process_pool)
            startup.execute()
            self._session_warmer = startup.session_warmer

        # No longer need periodic background polling for shots - they use reactive signals now
        # One-shot timers during initialization are still used for async loading
        # Only background workers are used for 3DE scene discovery
        self.logger.info(
            "Shot model uses reactive signals - periodic polling disabled (async init via QTimer)"
        )
        self.logger.info("=" * 60)
        self.logger.info("MainWindow.__init__() COMPLETE - returning to Qt event loop")
        self.logger.info("=" * 60)

    def _init_controllers(self) -> None:
        """Initialize controllers that require UI widgets to be set up first."""
        self.filter_coordinator = FilterCoordinator(
            shot_proxy=self.shot_proxy,
            previous_shots_proxy=self.previous_shots_proxy,
            threede_proxy=self.threede_proxy,
            threede_item_model=self.threede_item_model,
            previous_shots_item_model=self.previous_shots_item_model,
            threede_shot_grid=self.threede_shot_grid,
            previous_shots_grid=self.previous_shots_grid,
            previous_shots_model=self.previous_shots_model,
            settings_manager=self.settings_manager,
            status_bar=self.status_bar,
        )

        self.threede_controller = ThreeDEController(
            self,
            command_launcher=self.command_launcher,
        )

        self.shot_selection_controller: ShotSelectionController = (
            ShotSelectionController(
                self,
                command_launcher=self.command_launcher,
                parent=self,
            )
        )

        self.thumbnail_size_manager: ThumbnailSizeManager = ThumbnailSizeManager(self)

    def _setup_ui(self) -> None:
        """Set up the main UI."""
        if is_mock_mode():
            self.setWindowTitle(
                f"{Config.APP_NAME} v{Config.APP_VERSION} - 🧪 MOCK MODE"
            )
        else:
            self.setWindowTitle(f"{Config.APP_NAME} v{Config.APP_VERSION}")
        self.resize(Config.DEFAULT_WINDOW_WIDTH, Config.DEFAULT_WINDOW_HEIGHT)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        self._setup_tabs()
        self.splitter.addWidget(self.tab_widget)

        right_widget = self._setup_right_panel()
        self.splitter.addWidget(right_widget)

        self.splitter.setSizes([750, 450])

        self._setup_status_bar()
        self.update_status("Ready")

    def _setup_tabs(self) -> None:
        """Create the tab widget and all three shot-view tabs."""
        tabs = build_tabs(
            shot_model=self.shot_model,
            threede_item_model=self.threede_item_model,
            previous_shots_model=self.previous_shots_model,
            thumbnail_cache=self.thumbnail_cache,
            pin_manager=self.pin_manager,
            notes_manager=self.notes_manager,
            hide_manager=self.hide_manager,
            parent=self,
        )
        self.tab_widget = tabs.tab_widget
        self.shot_item_model = tabs.shot_item_model
        self.shot_proxy = tabs.shot_proxy
        self.shot_grid = tabs.shot_grid
        self.threede_proxy = tabs.threede_proxy
        self.threede_shot_grid = tabs.threede_shot_grid
        self.previous_shots_item_model = tabs.previous_shots_item_model
        self.previous_shots_proxy = tabs.previous_shots_proxy
        self.previous_shots_grid = tabs.previous_shots_grid

    def _setup_right_panel(self) -> QWidget:
        """Build the right-side panel with RightPanelWidget and log viewer."""
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.right_panel = RightPanelWidget(settings_manager=self.settings_manager)
        # Signal connections handled by LauncherController
        right_layout.addWidget(self.right_panel, stretch=1)

        # Log viewer (collapsible, starts collapsed)
        log_group = QGroupBox("Command Log")
        log_group.setCheckable(True)
        log_group.setChecked(False)  # Start collapsed
        log_layout = QVBoxLayout(log_group)
        self.log_viewer = LogViewer()
        log_layout.addWidget(self.log_viewer)
        _ = log_group.toggled.connect(self.log_viewer.setVisible)
        self.log_viewer.setVisible(False)  # Match initial collapsed state

        right_layout.addWidget(log_group)

        return right_widget

    def _setup_status_bar(self) -> None:
        """Create the status bar and initialize NotificationManager and ProgressManager."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        if is_mock_mode():
            mock_label = QLabel("🧪 MOCK MODE ACTIVE")
            mock_label.setStyleSheet("""
                QLabel {
                    color: #ffcc00;
                    font-weight: bold;
                    padding: 2px 8px;
                    background-color: rgba(255, 204, 0, 0.2);
                    border: 1px solid #ffcc00;
                    border-radius: 3px;
                }
            """)
            self.status_bar.addPermanentWidget(mock_label)

        _ = NotificationManager.initialize(self, self.status_bar)
        _ = ProgressManager.initialize(self.status_bar)

    def _setup_menu(self) -> None:
        """Set up menu bar."""
        self.refresh_action = build_menu(self, self, self._refresh_shots)

    def _connect_signals(self) -> None:
        """Connect signals."""
        # Shot model -> RefreshCoordinator connections
        self.refresh_coordinator.setup_signals()
        _ = self.shot_model.error_occurred.connect(self._on_shot_error)
        # Note: shot_model.shot_selected signal removed (vestigial - only logged, no action)
        # Note: cache_updated only logged debug — connection removed
        _ = self.shot_model.data_recovery_occurred.connect(self._on_data_recovery)
        # Background load signals for status feedback during initial async load
        _ = self.shot_model.background_load_started.connect(
            lambda: self.status_bar.showMessage("Fetching fresh data...")
        )
        # Note: background_load_finished had body `pass` — connection removed

        # Shot selection - handled by ShotSelectionController when active
        # Controller handles shot_selected, shot_double_clicked, recover_crashes_requested

        # My Shots filter signals
        _ = self.shot_grid.show_filter_requested.connect(
            partial(
                self.filter_coordinator.apply_show_filter, self.shot_proxy, "My Shots"
            )  # pyright: ignore[reportAny]
        )
        _ = self.shot_grid.text_filter_requested.connect(
            partial(
                self.filter_coordinator.apply_text_filter, self.shot_proxy, "My Shots"
            )  # pyright: ignore[reportAny]
        )

        # Previous Shots filter signals
        _ = self.previous_shots_grid.show_filter_requested.connect(
            partial(
                self.filter_coordinator.apply_show_filter,
                self.previous_shots_proxy,
                "Previous Shots",
            )  # pyright: ignore[reportAny]
        )
        _ = self.previous_shots_grid.text_filter_requested.connect(
            partial(
                self.filter_coordinator.apply_text_filter,
                self.previous_shots_proxy,
                "Previous Shots",
            )  # pyright: ignore[reportAny]
        )

        # Previous shots model updates (repopulate show filter when shots change)
        _ = self.previous_shots_item_model.shots_updated.connect(
            self.filter_coordinator.on_previous_shots_updated  # pyright: ignore[reportAny]
        )

        _ = self.shot_grid.app_launch_requested.connect(
            lambda app_name: self.command_launcher.launch(  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
                LaunchRequest(app_name=app_name)  # pyright: ignore[reportUnknownArgumentType]
            )
        )
        _ = self.shot_grid.shot_visibility_changed.connect(
            lambda: self.shot_proxy.invalidate()
        )
        _ = self.shot_grid.show_hidden_changed.connect(
            self.shot_proxy.set_show_hidden
        )

        # 3DE scene selection - handled by controller
        # Controller handles its own signal connections in __init__
        # Handle app launch with scene context (signal emits app_name, scene)
        _ = self.threede_shot_grid.app_launch_requested.connect(
            lambda app_name, scene: self.command_launcher.launch(  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
                LaunchRequest(app_name=app_name, scene=scene)  # pyright: ignore[reportUnknownArgumentType]
            )
        )

        # 3DE show filter - handled by controller
        # Controller handles show filter in its own signal setup

        # Previous shots selection - handled by ShotSelectionController when active
        # Controller handles shot_selected and shot_double_clicked
        _ = self.previous_shots_grid.app_launch_requested.connect(
            lambda app_name: self.command_launcher.launch(  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
                LaunchRequest(app_name=app_name)  # pyright: ignore[reportUnknownArgumentType]
            )
        )

        # Pin sort-order refresh — fallback path when view has no pin_manager set
        _ = self.shot_grid.pin_shot_requested.connect(
            self._on_shot_grid_pin_requested
        )
        _ = self.previous_shots_grid.pin_shot_requested.connect(
            self._on_previous_shots_pin_requested
        )

        _ = self.shot_selection_controller.settings_save_requested.connect(
            self.settings_controller.save_settings
        )
        _ = self.refresh_coordinator.threede_refresh_requested.connect(
            self.threede_controller.refresh_threede_scenes
        )

        _ = self.tab_widget.currentChanged.connect(
            self.shot_selection_controller.on_tab_activated
        )  # pyright: ignore[reportAny]
        _ = self.tab_widget.currentChanged.connect(
            self.threede_controller.on_tab_activated
        )  # pyright: ignore[reportAny]
        _ = self.right_panel.launch_requested.connect(self._on_right_panel_launch)
        _ = self.right_panel.status_message.connect(self.update_status)

        # Async file search state - update launch button during search
        _ = self.command_launcher.launch_pending.connect(
            lambda: self.right_panel.set_search_pending(True)
        )
        _ = self.command_launcher.launch_ready.connect(
            lambda: self.right_panel.set_search_pending(False)
        )

        # Thumbnail size synchronization handled by ThumbnailSizeManager

        # Sort order changes - connect view signals to model and settings persistence
        _ = self.threede_shot_grid.sort_order_changed.connect(
            partial(
                self.filter_coordinator.on_sort_order_changed,
                "threede_scenes",
                self.threede_item_model,
            )
        )
        _ = self.previous_shots_grid.sort_order_changed.connect(
            partial(
                self.filter_coordinator.on_sort_order_changed,
                "previous_shots",
                self.previous_shots_item_model,
            )
        )


    # ---------------------------------------------------------------------------
    # Inlined from DataEventHandler
    # ---------------------------------------------------------------------------

    def _on_shot_error(self, error_msg: str) -> None:
        """Handle error signal from shot model."""
        self.logger.error(f"Shot model error: {error_msg}")
        self.status_bar.showMessage(f"Error: {error_msg}")

    def _on_data_recovery(self, title: str, details: str) -> None:
        """Handle data recovery notification from shot model."""
        self.logger.warning(f"Data recovery: {title} - {details}")
        NotificationManager.warning(title, details)

    def _on_shot_grid_pin_requested(self, shot: Shot) -> None:
        """Handle pin request from the My Shots grid."""
        self.pin_manager.pin_shot(shot)
        self.shot_proxy.refresh_sort()

    def _on_previous_shots_pin_requested(self, shot: Shot) -> None:
        """Handle pin request from the Previous Shots grid."""
        self.pin_manager.pin_shot(shot)
        self.previous_shots_proxy.refresh_sort()

    # ---------------------------------------------------------------------------
    # Inlined from LaunchCoordinator
    # ---------------------------------------------------------------------------

    def _on_right_panel_launch(self, app_name: str, options: dict[str, Any]) -> None:
        """Handle launch request from right panel DCC section."""
        from dcc.scene_file import SceneFile

        selected_file = options.get("selected_file")
        if isinstance(selected_file, SceneFile):
            workspace_path = self._get_current_workspace_path()
            if workspace_path:
                from launch.launch_request import LaunchRequest as _LaunchRequest

                _ = self.command_launcher.launch(
                    _LaunchRequest(
                        app_name=app_name,
                        file_path=selected_file.path,
                        workspace_path=workspace_path,
                    )
                )
                return
            NotificationManager.error(
                "Cannot Launch File",
                "No shot or scene context available. Select a shot first.",
            )
            return

        from launch.command_launcher import LaunchContext
        from launch.launch_request import LaunchRequest as _LaunchRequest

        context = LaunchContext(
            open_latest_threede=bool(options.get("open_latest_threede", False)),  # pyright: ignore[reportAny]
            open_latest_maya=bool(options.get("open_latest_maya", False)),  # pyright: ignore[reportAny]
            open_latest_scene=bool(options.get("open_latest_scene", False)),  # pyright: ignore[reportAny]
            create_new_file=bool(options.get("create_new_file", False)),  # pyright: ignore[reportAny]
            selected_plate=options.get("selected_plate"),
            sequence_path=options.get("sequence_path"),
        )
        _ = self.command_launcher.launch(
            _LaunchRequest(
                app_name=app_name,
                context=context,
            )
        )

    def _get_current_workspace_path(self) -> str | None:
        """Get workspace path from current shot or selected 3DE scene."""
        current_shot = self.command_launcher.current_shot
        if current_shot:
            return current_shot.workspace_path
        selected_scene = self.threede_shot_grid.selected_scene
        if selected_scene:
            return selected_scene.workspace_path
        return None

    def _refresh_shots(self) -> None:
        """Refresh shot list with progress indication."""
        self.logger.debug("Refreshing shots via RefreshCoordinator")
        self.refresh_coordinator.refresh_tab(0)

    # Note: Background refresh methods removed - now handled by reactive signals

    def get_splitter_state(self) -> QByteArray:
        """Get the main splitter state for settings persistence."""
        return self.splitter.saveState()

    def restore_splitter_state(self, state: QByteArray | bytes | bytearray) -> bool:
        """Restore the main splitter state from settings."""
        return self.splitter.restoreState(state)

    def get_current_tab(self) -> int:
        """Get the current tab index."""
        return self.tab_widget.currentIndex()

    def set_current_tab(self, index: int) -> None:
        """Set the current tab index."""
        self.tab_widget.setCurrentIndex(index)

    def reset_splitter_sizes(self, sizes: list[int]) -> None:
        """Reset splitter to given sizes."""
        self.splitter.setSizes(sizes)

    def get_window_size(self) -> tuple[int, int]:
        """Get window size as tuple for SettingsTarget protocol compliance."""
        size = self.size()
        return (size.width(), size.height())

    def set_thumbnail_size(self, size: int) -> None:
        """Set thumbnail size across all grid tabs via ThumbnailSizeManager."""
        self.thumbnail_size_manager.sync_thumbnail_sizes(size)  # pyright: ignore[reportAny]

    def get_thumbnail_size(self) -> int:
        """Get current thumbnail size from the shot grid slider."""
        return self.shot_grid.size_slider.value()

    @property
    def closing(self) -> bool:
        """Public property to check if the window is closing."""
        return self._closing

    @closing.setter
    def closing(self, value: bool) -> None:
        """Set the closing state and emit closing_started if transitioning to True."""
        if value and not self._closing:
            self.closing_started.emit()
        self._closing = value

    @property
    def session_warmer(self) -> StartupCoordinator | None:
        """Public property to access the session warmer thread."""
        return self._session_warmer

    @session_warmer.setter
    def session_warmer(self, value: StartupCoordinator | None) -> None:
        """Set the session warmer thread."""
        self._session_warmer = value

    @property
    def last_selected_shot_name(self) -> str | None:
        """Public property to access the last selected shot name."""
        return getattr(self, "_last_selected_shot_name", None)

    @last_selected_shot_name.setter
    def last_selected_shot_name(self, value: str | None) -> None:
        """Set the last selected shot name."""
        self._last_selected_shot_name = value

    def update_status(self, message: str) -> None:
        """Update status bar."""
        self.status_bar.showMessage(message)

    def launch_app(self, app_name: str) -> None:
        """Public method to launch an application."""
        _ = self.command_launcher.launch(LaunchRequest(app_name=app_name))

    def get_active_shots(self) -> list[Shot]:
        """Get currently active shots for cross-controller queries."""
        return self.shot_model.shots

    def cleanup(self) -> None:
        """Explicit cleanup method for proper resource management.

        This method can be called independently of closeEvent, making it
        suitable for test environments where widgets are destroyed without
        proper close events.
        """
        self.logger.debug("Starting explicit MainWindow cleanup")
        self._perform_cleanup()
        self.logger.debug("Completed explicit MainWindow cleanup")

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Thread-safe close event handler."""
        self.logger.debug("MainWindow closeEvent - starting cleanup")

        # Flush any pending notes to disk
        self.notes_manager.flush()

        self._perform_cleanup()

        # Save settings before closing
        self.settings_controller.save_settings()

        self.logger.debug("MainWindow closeEvent - cleanup complete")
        event.accept()

    def _perform_cleanup(self) -> None:
        """Main cleanup orchestration method.

        Cleanup ordering:
            1. Mark window as closing
            2. Controllers (threede_controller, shot_selection_controller)
            3. Session warmer thread
            4. Managers (command_launcher, cache_coordinator)
            5. Models (shot_model, previous_shots_model, previous_shots_item_model)
        """
        self.logger.debug("Starting MainWindow cleanup sequence")

        # 1. Mark window as closing
        self._closing = True

        # 2. Controllers
        if self.threede_controller:
            self.logger.debug("Cleaning up 3DE controller")
            self.threede_controller.cleanup_worker()

        if self.shot_selection_controller:
            self.logger.debug("Cleaning up shot selection controller")
            self.shot_selection_controller.cleanup()

        # 3. Session warmer thread
        if self._session_warmer is not None:
            warmer = self._session_warmer
            warmer.safe_shutdown(TimeoutConfig.SESSION_WARMER_STOP_MS)
            self._session_warmer = None

        # 4. Managers
        if self.command_launcher and hasattr(self.command_launcher, "cleanup"):
            self.logger.debug("Cleaning up command launcher")
            self.command_launcher.cleanup()

        self.logger.debug("Shutting down cache coordinator")
        self.cache_coordinator.shutdown()

        # 5. Models
        if hasattr(self.shot_model, "cleanup"):
            self.logger.debug("Cleaning up ShotModel background threads")
            self.shot_model.cleanup()

        if self.previous_shots_model:
            self.logger.debug("Cleaning up PreviousShotsModel")
            try:
                self.previous_shots_model.cleanup()
            except Exception:
                self.logger.exception("Error cleaning up PreviousShotsModel")

        if self.previous_shots_item_model:
            self.logger.debug("Cleaning up PreviousShotsItemModel")
            try:
                item_model = self.previous_shots_item_model
                if hasattr(item_model, "cleanup"):
                    item_model.cleanup()
            except Exception:
                self.logger.exception("Error cleaning up PreviousShotsItemModel")

        # Final: process events, clean QRunnables, GC
        from PySide6.QtWidgets import QApplication as QApplicationType

        app = QApplicationType.instance()
        if app:
            app.processEvents()

        from workers.runnable_tracker import cleanup_all_runnables

        self.logger.debug("Cleaning up tracked QRunnables")
        cleanup_all_runnables()

        import gc

        _ = gc.collect()

        self.logger.debug("MainWindow cleanup sequence completed")


# Background refresh methods and BackgroundRefreshWorker removed - ShotModel now uses reactive signals instead of polling
