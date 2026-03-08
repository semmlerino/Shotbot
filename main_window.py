"""Main window for ShotBot application.

This module contains the MainWindow class, which serves as the primary user interface
for the ShotBot VFX shot browsing and launcher application. The MainWindow integrates
all core components including shot grids, 3DE scene discovery, and application management.

The MainWindow follows a tabbed interface design with:
- My Shots: Visual grid of user's assigned shots with thumbnails
- Other 3DE scenes: Grid of discovered 3DE scenes from user directories
- Shot Info: Details panel showing current shot information

Key Features:
    - Real-time shot data refresh with caching
    - Background 3DE scene discovery with progress reporting
    - Persistent UI state and settings storage
    - Memory-optimized thumbnail loading and caching
    - Cross-platform file system operations

Architecture:
    The MainWindow uses Qt's signal-slot mechanism for loose coupling between
    components. It maintains domain-specific cache managers (ThumbnailCache,
    ShotDataCache, SceneDiskCache, LatestFileCache) coordinated through a
    CacheCoordinator for memory efficiency. Thread safety is ensured through
    proper mutex usage and state management.

Examples:
    Basic usage:
        >>> from main_window import MainWindow
        >>> window = MainWindow()
        >>> window.show()

    With custom configuration:
        >>> from config import Config
        >>> Config.DEFAULT_THUMBNAIL_SIZE = 250
        >>> window = MainWindow()
        >>> window.resize(1600, 1000)
        >>> window.show()

Type Safety:
    This module uses comprehensive type annotations with Optional types for
    nullable Qt widgets and proper signal type declarations. All public methods
    include full type hints for parameters and return values.

"""

from __future__ import annotations

# Standard library imports
import os
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, final

# Third-party imports
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from file_pin_manager import FilePinManager
from hide_manager import HideManager
from notes_manager import NotesManager
from pin_manager import PinManager
from typing_compat import override


if TYPE_CHECKING:
    # Local application imports
    from base_shot_model import BaseShotModel  # used in cast()
    from command_launcher import CommandLauncher
    from protocols import ProcessPoolInterface
    from scene_file import SceneFile
    from settings_dialog import SettingsDialog
    from type_definitions import ShotDict

# Runtime imports (needed at runtime)
# Local application imports
from cache import (
    CacheCoordinator,
    LatestFileCache,
    SceneDiskCache,
    ShotDataCache,
    ThumbnailCache,
    resolve_default_cache_dir,
)
from command_launcher import CommandLauncher  # Need at runtime
from config import Config, is_mock_mode
from controllers.filter_coordinator import FilterCoordinator
from controllers.settings_controller import (
    SettingsController,  # Refactored settings handling
)
from controllers.shot_selection_controller import (
    ShotSelectionController,  # Refactored shot selection management
)
from controllers.threede_controller import (
    ThreeDEController,  # Refactored 3DE scene management
)
from controllers.thumbnail_size_manager import ThumbnailSizeManager
from design_system import design_system
from log_viewer import LogViewer
from logging_mixin import LoggingMixin, get_module_logger
from notification_manager import NotificationManager
from previous_shots_item_model import PreviousShotsItemModel
from previous_shots_model import PreviousShotsModel
from previous_shots_view import PreviousShotsView
from process_pool_manager import ProcessPoolManager
from progress_manager import ProgressManager
from qt_widget_mixin import QtWidgetMixin
from refresh_orchestrator import RefreshOrchestrator  # Extracted refresh logic
from right_panel import RightPanelWidget  # New redesigned right panel
from scene_file import SceneFile
from settings_manager import SettingsManager
from shot_grid_view import ShotGridView  # Model/View implementation
from shot_item_model import ShotItemModel
from shot_model import ShotModel
from startup_coordinator import SessionWarmer
from threede_grid_view import ThreeDEGridView
from threede_item_model import ThreeDEItemModel
from threede_scene_model import ThreeDEScene, ThreeDESceneModel


# Set up logger for this module
logger = get_module_logger(__name__)


# Tab index constants for the main tab widget
TAB_MY_SHOTS = 0
TAB_OTHER_3DE = 1
TAB_PREVIOUS = 2

_TAB_BAR_STYLESHEET = """
    /* Tab bar - disable focus indicators */
    QTabBar {
        qproperty-drawBase: 0;
    }

    /* Base tab styling - professional proportions */
    QTabBar::tab {
        min-width: 120px;
        font-size: 16px;
        font-weight: 400;
        border: none;
        outline: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
        border-bottom-left-radius: 0px;
        border-bottom-right-radius: 0px;
    }

    /* Disable focus indicators */
    QTabBar::tab:focus {
        outline: none;
        border: none;
    }

    /* Inactive tabs - subtle and recessed */
    QTabBar::tab:!selected {
        background: rgba(50, 50, 50, 1.0);
        color: rgba(180, 180, 180, 1.0);
        padding: 10px 28px 12px 28px;
        margin-top: 4px;
        margin-bottom: 0px;
        margin-left: 0px;
        margin-right: 1px;
        border-top: 2px solid rgba(80, 80, 80, 1.0);
    }

    /* Tab 0 (My Shots) - Blue accent when inactive */
    QTabBar::tab:!selected:first {
        border-top: 2px solid rgba(100, 150, 200, 0.3);
    }

    /* Tab 1 (Other 3DE) - Cyan accent when inactive */
    QTabBar::tab:!selected:middle {
        border-top: 2px solid rgba(80, 180, 190, 0.3);
    }

    /* Tab 2 (Previous Shots) - Purple accent when inactive */
    QTabBar::tab:!selected:last {
        border-top: 2px solid rgba(150, 100, 180, 0.3);
        margin-right: 0px;
    }

    /* Selected tab - elevated, no border, no outline */
    QTabBar::tab:selected {
        background: rgba(65, 65, 65, 1.0);
        color: rgba(240, 240, 240, 1.0);
        padding: 12px 28px 14px 28px;
        margin-top: 0px;
        margin-bottom: -2px;
        margin-left: 0px;
        margin-right: 1px;
        border: 0px solid transparent;
        border-top: 0px solid transparent;
        border-bottom: 0px solid transparent;
        border-left: 0px solid transparent;
        border-right: 0px solid transparent;
        outline: 0px solid transparent;
    }

    /* Override any inherited borders for selected tabs */
    QTabBar::tab:selected:first {
        border: 0px solid transparent;
        outline: 0px solid transparent;
    }

    QTabBar::tab:selected:middle {
        border: 0px solid transparent;
        outline: 0px solid transparent;
    }

    QTabBar::tab:selected:last {
        border: 0px solid transparent;
        outline: 0px solid transparent;
    }

    /* Remove focus indicators from selected tabs */
    QTabBar::tab:selected:focus {
        outline: none;
        border: none;
    }

    QTabBar::tab:selected:first:focus {
        outline: none;
        border: none;
    }

    QTabBar::tab:selected:middle:focus {
        outline: none;
        border: none;
    }

    QTabBar::tab:selected:last:focus {
        outline: none;
        border: none;
    }
"""


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
    closing_started: Signal = Signal()

    # Timer delays for UI paint and event loop yields (milliseconds)
    _PAINT_YIELD_MS: int = 500  # Delay to let Qt paint initial UI before refresh
    _EVENT_LOOP_YIELD_MS: int = 100  # Delay to yield to event loop between operations

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        cache_dir: Path | None = None,
    ) -> None:
        # === Initialization Order (do not reorder) ===
        # 1. Thread/app safety checks (lines below)
        # 2. super().__init__() — QMainWindow + LoggingMixin
        # 3. Infrastructure: ProcessPool, CacheManager, PinManager, NotesManager,
        #    FilePinManager, CleanupManager, RefreshOrchestrator, SettingsManager
        # 4. Models: ThreeDEItemModel, ShotModel (+ async init), ThreeDESceneModel,
        #    PreviousShotsModel, CommandLauncher
        # 5. _setup_ui() — MUST precede controller init (controllers reference widgets)
        # 6. Controllers: ThreeDEController, ShotSelectionController,
        #    FilterCoordinator, ThumbnailSizeManager
        # 7. _setup_menu(), _setup_accessibility(), _connect_signals()
        # 8. settings_controller.load_settings(), _restore_sort_orders()
        # 9. _initial_load() — deferred data loading with QTimer scheduling

        # Ensure we're in the main thread for Qt widget creation
        from PySide6.QtCore import QCoreApplication, QThread

        app_instance = QCoreApplication.instance()
        if app_instance is None:
            msg = "MainWindow: No QApplication instance found"
            raise RuntimeError(msg)

        current_thread = QThread.currentThread()
        main_thread = app_instance.thread()
        if current_thread != main_thread:
            msg = (
                "MainWindow must be created in the main thread. "
                 f"Current thread: {current_thread}, "
                 f"Main thread: {main_thread}"
            )
            raise RuntimeError(
                msg
            )

        # Additional safety check for QApplication type (relaxed for tests)
        # In test environments, QCoreApplication is acceptable since pytest-qt may create it
        import sys

        is_test_environment = "pytest" in sys.modules or "unittest" in sys.modules

        if not isinstance(app_instance, QApplication) and not is_test_environment:
            msg = (
                "MainWindow: QCoreApplication instance is not a QApplication. "
                 f"Type: {type(app_instance)}"
            )
            raise RuntimeError(
                msg
            )

        super().__init__(parent)

        self._process_pool: ProcessPoolInterface
        if is_mock_mode():
            from mock_workspace_pool import create_mock_pool_from_filesystem

            self._process_pool = create_mock_pool_from_filesystem()
            self.logger.info("Using MockWorkspacePool for process execution")
        else:
            self._process_pool = ProcessPoolManager.get_instance()
            self.logger.info("Using ProcessPoolManager for process execution")

        # Resolve cache directory
        _cache_dir = cache_dir if cache_dir is not None else resolve_default_cache_dir()
        _cache_dir.mkdir(parents=True, exist_ok=True)

        # Create domain-specific cache managers
        self.thumbnail_cache = ThumbnailCache(_cache_dir)
        self.shot_cache = ShotDataCache(_cache_dir)
        self.scene_disk_cache = SceneDiskCache(_cache_dir)
        self.latest_file_cache = LatestFileCache(_cache_dir)
        self.cache_coordinator = CacheCoordinator(
            _cache_dir,
            self.thumbnail_cache,
            self.shot_cache,
            self.scene_disk_cache,
            self.latest_file_cache,
            on_cleared=lambda: self._process_pool.invalidate_cache(),
        )

        self.pin_manager = PinManager(_cache_dir)
        self.hide_manager = HideManager(_cache_dir)
        self.notes_manager = NotesManager(_cache_dir, parent=self)
        self.file_pin_manager = FilePinManager(_cache_dir, parent=self)

        self.refresh_orchestrator = RefreshOrchestrator(self)

        self.settings_manager = SettingsManager()
        saved_scale = self.settings_manager.get_ui_scale()
        design_system.set_ui_scale(saved_scale)
        self.settings_dialog: SettingsDialog | None = None

        self.settings_controller = SettingsController(self)

        self.threede_item_model = ThreeDEItemModel(cache_manager=self.thumbnail_cache)

        self.logger.info("Creating ShotModel with 366x faster startup")
        self.shot_model = ShotModel(self.shot_cache, process_pool=self._process_pool)
        init_result = self.shot_model.initialize_async()
        if init_result.success:
            cached_count = len(self.shot_model.shots)
            self.logger.debug(f"Model initialized: {cached_count} shots in memory")

        self.threede_scene_model = ThreeDESceneModel(self.scene_disk_cache)
        # Cast to BaseShotModel for type safety (ShotModel inherits from BaseShotModel)
        self.previous_shots_model = PreviousShotsModel(
            cast("BaseShotModel", self.shot_model),
            self.shot_cache,
        )

        self.command_launcher = CommandLauncher(
            parent=self,
            settings_manager=self.settings_manager,
            cache_manager=self.latest_file_cache,
        )

        self._closing = False  # Track shutdown state
        self._session_warmer: SessionWarmer | None = None
        self._last_selected_shot_name: str | None = None

        # UI setup must come before controller initialization
        self._setup_ui()

        self.threede_controller = ThreeDEController(self)

        self.shot_selection_controller: ShotSelectionController = ShotSelectionController(self)

        self.filter_coordinator: FilterCoordinator = FilterCoordinator(self)

        self.thumbnail_size_manager: ThumbnailSizeManager = ThumbnailSizeManager(self)

        self._setup_menu()
        self._setup_accessibility()
        self._connect_signals()
        self.settings_controller.load_settings()
        self._restore_sort_orders()

        # Skip initial load in test environments if requested
        if not os.environ.get("SHOTBOT_NO_INITIAL_LOAD"):
            self._initial_load()

        # No longer need periodic background polling for shots - they use reactive signals now
        # One-shot timers during initialization are still used for async loading
        # Only background workers are used for 3DE scene discovery
        self.logger.info(
            "Shot model uses reactive signals - periodic polling disabled (async init via QTimer)"
        )
        self.logger.info("=" * 60)
        self.logger.info("MainWindow.__init__() COMPLETE - returning to Qt event loop")
        self.logger.info("=" * 60)

    def _setup_ui(self) -> None:
        """Set up the main UI."""
        # Set window title with mock indicator if applicable
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

        # Left side - Tab widget for different views
        self.tab_widget = QTabWidget()
        # Disable focus indicators on tab bar
        self.tab_widget.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.splitter.addWidget(self.tab_widget)

        # Tab 1: My Shots
        self.shot_item_model = ShotItemModel(
            cache_manager=self.thumbnail_cache,
            pin_manager=self.pin_manager,
            notes_manager=self.notes_manager,
            hide_manager=self.hide_manager,
        )
        self.shot_model.set_hide_manager(self.hide_manager)
        self.shot_item_model.set_shots(self.shot_model.get_filtered_shots())
        self.shot_grid = ShotGridView(
            model=self.shot_item_model,
            pin_manager=self.pin_manager,
            notes_manager=self.notes_manager,
            hide_manager=self.hide_manager,
        )
        _ = self.tab_widget.addTab(self.shot_grid, "My Shots")

        # Tab 2: Other 3DE scenes (using Model/View architecture)
        self.threede_shot_grid = ThreeDEGridView(
            model=self.threede_item_model,
            pin_manager=self.pin_manager,
            notes_manager=self.notes_manager,
        )
        _ = self.tab_widget.addTab(self.threede_shot_grid, "Other 3DE scenes")

        # Tab 3: Previous Shots (approved/completed) - using Model/View architecture
        self.previous_shots_item_model = PreviousShotsItemModel(
            self.previous_shots_model,
            self.thumbnail_cache,
            pin_manager=self.pin_manager,
            notes_manager=self.notes_manager,
        )
        self.previous_shots_grid = PreviousShotsView(
            model=self.previous_shots_item_model,
            pin_manager=self.pin_manager,
            notes_manager=self.notes_manager,
        )
        _ = self.tab_widget.addTab(self.previous_shots_grid, "Previous Shots")

        self.tab_widget.tabBar().setStyleSheet(_TAB_BAR_STYLESHEET)

        # Right side panel
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

        self.splitter.addWidget(right_widget)

        # Set splitter sizes (wider right panel for better visibility)
        self.splitter.setSizes([750, 450])

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

        self.update_status("Ready")

    def _setup_menu(self) -> None:
        """Set up menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        self.refresh_action = QAction("&Refresh Shots", self)
        self.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        _ = self.refresh_action.triggered.connect(self._refresh_shots)
        file_menu.addAction(self.refresh_action)

        _ = file_menu.addSeparator()

        # Settings import/export
        import_settings_action = QAction("&Import Settings...", self)
        _ = import_settings_action.triggered.connect(
            self.settings_controller.import_settings
        )
        file_menu.addAction(import_settings_action)

        export_settings_action = QAction("&Export Settings...", self)
        _ = export_settings_action.triggered.connect(
            self.settings_controller.export_settings
        )
        file_menu.addAction(export_settings_action)

        _ = file_menu.addSeparator()

        exit_action = QAction("&Exit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        _ = exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        increase_size_action = QAction("&Increase Thumbnail Size", self)
        increase_size_action.setShortcut(QKeySequence.StandardKey.ZoomIn)
        _ = increase_size_action.triggered.connect(self.thumbnail_size_manager.increase_size)
        view_menu.addAction(increase_size_action)

        decrease_size_action = QAction("&Decrease Thumbnail Size", self)
        decrease_size_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
        _ = decrease_size_action.triggered.connect(self.thumbnail_size_manager.decrease_size)
        view_menu.addAction(decrease_size_action)

        _ = view_menu.addSeparator()

        reset_layout_action = QAction("&Reset Layout", self)
        _ = reset_layout_action.triggered.connect(self.settings_controller.reset_layout)
        view_menu.addAction(reset_layout_action)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")

        preferences_action = QAction("&Preferences...", self)
        preferences_action.setShortcut("Ctrl+,")  # Standard preferences shortcut
        _ = preferences_action.triggered.connect(
            self.settings_controller.show_preferences
        )
        edit_menu.addAction(preferences_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        shortcuts_action = QAction("&Keyboard Shortcuts", self)
        shortcuts_action.setShortcut(QKeySequence.StandardKey.HelpContents)
        _ = shortcuts_action.triggered.connect(self._show_shortcuts)
        help_menu.addAction(shortcuts_action)

        _ = help_menu.addSeparator()

        about_action = QAction("&About", self)
        _ = about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_accessibility(self) -> None:
        """Set up accessibility features for screen readers and keyboard navigation."""
        # Local application imports
        from accessibility_manager import AccessibilityManager

        # Set up main window accessibility
        AccessibilityManager.setup_main_window_accessibility(self)

        # Set up shot grid accessibility
        AccessibilityManager.setup_shot_grid_accessibility(self.shot_grid, "shots")
        AccessibilityManager.setup_shot_grid_accessibility(
            self.threede_shot_grid, "3de"
        )
        AccessibilityManager.setup_shot_grid_accessibility(
            self.previous_shots_grid, "previous"
        )

        # Set up tab widget
        AccessibilityManager.setup_tab_widget_accessibility(self.tab_widget)

        # Add comprehensive tooltips
        AccessibilityManager.setup_comprehensive_tooltips(self)


    def _connect_signals(self) -> None:
        """Connect signals."""
        # Connect shot model signals directly to RefreshOrchestrator (no proxy)
        _ = self.shot_model.shots_loaded.connect(
            self.refresh_orchestrator.handle_shots_loaded
        )
        _ = self.shot_model.shots_loaded.connect(
            self.refresh_orchestrator.trigger_previous_shots_refresh
        )
        _ = self.shot_model.shots_changed.connect(
            self.refresh_orchestrator.handle_shots_changed
        )
        _ = self.shot_model.shots_changed.connect(
            self.refresh_orchestrator.trigger_previous_shots_refresh
        )
        _ = self.shot_model.refresh_started.connect(
            self.refresh_orchestrator.handle_refresh_started
        )
        _ = self.shot_model.refresh_finished.connect(
            self.refresh_orchestrator.handle_refresh_finished
        )
        _ = self.shot_model.error_occurred.connect(self._on_shot_error)
        # Note: shot_model.shot_selected signal removed (vestigial - only logged, no action)
        _ = self.shot_model.cache_updated.connect(self._on_cache_updated)
        _ = self.shot_model.data_recovery_occurred.connect(self._on_data_recovery)
        # Background load signals for status feedback during initial async load
        _ = self.shot_model.background_load_started.connect(
            self._on_background_load_started
        )
        _ = self.shot_model.background_load_finished.connect(
            self._on_background_load_finished
        )

        # Connect to shot cache for migration events
        _ = self.shot_cache.shots_migrated.connect(
            self._on_shots_migrated, Qt.ConnectionType.QueuedConnection
        )

        # Shot selection - handled by ShotSelectionController when active
        # Controller handles shot_selected, shot_double_clicked, recover_crashes_requested
        # Filter signals handled by FilterCoordinator
        _ = self.shot_grid.app_launch_requested.connect(
            self.command_launcher.launch_app
        )
        _ = self.shot_grid.shot_visibility_changed.connect(
            self._on_shot_visibility_changed
        )
        _ = self.shot_grid.show_hidden_changed.connect(self._on_show_hidden_changed)

        # 3DE scene selection - handled by controller
        # Controller handles its own signal connections in __init__
        # Handle app launch with scene context (signal emits app_name, scene)
        _ = self.threede_shot_grid.app_launch_requested.connect(
            self._launch_app_with_scene_context
        )

        # 3DE show filter - handled by controller
        # Controller handles show filter in its own signal setup

        # Previous shots selection - handled by ShotSelectionController when active
        # Controller handles shot_selected and shot_double_clicked
        # Filter signals handled by FilterCoordinator
        _ = self.previous_shots_grid.app_launch_requested.connect(
            self.command_launcher.launch_app
        )

        _ = self.tab_widget.currentChanged.connect(self._on_tab_changed)
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
            partial(self._on_sort_order_changed, "threede_scenes", self.threede_item_model)
        )
        _ = self.previous_shots_grid.sort_order_changed.connect(
            partial(self._on_sort_order_changed, "previous_shots", self.previous_shots_item_model)
        )

    def _restore_sort_orders(self) -> None:
        """Restore sort order settings for each tab.

        Called after load_settings() to restore persisted sort orders
        to both the item models and the view UI buttons.
        """
        threede_order = self.settings_manager.get_sort_order("threede_scenes")
        self.threede_item_model.set_sort_order(threede_order)
        self.threede_shot_grid.set_sort_order(threede_order)
        self.logger.debug(f"Restored 3DE scenes sort order: {threede_order}")

        # Restore Previous Shots sort order
        previous_order = self.settings_manager.get_sort_order("previous_shots")
        self.previous_shots_item_model.set_sort_order(previous_order)
        self.previous_shots_grid.set_sort_order(previous_order)
        self.logger.debug(f"Restored Previous Shots sort order: {previous_order}")

        # My Shots tab always sorts by name - no user-configurable sort order

    def _initial_load(self) -> None:
        """Initial shot loading — instant from cache or deferred to background.

        Implements a 4-case decision table based on cache state:
            cached shots + cached scenes  → display both, schedule background refresh
            cached shots only             → display shots, schedule background refresh
            cached scenes only            → display scenes, no shot refresh scheduled
            no cache                      → show "Loading..." status; background refresh
                                            already in progress from initialize_async()
        """
        # Pre-warm bash sessions in background to avoid first-command delay
        # Only warm real process pools (test doubles don't spawn subprocesses)
        if isinstance(self._process_pool, ProcessPoolManager):
            self._session_warmer = SessionWarmer(self._process_pool)
            self._session_warmer.start()
            logger.debug("SessionWarmer started")

        has_cached_shots = bool(self.shot_model.shots)
        has_cached_scenes = bool(self.threede_scene_model.scenes)

        # Show cached shots immediately if available (should already be loaded)
        if has_cached_shots:
            self._refresh_shot_display()
            logger.info(
                f"Displayed {len(self.shot_model.shots)} cached shots instantly"
            )
        else:
            # No cache, but let's check one more time
            logger.info(
                "No cached shots found on initial check, attempting explicit cache load"
            )
            if self.shot_model.try_load_from_cache():
                has_cached_shots = True
                self._refresh_shot_display()
                logger.info(
                    f"Loaded and displayed {len(self.shot_model.shots)} shots from cache"
                )

            # Restore last selected shot if available
            if isinstance(self._last_selected_shot_name, str):
                shot = self.shot_model.find_shot_by_name(self._last_selected_shot_name)
                if shot:
                    self.shot_grid.select_shot_by_name(shot.full_name)

        # Show cached 3DE scenes immediately if available
        if has_cached_scenes:
            self.threede_item_model.set_scenes(self.threede_scene_model.scenes)
            # Populate show filter with available shows
            self.threede_shot_grid.populate_show_filter(self.threede_scene_model)

        # Update status with what was loaded from cache
        paint_yield_ms = 500
        event_loop_yield_ms = 100
        if has_cached_shots and has_cached_scenes:
            self.update_status(
                (
                    f"Loaded {len(self.shot_model.shots)} shots and "
                    f"{len(self.threede_scene_model.scenes)} 3DE scenes from cache"
                ),
            )
            QTimer.singleShot(paint_yield_ms, self._refresh_shots)
        elif has_cached_shots:
            self.update_status(
                f"Loaded {len(self.shot_model.shots)} shots from cache"
            )
            QTimer.singleShot(paint_yield_ms, self._refresh_shots)
        elif has_cached_scenes:
            self.update_status(
                f"Loaded {len(self.threede_scene_model.scenes)} 3DE scenes from cache",
            )
        else:
            self.update_status("Loading shots and scenes...")
            logger.info(
                "No cached data found - background refresh already in progress from initialize_async()",
            )

        # If shots are already loaded from cache, trigger refresh immediately
        if self.shot_model.shots:
            logger.info(
                "Shots already loaded from cache, triggering previous shots refresh immediately"
            )
            QTimer.singleShot(
                event_loop_yield_ms, self.previous_shots_model.refresh_shots
            )

        # Only start 3DE discovery if we have shots AND cache is invalid/expired
        if has_cached_shots:
            if not self.scene_disk_cache.has_valid_threede_cache():
                logger.debug("3DE cache invalid/expired - starting discovery")
                if self.threede_controller:
                    QTimer.singleShot(
                        100, self.threede_controller.refresh_threede_scenes
                    )
            else:
                logger.debug("3DE cache valid - skipping initial scan")

    def _refresh_shots(self) -> None:
        """Refresh shot list with progress indication."""
        self.logger.debug("Refreshing shots via RefreshOrchestrator")
        self.refresh_orchestrator.refresh_tab(0)

    # Note: Background refresh methods removed - now handled by reactive signals

    def _refresh_shot_display(self) -> None:
        """Refresh the shot display using Model/View implementation."""
        # Delegate to RefreshOrchestrator
        self.refresh_orchestrator.refresh_shot_display()


    def _on_shot_error(self, error_msg: str) -> None:
        """Handle error signal from model.

        Args:
            error_msg: The error message

        """
        self.logger.error(f"Shot model error: {error_msg}")
        self.update_status(f"Error: {error_msg}")

    def _on_data_recovery(self, title: str, details: str) -> None:
        """Handle data recovery notification from model.

        Shows a warning dialog to inform the user about cache corruption recovery.

        Args:
            title: The dialog title
            details: Detailed message about the recovery

        """
        self.logger.warning(f"Data recovery: {title} - {details}")
        NotificationManager.warning(title, details)

    def _on_background_load_started(self) -> None:
        """Handle background load started signal from model.

        Shows a status message while fresh data is being fetched in the background.
        """
        self.status_bar.showMessage("Fetching fresh data...")

    def _on_background_load_finished(self) -> None:
        """Handle background load finished signal from model.

        Intentionally empty: completion status is handled by the shots_loaded /
        shots_changed signals via RefreshOrchestrator.
        """
        pass  # noqa: PIE790

    def _on_shot_visibility_changed(self) -> None:
        """Handle shot hide/unhide — refresh the shot grid display."""
        self.shot_item_model.set_shots(self.shot_model.get_filtered_shots())

    def _on_show_hidden_changed(self, show: bool) -> None:
        """Handle Show Hidden checkbox toggle.

        Args:
            show: True to show hidden shots, False to hide them

        """
        self.shot_model.set_show_hidden(show)
        self.shot_item_model.set_shots(self.shot_model.get_filtered_shots())


    def _on_cache_updated(self) -> None:
        """Handle cache updated signal from model."""
        self.logger.debug("Shot cache updated")

    def _on_shots_migrated(self, migrated_shots: list[ShotDict]) -> None:
        """Handle shots migrated to Previous Shots cache.

        This is called when shots are removed from My Shots and automatically
        migrated to the Previous Shots cache. We refresh the Previous Shots
        tab so users see the migrated shots immediately.

        Args:
            migrated_shots: List of ShotDict objects that were migrated

        """
        self.logger.info(f"{len(migrated_shots)} shots migrated to Previous Shots")
        # Trigger Previous Shots tab refresh to show newly migrated shots
        if self.previous_shots_model:
            _ = self.previous_shots_model.refresh_shots()

    def _on_tab_changed(self, index: int) -> None:
        """Handle tab widget tab changes.

        When switching tabs, update the shot context based on the
        currently selected item in the new tab.

        Args:
            index: Index of the newly selected tab

        """
        if index == TAB_MY_SHOTS:
            # Get the current selection from My Shots
            selected_shot = self.shot_grid.selected_shot
            self.shot_selection_controller.on_shot_selected(selected_shot)

        elif index == TAB_OTHER_3DE:
            # Get the current selection from 3DE scenes
            selected_scene = self.threede_shot_grid.selected_scene
            if selected_scene:
                # Re-apply the scene selection to update context
                if self.threede_controller:
                    self.threede_controller.on_scene_selected(selected_scene)
            else:
                # Clear selection
                self.command_launcher.set_current_shot(None)
                self.right_panel.set_shot(None)

        elif index == TAB_PREVIOUS:
            # Get the current selection from Previous Shots
            selected_shot = self.previous_shots_grid.selected_shot
            self.shot_selection_controller.on_shot_selected(selected_shot)

    def _launch_app_with_scene_context(
        self, app_name: str, scene: ThreeDEScene
    ) -> None:
        """Launch an application with scene context.

        This method is used when app_launch_requested signal is emitted from
        ThreeDEGridView with both app_name and scene parameters.

        Args:
            app_name: Name of the application to launch
            scene: 3DE scene providing the launch context

        """
        _ = self.command_launcher.launch_app_with_scene(app_name, scene)

    def _on_right_panel_launch(
        self, app_name: str, options: dict[str, Any]
    ) -> None:
        """Handle launch request from right panel DCC section.

        Converts options dict to launch_app parameters. If a specific file
        is selected in the DCC section, launches with that file instead.

        Args:
            app_name: Name of the application to launch
            options: Dict containing checkbox states, selected plate, and
                optionally a selected_file (SceneFile) to open

        """
        # Check if a specific file was selected for launch
        selected_file = options.get("selected_file")
        if isinstance(selected_file, SceneFile):
            # Get workspace path from current context (shot or 3DE scene)
            workspace_path = self._get_current_workspace_path()
            if workspace_path:
                _ = self.command_launcher.launch_with_file(
                    app_name,
                    selected_file.path,
                    workspace_path,
                )
                return
            # If no workspace context, show error
            from notification_manager import error as notify_error

            notify_error(
                "Cannot Launch File",
                "No shot or scene context available. Select a shot first.",
            )
            return

        # Standard launch without specific file
        from command_launcher import LaunchContext

        context = LaunchContext(
            open_latest_threede=bool(options.get("open_latest_threede", False)),
            open_latest_maya=bool(options.get("open_latest_maya", False)),
            open_latest_scene=bool(options.get("open_latest_scene", False)),
            create_new_file=bool(options.get("create_new_file", False)),
            selected_plate=options.get("selected_plate"),
            sequence_path=options.get("sequence_path"),
        )
        _ = self.command_launcher.launch_app(app_name, context)

    def _get_current_workspace_path(self) -> str | None:
        """Get workspace path from current shot or selected 3DE scene.

        Used when launching files from the DCC panel - needs workspace
        context from either "My Shots" or "Other 3DE Scenes" tab.

        Returns:
            Workspace path string, or None if no context available

        """
        # Try current shot first (My Shots or Previous Shots tab)
        current_shot = self.command_launcher.current_shot
        if current_shot:
            return current_shot.workspace_path

        # Fall back to selected 3DE scene (Other 3DE Scenes tab)
        selected_scene = self.threede_shot_grid.selected_scene
        if selected_scene:
            return selected_scene.workspace_path

        return None

    # Filter methods moved to FilterCoordinator
    # Size methods moved to ThumbnailSizeManager

    def _on_sort_order_changed(
        self,
        settings_key: str,
        item_model: ThreeDEItemModel | PreviousShotsItemModel,
        order: str,
    ) -> None:
        """Handle sort order change for any grid view.

        Args:
            settings_key: Settings key for persistence (e.g., "threede_scenes")
            item_model: The item model to update
            order: Sort order ("name" or "date")

        """
        item_model.set_sort_order(order)
        self.settings_manager.set_sort_order(settings_key, order)
        self.logger.info(f"{settings_key} sort order changed to: {order}")

    def _show_shortcuts(self) -> None:
        """Show keyboard shortcuts dialog."""
        shortcuts_text = """<h3>Keyboard Shortcuts</h3>
        <table cellpadding="5">
        <tr><td><b>Navigation:</b></td><td></td></tr>
        <tr><td>Arrow Keys</td><td>Navigate through shots/scenes</td></tr>
        <tr><td>Home/End</td><td>Jump to first/last shot</td></tr>
        <tr><td>Enter</td><td>Launch default app (3de)</td></tr>
        <tr><td>Ctrl+Wheel</td><td>Adjust thumbnail size</td></tr>
        <tr><td>&nbsp;</td><td></td></tr>
        <tr><td><b>Applications:</b></td><td></td></tr>
        <tr><td>3</td><td>Launch 3de</td></tr>
        <tr><td>N</td><td>Launch Nuke</td></tr>
        <tr><td>M</td><td>Launch Maya</td></tr>
        <tr><td>R</td><td>Launch RV</td></tr>
        <tr><td>P</td><td>Launch Publish</td></tr>
        <tr><td>&nbsp;</td><td></td></tr>
        <tr><td><b>View:</b></td><td></td></tr>
        <tr><td>Ctrl++</td><td>Increase thumbnail size</td></tr>
        <tr><td>Ctrl+-</td><td>Decrease thumbnail size</td></tr>
        <tr><td>&nbsp;</td><td></td></tr>
        <tr><td><b>General:</b></td><td></td></tr>
        <tr><td>F5</td><td>Refresh shots</td></tr>
        <tr><td>F1</td><td>Show this help</td></tr>
        </table>
        """

        _ = QMessageBox.information(self, "Keyboard Shortcuts", shortcuts_text)

    def _show_about(self) -> None:
        """Show about dialog."""
        _ = QMessageBox.about(
            self,
            f"About {Config.APP_NAME}",
            (
                f"{Config.APP_NAME} v{Config.APP_VERSION}\n\n"
                 "VFX Shot Launcher\n\n"
                 "A tool for browsing and launching applications in shot context."
            ),
        )

    def get_window_size(self) -> tuple[int, int]:
        """Get window size as tuple for SettingsTarget protocol compliance."""
        size = self.size()
        return (size.width(), size.height())

    def set_thumbnail_size(self, size: int) -> None:
        """Set thumbnail size across all grid tabs via ThumbnailSizeManager."""
        self.thumbnail_size_manager.sync_thumbnail_sizes(size)

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
    def session_warmer(self) -> SessionWarmer | None:
        """Public property to access the session warmer thread."""
        return self._session_warmer

    @session_warmer.setter
    def session_warmer(self, value: SessionWarmer | None) -> None:
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
        _ = self.command_launcher.launch_app(app_name)

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
            if not warmer.isFinished():
                self.logger.debug("Requesting session warmer to stop")
                _ = warmer.request_stop()

                import sys
                is_test_environment = "pytest" in sys.modules
                session_timeout_ms = 200 if is_test_environment else 2000

                if not warmer.wait(session_timeout_ms):
                    self.logger.warning(
                        f"Session warmer didn't finish gracefully within {session_timeout_ms}ms, using safe termination"
                    )
                    warmer.safe_terminate()

                    final_timeout_ms = 100 if is_test_environment else 1000
                    if not warmer.wait(final_timeout_ms):
                        self.logger.warning(
                            "Session warmer thread abandoned - will be cleaned on exit"
                        )

            if warmer.is_zombie():
                self.logger.warning(
                    "Session warmer thread is a zombie and will not be deleted"
                )
            else:
                warmer.deleteLater()

            self._session_warmer = None

        # 4. Managers
        if (
            self.command_launcher
            and hasattr(self.command_launcher, "nuke_handler")
            and hasattr(self.command_launcher.nuke_handler, "log_usage_stats")
        ):
            self.logger.debug("Logging Nuke launcher usage statistics")
            self.command_launcher.nuke_handler.log_usage_stats()

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
        app = QApplication.instance()
        if app:
            app.processEvents()

        from runnable_tracker import cleanup_all_runnables
        self.logger.debug("Cleaning up tracked QRunnables")
        cleanup_all_runnables()

        import gc
        _ = gc.collect()

        self.logger.debug("MainWindow cleanup sequence completed")


# Background refresh methods and BackgroundRefreshWorker removed - ShotModel now uses reactive signals instead of polling
