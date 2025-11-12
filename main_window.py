"""Main window for ShotBot application.

This module contains the MainWindow class, which serves as the primary user interface
for the ShotBot VFX shot browsing and launcher application. The MainWindow integrates
all core components including shot grids, 3DE scene discovery, custom launchers,
and application management.

The MainWindow follows a tabbed interface design with:
- My Shots: Visual grid of user's assigned shots with thumbnails
- Other 3DE scenes: Grid of discovered 3DE scenes from user directories
- Shot Info: Details panel showing current shot information
- Custom Launchers: Management interface for creating custom application launchers

Key Features:
    - Real-time shot data refresh with caching
    - Background 3DE scene discovery with progress reporting
    - Thread-safe custom launcher management with race condition protection
    - Persistent UI state and settings storage
    - Memory-optimized thumbnail loading and caching
    - Cross-platform file system operations

Architecture:
    The MainWindow uses Qt's signal-slot mechanism for loose coupling between
    components. It maintains a single CacheManager instance shared across all
    thumbnail widgets and data models for memory efficiency. Thread safety is
    ensured through proper mutex usage and state management.

Examples:
    Basic usage:
        >>> from main_window import MainWindow
        >>> from cache_manager import CacheManager
        >>> cache = CacheManager()
        >>> window = MainWindow(cache_manager=cache)
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
import time
from typing import TYPE_CHECKING, cast, final

# Third-party imports
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
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

from typing_compat import override


if TYPE_CHECKING:
    # Local application imports
    from base_shot_model import BaseShotModel
    from cache_manager import CacheManager
    from command_launcher import CommandLauncher
    from launcher_dialog import LauncherManagerDialog
    from launcher_manager import LauncherManager
    from protocols import ProcessPoolInterface
    from settings_dialog import SettingsDialog
    from type_definitions import ShotDict

# Runtime imports (needed at runtime)
# Local application imports
from cache_manager import CacheManager  # Need at runtime for instantiation
from cleanup_manager import CleanupManager  # Extracted cleanup logic
from command_launcher import CommandLauncher  # Need at runtime
from config import Config
from controllers.launcher_controller import (
    LauncherController,  # Refactored launcher management
)
from controllers.settings_controller import (
    SettingsController,  # Refactored settings handling
)
from controllers.threede_controller import (
    ThreeDEController,  # Refactored 3DE scene management
)
from launcher_manager import LauncherManager  # Need at runtime
from launcher_panel import LauncherPanel  # Improved launcher UI
from log_viewer import LogViewer
from logging_mixin import LoggingMixin, get_module_logger
from notification_manager import NotificationManager
from persistent_terminal_manager import PersistentTerminalManager
from previous_shots_item_model import PreviousShotsItemModel
from previous_shots_model import PreviousShotsModel
from previous_shots_view import PreviousShotsView
from process_pool_manager import ProcessPoolManager
from progress_manager import ProgressManager
from qt_widget_mixin import QtWidgetMixin
from refresh_orchestrator import RefreshOrchestrator  # Extracted refresh logic
from settings_manager import SettingsManager
from shot_grid_view import ShotGridView  # Model/View implementation
from shot_info_panel import ShotInfoPanel
from shot_item_model import ShotItemModel
from shot_model import Shot, ShotModel
from thread_safe_worker import ThreadSafeWorker
from threede_grid_view import ThreeDEGridView
from threede_item_model import ThreeDEItemModel
from threede_scene_model import ThreeDEScene, ThreeDESceneModel


# Set up logger for this module
# Module-level logger for non-class code (SessionWarmer, etc.)
logger = get_module_logger(__name__)


class SessionWarmer(ThreadSafeWorker):
    """Background thread for pre-warming bash sessions without blocking UI.

    This thread runs during idle time after the UI is displayed, initializing
    the bash environment and 'ws' function in the background. This prevents
    the ~8 second freeze that would occur if this initialization happened
    on the main thread during the first actual command execution.
    """

    def __init__(self, process_pool: ProcessPoolInterface) -> None:
        """Initialize session warmer with process pool.

        Args:
            process_pool: ProcessPoolInterface instance to warm up
        """
        super().__init__()
        self._process_pool: ProcessPoolInterface = process_pool

    @Slot()
    @override
    def run(self) -> None:
        """Pre-warm bash sessions in background thread."""
        try:
            # Check if we should stop before starting
            if self.should_stop():
                return

            logger.debug("Starting background session pre-warming")
            start_time = time.time()

            # Check if we should stop before executing
            if self.should_stop():
                return

            _ = self._process_pool.execute_workspace_command(
                "echo warming",
                cache_ttl=1,  # Short TTL since this is just for warming
                timeout=15,  # Give enough time for first initialization
                use_login_shell=True,  # Use bash -l to avoid terminal blocking
            )
            duration = time.time() - start_time
            logger.info(f"Bash session pre-warming completed successfully ({duration:.2f}s)")
        except Exception as e:
            # Don't fail the app if pre-warming fails
            logger.warning(f"Session pre-warming failed (non-critical): {e}")


@final
class MainWindow(QtWidgetMixin, LoggingMixin, QMainWindow):
    """Main application window."""

    def __init__(
        self,
        cache_manager: CacheManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        # Ensure we're in the main thread for Qt widget creation
        # Third-party imports
        from PySide6.QtCore import QCoreApplication, QThread
        from PySide6.QtWidgets import QApplication

        # Check if QApplication exists
        app_instance = QCoreApplication.instance()
        if app_instance is None:
            raise RuntimeError("MainWindow: No QApplication instance found")

        # Check if we're in the main thread
        current_thread = QThread.currentThread()
        main_thread = app_instance.thread()
        if current_thread != main_thread:
            raise RuntimeError(
                "MainWindow must be created in the main thread. "
                 f"Current thread: {current_thread}, "
                 f"Main thread: {main_thread}"
            )

        # Additional safety check for QApplication type (relaxed for tests)
        # In test environments, QCoreApplication is acceptable since pytest-qt may create it
        # Standard library imports
        import sys

        is_test_environment = "pytest" in sys.modules or "unittest" in sys.modules

        if not isinstance(app_instance, QApplication) and not is_test_environment:
            raise RuntimeError(
                "MainWindow: QCoreApplication instance is not a QApplication. "
                 f"Type: {type(app_instance)}"
            )

        super().__init__(parent)

        # Initialize shot_model attribute (will be set later based on feature flag)

        # Create process pool based on mock mode
        # Check for mock mode from environment variable
        is_mock_mode = os.environ.get("SHOTBOT_MOCK", "").lower() in (
            "1",
            "true",
            "yes",
        )
        self._process_pool: ProcessPoolInterface
        if is_mock_mode:
            # Local application imports
            from mock_workspace_pool import create_mock_pool_from_filesystem

            self._process_pool = create_mock_pool_from_filesystem()
            self.logger.info("Using MockWorkspacePool for process execution")
        else:
            # Use production pool
            self._process_pool = ProcessPoolManager.get_instance()
            self.logger.info("Using ProcessPoolManager for process execution")

        # Create single cache manager for the application
        self.cache_manager = cache_manager or CacheManager()

        # Initialize cleanup and refresh managers (extracted from MainWindow)
        # MainWindow implements protocol interfaces functionally at runtime
        # QMainWindow signatures use position-only params which differ from Protocol
        self.cleanup_manager = CleanupManager(self)  # pyright: ignore[reportArgumentType]
        self.refresh_orchestrator = RefreshOrchestrator(self)  # pyright: ignore[reportArgumentType]

        # Initialize settings manager
        self.settings_manager = SettingsManager()

        # Store reference to settings dialog
        self._settings_dialog: SettingsDialog | None = None

        # Initialize settings controller (refactored from MainWindow methods)
        # MainWindow implements SettingsTarget protocol functionally at runtime
        # QMainWindow signatures use position-only params which differ from Protocol
        self.settings_controller = SettingsController(self)  # pyright: ignore[reportArgumentType]

        # Create 3DE item model for Model/View architecture
        self.threede_item_model = ThreeDEItemModel(cache_manager=self.cache_manager)

        # Create the shot model with async loading and instant UI display
        self.logger.info("Creating ShotModel with 366x faster startup")
        self.shot_model = ShotModel(self.cache_manager, process_pool=self._process_pool)

        # Initialize async loading for immediate UI display
        init_result = self.shot_model.initialize_async()
        if init_result.success:
            cached_count = len(self.shot_model.shots)
            if cached_count > 0:
                self.logger.debug(
                    f"Model initialized with {cached_count} cached shots (valid cache)"
                )
            else:
                # Check if cache exists but expired
                persistent_cache = self.cache_manager.get_persistent_shots()
                if persistent_cache:
                    self.logger.debug(
                        f"Model initialized: cache expired ({len(persistent_cache)} shots), "
                         "background refresh in progress"
                    )
                else:
                    self.logger.debug(
                        "Model initialized: no cache file, background refresh in progress"
                    )

        self.threede_scene_model = ThreeDESceneModel(self.cache_manager)
        # Cast to BaseShotModel for type safety (ShotModel inherits from BaseShotModel)
        self.previous_shots_model = PreviousShotsModel(
            cast("BaseShotModel", self.shot_model),
            self.cache_manager,
        )
        # Create persistent terminal manager if enabled
        # Feature flag for simplified launcher
        use_simplified_launcher = (
            os.environ.get("USE_SIMPLIFIED_LAUNCHER", "false").lower() == "true"
        )

        if use_simplified_launcher:
            # Use new simplified launcher (500 lines vs 2,872 lines)
            # Local application imports
            from simplified_launcher import SimplifiedLauncher

            self.logger.info(
                "Using SimplifiedLauncher - streamlined process management"
            )
            self.command_launcher = SimplifiedLauncher()

            # NOTE: SimplifiedLauncher implements ProcessPoolInterface
            # We could pass it to ShotModel, but currently ShotModel
            # was already created with self._process_pool above.
            # This is a known limitation of the SimplifiedLauncher approach.

            self.launcher_manager = None  # Not needed with simplified approach
            self.persistent_terminal = None
        else:
            # Use legacy launcher stack
            self.persistent_terminal: PersistentTerminalManager | None = None
            if Config.PERSISTENT_TERMINAL_ENABLED and Config.USE_PERSISTENT_TERMINAL:
                self.persistent_terminal = PersistentTerminalManager(
                    fifo_path=Config.PERSISTENT_TERMINAL_FIFO
                )

            self.command_launcher = CommandLauncher(
                persistent_terminal=self.persistent_terminal,
                parent=self,
            )
            self.launcher_manager = LauncherManager(
                process_pool=self._process_pool, parent=self
            )

        # NOTE: Current scene/shot context now managed by launcher_controller (single source of truth)
        self._closing = False  # Track shutdown state
        self._launcher_dialog: LauncherManagerDialog | None = None
        self._session_warmer: SessionWarmer | None = None  # Initialize session warmer
        self._last_selected_shot_name: str | None = (
            None  # Initialize last selected shot
        )

        # UI setup must come before controller initialization
        self._setup_ui()

        # Initialize 3DE controller after UI widgets are created
        # Skip controller in test environment to avoid threading issues
        if os.environ.get("PYTEST_CURRENT_TEST"):
            self.logger.info("Skipping ThreeDEController in test environment")
            self.threede_controller = None
        else:
            self.logger.info("Using ThreeDEController for 3DE scene management")
            # MainWindow implements ThreeDETarget protocol functionally at runtime
            # command_launcher union type and QMainWindow position-only params differ from Protocol
            self.threede_controller = ThreeDEController(self)  # pyright: ignore[reportArgumentType]

        # Initialize launcher controller for all launcher functionality
        self.logger.info("Using LauncherController for launcher management")
        # MainWindow implements LauncherTarget protocol functionally at runtime
        self.launcher_controller = LauncherController(self)
        self._setup_menu()
        self._setup_accessibility()  # Add accessibility support
        self._connect_signals()
        self.settings_controller.load_settings()  # Use refactored settings controller

        # Initial shot load - immediately, no delay
        # Skip in test environment if requested
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
        # Check if we're in mock mode
        is_mock_mode = os.environ.get("SHOTBOT_MOCK", "").lower() in (
            "1",
            "true",
            "yes",
        )

        # Set window title with mock indicator if applicable
        if is_mock_mode:
            self.setWindowTitle(
                f"{Config.APP_NAME} v{Config.APP_VERSION} - 🧪 MOCK MODE"
            )
        else:
            self.setWindowTitle(f"{Config.APP_NAME} v{Config.APP_VERSION}")
        self.resize(Config.DEFAULT_WINDOW_WIDTH, Config.DEFAULT_WINDOW_HEIGHT)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        # Left side - Tab widget for different views
        self.tab_widget = QTabWidget()
        # Disable focus indicators on tab bar
        self.tab_widget.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.splitter.addWidget(self.tab_widget)

        # Tab 1: My Shots
        # Always use Model/View architecture for maximum efficiency
        self.shot_item_model = ShotItemModel(cache_manager=self.cache_manager)
        self.shot_item_model.set_shots(self.shot_model.shots)
        self.shot_grid = ShotGridView(model=self.shot_item_model)
        _ = self.tab_widget.addTab(self.shot_grid, "My Shots")

        # Tab 2: Other 3DE scenes (using Model/View architecture)
        self.threede_shot_grid = ThreeDEGridView(model=self.threede_item_model)
        _ = self.tab_widget.addTab(self.threede_shot_grid, "Other 3DE scenes")

        # Tab 3: Previous Shots (approved/completed) - using Model/View architecture
        self.previous_shots_item_model = PreviousShotsItemModel(
            self.previous_shots_model, self.cache_manager
        )
        self.previous_shots_grid = PreviousShotsView(
            model=self.previous_shots_item_model
        )
        _ = self.tab_widget.addTab(self.previous_shots_grid, "Previous Shots")

        # Apply distinct color themes to each tab
        _ = self.tab_widget.currentChanged.connect(self._update_tab_accent_color)
        self._update_tab_accent_color(0)  # Initialize with first tab color

        # Right side - Controls and log
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Shot info panel
        self.shot_info_panel = ShotInfoPanel(self.cache_manager)
        right_layout.addWidget(self.shot_info_panel)

        # App launcher panel (improved UI)
        self.launcher_panel = LauncherPanel()
        # Signal connections handled by LauncherController
        self.launcher_panel.setMinimumHeight(400)  # Ensure adequate space
        right_layout.addWidget(self.launcher_panel)

        # Keep references to checkboxes for backward compatibility
        # (These are now managed by the launcher_panel)
        self.raw_plate_checkbox = (
            None  # Will access via launcher_panel.get_checkbox_state
        )
        self.open_latest_threede_checkbox = (
            None  # Will access via launcher_panel.get_checkbox_state
        )

        # Log viewer
        log_group = QGroupBox("Command Log")
        log_layout = QVBoxLayout(log_group)
        self.log_viewer = LogViewer()
        log_layout.addWidget(self.log_viewer)

        right_layout.addWidget(log_group)

        self.splitter.addWidget(right_widget)

        # Set splitter sizes (70/30 split)
        self.splitter.setSizes([840, 360])

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Add mock mode indicator to status bar if in mock mode
        if is_mock_mode:
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

        # Initialize notification manager
        _ = NotificationManager.initialize(self, self.status_bar)

        # Initialize progress manager
        _ = ProgressManager.initialize(self.status_bar)

        self._update_status("Ready")

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
        _ = increase_size_action.triggered.connect(self._increase_thumbnail_size)
        view_menu.addAction(increase_size_action)

        decrease_size_action = QAction("&Decrease Thumbnail Size", self)
        decrease_size_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
        _ = decrease_size_action.triggered.connect(self._decrease_thumbnail_size)
        view_menu.addAction(decrease_size_action)

        _ = view_menu.addSeparator()

        # Reset layout action
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

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")

        # Launcher manager
        self.launcher_manager_action = QAction("&Manage Custom Launchers...", self)
        self.launcher_manager_action.setShortcut("Ctrl+L")
        _ = self.launcher_manager_action.triggered.connect(
            self.launcher_controller.show_launcher_manager
        )
        tools_menu.addAction(self.launcher_manager_action)

        _ = tools_menu.addSeparator()

        # Custom launchers submenu
        self.custom_launcher_menu = tools_menu.addMenu("Custom &Launchers")
        # Launcher menu will be updated by LauncherController after initialization

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

        # Set up launcher panel (improved accessibility built into LauncherPanel)
        # AccessibilityManager.setup_launcher_buttons_accessibility is no longer needed

        # Set up tab widget
        AccessibilityManager.setup_tab_widget_accessibility(self.tab_widget)

        # Add comprehensive tooltips
        # MainWindow implements MainWindowProtocol functionally at runtime
        # Protocol uses optional attributes checked with hasattr at runtime
        AccessibilityManager.setup_comprehensive_tooltips(
            self  # pyright: ignore[reportArgumentType]
        )

        # Set up keyboard navigation tab order
        AccessibilityManager.setup_keyboard_navigation(self)  # pyright: ignore[reportArgumentType]

        # Apply focus indicator stylesheet
        existing_style = self.styleSheet() or ""
        focus_style = AccessibilityManager.add_focus_indicators_stylesheet()
        self.setStyleSheet(existing_style + focus_style)

    def _connect_signals(self) -> None:
        """Connect signals."""
        # Connect to shot model signals for reactive updates
        _ = self.shot_model.shots_loaded.connect(self._on_shots_loaded)
        _ = self.shot_model.shots_changed.connect(self._on_shots_changed)
        _ = self.shot_model.refresh_started.connect(self._on_refresh_started)
        _ = self.shot_model.refresh_finished.connect(self._on_refresh_finished)
        _ = self.shot_model.error_occurred.connect(self._on_shot_error)
        # Note: shot_model.shot_selected signal removed (vestigial - only logged, no action)
        _ = self.shot_model.cache_updated.connect(self._on_cache_updated)

        # Connect to cache manager for migration events
        _ = self.cache_manager.shots_migrated.connect(
            self._on_shots_migrated, Qt.ConnectionType.QueuedConnection
        )

        # Shot selection
        _ = self.shot_grid.shot_selected.connect(self._on_shot_selected)
        _ = self.shot_grid.shot_double_clicked.connect(self._on_shot_double_clicked)
        _ = self.shot_grid.app_launch_requested.connect(
            self.launcher_controller.launch_app
        )
        _ = self.shot_grid.show_filter_requested.connect(
            self._on_shot_show_filter_requested
        )
        _ = self.shot_grid.text_filter_requested.connect(
            self._on_shot_text_filter_requested
        )
        _ = self.shot_grid.recover_crashes_requested.connect(
            self._on_shot_recover_crashes_requested
        )

        # 3DE scene selection - handled by controller
        # Controller handles its own signal connections in __init__
        # Handle app launch with scene context (signal emits app_name, scene)
        def handle_threede_launch(app_name: str, scene: ThreeDEScene) -> None:
            self._launch_app_with_scene_context(app_name, scene)

        _ = self.threede_shot_grid.app_launch_requested.connect(handle_threede_launch)

        # 3DE show filter - handled by controller
        # Controller handles show filter in its own signal setup

        # Previous shots selection
        _ = self.previous_shots_grid.shot_selected.connect(self._on_shot_selected)
        _ = self.previous_shots_grid.shot_double_clicked.connect(
            self._on_shot_double_clicked
        )
        _ = self.previous_shots_grid.app_launch_requested.connect(
            self.launcher_controller.launch_app
        )
        _ = self.previous_shots_grid.show_filter_requested.connect(
            self._on_previous_show_filter_requested
        )
        _ = self.previous_shots_grid.text_filter_requested.connect(
            self._on_previous_text_filter_requested
        )
        _ = self.previous_shots_item_model.shots_updated.connect(
            self._on_previous_shots_updated
        )

        # Tab widget - handle tab changes to update shot context
        _ = self.tab_widget.currentChanged.connect(self._on_tab_changed)

        # Launcher signals are handled by LauncherController in its _setup_signals method

        # Synchronize thumbnail sizes between tabs
        _ = self.shot_grid.size_slider.valueChanged.connect(self._sync_thumbnail_sizes)
        _ = self.threede_shot_grid.size_slider.valueChanged.connect(
            self._sync_thumbnail_sizes,
        )
        _ = self.previous_shots_grid.size_slider.valueChanged.connect(
            self._sync_thumbnail_sizes,
        )

    def _initial_load(self) -> None:
        """Initial shot loading - instant from cache or async."""
        self.logger.info(">>> _initial_load() START")
        # Async initialization was already called in __init__, just pre-warm sessions
        self.logger.info("Using async initialization (already started in __init__)")
        # Pre-warm sessions in background thread to avoid UI freeze
        # Pre-warm bash sessions in background to avoid first-command delay
        # Skip in test environment to avoid threading issues
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            self.logger.info("Creating SessionWarmer with login shell mode...")
            self._session_warmer = SessionWarmer(self._process_pool)
            self.logger.info("Starting SessionWarmer thread...")
            self._session_warmer.start()
            self.logger.info("SessionWarmer thread started in background")
        else:
            self._session_warmer = None
            self.logger.debug("Skipping SessionWarmer in test environment")

        has_cached_shots = bool(self.shot_model.shots)
        has_cached_scenes = bool(self.threede_scene_model.scenes)

        # Show cached shots immediately if available (should already be loaded)
        if has_cached_shots:
            self._refresh_shot_display()
            self.logger.info(
                f"Displayed {len(self.shot_model.shots)} cached shots instantly"
            )
        else:
            # No cache, but let's check one more time
            self.logger.info(
                "No cached shots found on initial check, attempting explicit cache load"
            )
            if self.shot_model.test_load_from_cache():
                has_cached_shots = True
                self._refresh_shot_display()
                self.logger.info(
                    f"Loaded and displayed {len(self.shot_model.shots)} shots from cache"
                )

            # Restore last selected shot if available
            if hasattr(self, "_last_selected_shot_name") and isinstance(
                self._last_selected_shot_name,
                str,
            ):
                shot = self.shot_model.find_shot_by_name(self._last_selected_shot_name)
                if shot:
                    self.shot_grid.select_shot_by_name(shot.full_name)

        # Show cached 3DE scenes immediately if available
        if has_cached_scenes:
            self.threede_item_model.set_scenes(self.threede_scene_model.scenes)
            # Populate show filter with available shows
            self.threede_shot_grid.populate_show_filter(self.threede_scene_model)

        # Update status with what was loaded from cache
        if has_cached_shots and has_cached_scenes:
            self._update_status(
                (
                    f"Loaded {len(self.shot_model.shots)} shots and "
                     f"{len(self.threede_scene_model.scenes)} 3DE scenes from cache"
                ),
            )
            # Schedule background refresh for fresh data (non-blocking)
            QTimer.singleShot(500, self._refresh_shots)
        elif has_cached_shots:
            self._update_status(f"Loaded {len(self.shot_model.shots)} shots from cache")
            # Schedule background refresh for fresh data (non-blocking)
            QTimer.singleShot(500, self._refresh_shots)
        elif has_cached_scenes:
            self._update_status(
                f"Loaded {len(self.threede_scene_model.scenes)} 3DE scenes from cache",
            )
        else:
            self._update_status("Loading shots and scenes...")
            # No cache exists - background refresh already started by initialize_async()
            self.logger.info(
                "No cached data found - background refresh already in progress from initialize_async()",
            )

        # Note: Auto-refresh removed from PreviousShotsModel (persistent incremental caching)
        # Previous shots now only refresh on explicit user action via "Refresh" button

        # Trigger initial refresh for previous shots ONLY after shots are loaded
        # This prevents the "No target shows found" warning when shots haven't loaded yet
        _ = self.shot_model.shots_loaded.connect(self._trigger_previous_shots_refresh)
        _ = self.shot_model.shots_changed.connect(self._trigger_previous_shots_refresh)

        # If shots are already loaded from cache, trigger refresh immediately
        if self.shot_model.shots:
            self.logger.info(
                "Shots already loaded from cache, triggering previous shots refresh immediately"
            )
            QTimer.singleShot(100, self.previous_shots_model.refresh_shots)

        # Only start 3DE discovery if we have shots AND cache is invalid/expired
        # This avoids unnecessary scans when we already know there are no scenes
        if has_cached_shots:
            # Check if we have a valid cache (including valid empty results)
            if not self.cache_manager.has_valid_threede_cache():
                self.logger.info("3DE cache invalid/expired - starting discovery")
                if self.threede_controller:
                    QTimer.singleShot(
                        100, self.threede_controller.refresh_threede_scenes
                    )
            else:
                self.logger.info("3DE cache is valid - skipping initial scan")
                # Cache is valid but might be empty - that's OK, we cached the "no scenes" state

        self.logger.info("<<< _initial_load() COMPLETE - returning")

    def _refresh_shots(self) -> None:
        """Refresh shot list with progress indication."""
        self.logger.info(">>> MainWindow._refresh_shots() called (via QTimer)")
        # Delegate to RefreshOrchestrator
        self.logger.info("Delegating to RefreshOrchestrator._refresh_shots()...")
        self.refresh_orchestrator._refresh_shots()  # pyright: ignore[reportPrivateUsage]
        self.logger.info("<<< MainWindow._refresh_shots() complete")

    # Note: Background refresh methods removed - now handled by reactive signals

    def _refresh_shot_display(self) -> None:
        """Refresh the shot display using Model/View implementation."""
        # Delegate to RefreshOrchestrator
        self.refresh_orchestrator._refresh_shot_display()  # pyright: ignore[reportPrivateUsage]

    def _on_shots_loaded(self, shots: list[Shot]) -> None:
        """Handle shots loaded signal from model.

        Args:
            shots: List of loaded Shot objects
        """
        # Delegate to RefreshOrchestrator
        self.refresh_orchestrator.handle_shots_loaded(shots)

    def _on_shots_changed(self, shots: list[Shot]) -> None:
        """Handle shots changed signal from model.

        Args:
            shots: List of updated Shot objects
        """
        # Delegate to RefreshOrchestrator
        self.refresh_orchestrator.handle_shots_changed(shots)

    def _on_refresh_started(self) -> None:
        """Handle refresh started signal from model."""
        # Delegate to RefreshOrchestrator
        self.refresh_orchestrator.handle_refresh_started()

    def _on_refresh_finished(self, success: bool, has_changes: bool) -> None:
        """Handle refresh finished signal from model.

        Args:
            success: Whether the refresh was successful
            has_changes: Whether the shot list changed
        """
        # Delegate to RefreshOrchestrator
        self.refresh_orchestrator.handle_refresh_finished(success, has_changes)

    def _on_shot_error(self, error_msg: str) -> None:
        """Handle error signal from model.

        Args:
            error_msg: The error message
        """
        self.logger.error(f"Shot model error: {error_msg}")
        self._update_status(f"Error: {error_msg}")

    def _trigger_previous_shots_refresh(self, shots: list[Shot]) -> None:
        """Trigger previous shots refresh only after shots are loaded.

        This method is connected to the shot model's shots_loaded signal to ensure
        that previous shots scanning only starts when active shots are available.
        This prevents the "No target shows found" warning.

        Args:
            shots: The loaded shots (from signal)
        """
        # Delegate to RefreshOrchestrator
        self.refresh_orchestrator.trigger_previous_shots_refresh(shots)


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
        # Scene/shot context is automatically cleared by launcher_controller when switching contexts

        if index == 0:  # My Shots tab
            # Get the current selection from My Shots
            selected_shot = self.shot_grid.selected_shot
            if selected_shot:
                # Re-apply the shot selection to update context
                self._on_shot_selected(selected_shot)
            else:
                # Clear selection
                self._on_shot_selected(None)

        elif index == 1:  # Other 3DE scenes tab
            # Get the current selection from 3DE scenes
            selected_scene = self.threede_shot_grid.selected_scene
            if selected_scene:
                # Re-apply the scene selection to update context
                if self.threede_controller:
                    self.threede_controller.on_scene_selected(selected_scene)
            else:
                # Clear selection
                self.launcher_controller.set_current_shot(None)
                self.shot_info_panel.set_shot(None)
                self.launcher_panel.set_shot(None)
                self.launcher_controller.update_launcher_menu_availability(False)

        elif index == 2:  # Previous Shots tab
            # Get the current selection from Previous Shots
            selected_shot = self.previous_shots_grid.selected_shot
            if selected_shot:
                # Re-apply the shot selection to update context
                self._on_shot_selected(selected_shot)
            else:
                # Clear selection
                self._on_shot_selected(None)

    def _update_tab_accent_color(self, index: int) -> None:
        """Update tab styling with distinct background color based on selected tab.

        Applies a full colored background to the selected tab to provide strong
        visual distinction between the three main tabs (My Shots, Other 3DE, Previous).

        Args:
            index: Index of the currently selected tab (0=My Shots, 1=Other 3DE, 2=Previous)
        """
        # Define distinct colors for each tab (main and darker variant)
        # Note: Colors are defined for future dynamic styling but currently unused
        tab_colors = {
            0: ("#2196F3", "#1976D2"),  # Blue - My Shots
            1: ("#00BCD4", "#00ACC1"),  # Cyan - Other 3DE scenes
            2: ("#9C27B0", "#7B1FA2"),  # Purple - Previous Shots
        }

        _ = tab_colors.get(index, ("#2196F3", "#1976D2"))  # Reserved for future styling

        # Professional tab design: muted colors, subtle accents, proper proportions
        # Qt supports :first, :middle, :last (NOT :nth-child)
        tab_stylesheet = """
            /* Tab bar - disable focus indicators */
            QTabBar {
                qproperty-drawBase: 0;
            }

            /* Base tab styling - professional proportions */
            QTabBar::tab {
                min-width: 120px;
                font-size: 14px;
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

        # Apply stylesheet to tab bar only (preserves design system defaults)
        self.tab_widget.tabBar().setStyleSheet(tab_stylesheet)

    def _on_shot_selected(self, shot: Shot | None) -> None:
        """Handle shot selection or deselection.

        Args:
            shot: Shot object or None to clear selection
        """
        # Scene context is automatically cleared by launcher_controller.set_current_shot()

        if shot is None:
            # Handle deselection
            self.launcher_controller.set_current_shot(None)
            self.shot_info_panel.set_shot(None)

            # Update launcher panel to disable buttons
            self.launcher_panel.set_shot(None)

            # Clear plate selectors for all apps
            for app_name in ["nuke", "maya", "3de", "rv"]:
                if app_name in self.launcher_panel.app_sections:
                    self.launcher_panel.app_sections[app_name].set_available_plates([])

            # Update custom launcher menu availability
            self.launcher_controller.update_launcher_menu_availability(False)

            # Reset window title
            self.setWindowTitle(Config.APP_NAME)

            # Update status
            self._update_status("No shot selected")

            # Clear saved selection
            self._last_selected_shot_name = None
            self.settings_controller.save_settings()
        else:
            # Handle selection - use launcher controller
            self.launcher_controller.set_current_shot(shot)

            # Update shot info panel
            self.shot_info_panel.set_shot(shot)

            # Update launcher panel to enable buttons
            self.launcher_panel.set_shot(shot)

            # Update plate selectors for all apps
            # Local application imports
            from plate_discovery import PlateDiscovery

            available_plates = PlateDiscovery.get_available_plates(shot.workspace_path)
            for app_name in ["nuke", "maya", "3de", "rv"]:
                if app_name in self.launcher_panel.app_sections:
                    app_section = self.launcher_panel.app_sections[app_name]
                    app_section.set_available_plates(available_plates)

                    # Auto-select first plate if available (prevents validation errors)
                    if available_plates and app_section.plate_selector:
                        app_section.plate_selector.setCurrentIndex(0)
                        self.logger.debug(
                            f"Auto-selected first plate '{available_plates[0]}' for {app_name}"
                        )

            # Update custom launcher menu availability
            self.launcher_controller.update_launcher_menu_availability(True)

            # Update window title
            self.setWindowTitle(f"{Config.APP_NAME} - {shot.full_name} ({shot.show})")

            # Update status
            self._update_status(f"Selected: {shot.full_name} ({shot.show})")

            # Save selection
            self._last_selected_shot_name = shot.full_name
            self.settings_controller.save_settings()

    def _on_shot_double_clicked(self, _shot: Shot) -> None:
        """Handle shot double click - launch default app."""
        self.launcher_controller.launch_app(Config.DEFAULT_APP)

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
        # Set the scene context in launcher controller
        self.launcher_controller.set_current_scene(scene)

        # Launch the application
        self.launcher_controller.launch_app(app_name)

    def _apply_show_filter(
        self, item_model: object, model: object, show: str, tab_name: str
    ) -> None:
        """Generic show filter handler for all tabs.

        Args:
            item_model: The item model to apply the filter to (ShotItemModel, ThreeDEItemModel, or PreviousShotsItemModel)
            model: The data model to pass to the item model (ShotModel, ThreeDESceneModel, or PreviousShotsModel)
            show: Show name to filter by, or empty string for all shows
            tab_name: Human-readable tab name for logging
        """
        # Convert empty string back to None for the model
        show_filter = show if show else None

        # Apply filter to item model
        # Different item models have varying set_show_filter signatures:
        # - ShotItemModel.set_show_filter(BaseShotModel, str | None)
        # - PreviousShotsItemModel.set_show_filter(PreviousShotsModel, str | None)
        # We use object types for generic handling across all tabs
        item_model.set_show_filter(model, show_filter)  # pyright: ignore[reportAttributeAccessIssue]

        self.logger.info(
            f"Applied {tab_name} show filter: {show if show else 'All Shows'}"
        )

    def _on_shot_show_filter_requested(self, show: str) -> None:
        """Handle show filter request from My Shots grid view."""
        self._apply_show_filter(self.shot_item_model, self.shot_model, show, "My Shots")

    def _on_shot_text_filter_requested(self, text: str) -> None:
        """Handle text filter request from My Shots grid view."""
        filter_text = text.strip() if text else None
        # Cast to BaseShotModel to access inherited methods
        base_model = cast("BaseShotModel", self.shot_model)
        base_model.set_text_filter(filter_text)

        # Update item model with filtered shots
        filtered_shots = base_model.get_filtered_shots()
        # get_filtered_shots returns list[Shot], set_items needs list[ItemType]
        self.shot_item_model.set_items(filtered_shots)

        self.logger.debug(
            f"My Shots text filter applied: '{filter_text}' - {len(filtered_shots)} shots"
        )

    @Slot()
    def _on_shot_recover_crashes_requested(self) -> None:
        """Handle recovery crashes request from My Shots grid view.

        Scans for crash files in the current shot's workspace and presents
        a recovery dialog if any are found.
        """
        # Get current shot or scene from launcher controller
        # Check both since either can provide workspace context
        current_shot = self.launcher_controller.current_shot
        current_scene = self.launcher_controller.current_scene

        if not current_shot and not current_scene:
            # Local application imports
            from notification_manager import NotificationManager
            NotificationManager.warning(
                "No Shot Selected",
                "Please select a shot before attempting crash recovery."
            )
            return

        # Use shot if available, otherwise derive from scene
        # At this point, at least one must be non-None due to guard above
        if current_shot:
            workspace_path = current_shot.workspace_path
            full_name = current_shot.full_name
        else:
            # current_scene must be non-None here
            assert current_scene is not None  # Type narrowing
            workspace_path = current_scene.workspace_path
            full_name = current_scene.full_name
        self.logger.info(f"Scanning for crash files in shot workspace: {workspace_path}")

        # Import recovery components
        from threede_recovery import CrashFileInfo, ThreeDERecoveryManager
        from threede_recovery_dialog import (
            ThreeDERecoveryDialog,
            ThreeDERecoveryResultDialog,
        )

        # Create recovery manager
        recovery_manager = ThreeDERecoveryManager()

        # Find crash files in workspace
        try:
            crash_files = recovery_manager.find_crash_files(workspace_path, recursive=True)
        except Exception as e:
            self.logger.error(f"Error scanning for crash files: {e}")
            # Local application imports
            from notification_manager import NotificationManager
            NotificationManager.error(
                "Scan Error",
                f"Failed to scan for crash files: {e}"
            )
            return

        if not crash_files:
            # Local application imports
            from notification_manager import NotificationManager
            message = f"No 3DE crash files found in workspace for {full_name}."
            NotificationManager.info(message)
            return

        # Show recovery dialog
        self.logger.info(f"Found {len(crash_files)} crash file(s), showing recovery dialog")
        dialog = ThreeDERecoveryDialog(crash_files, parent=self.shot_grid)

        # Connect recovery signal
        def on_recovery_requested(crash_info: CrashFileInfo) -> None:  # type: ignore[name-defined]
            self.logger.info(f"Recovery requested for: {crash_info.crash_path.name}")
            try:
                # Perform recovery and archiving
                recovered_path, archived_path = recovery_manager.recover_and_archive(crash_info)

                # Show success result
                result_dialog = ThreeDERecoveryResultDialog(
                    success=True,
                    recovered_path=recovered_path,
                    archived_path=archived_path,
                    parent=self.shot_grid,
                )
                _ = result_dialog.exec()

                # Local application imports
                from notification_manager import NotificationManager, NotificationType
                NotificationManager.toast(
                    f"Recovered: {recovered_path.name}",
                    NotificationType.SUCCESS
                )

            except Exception as e:
                self.logger.error(f"Failed to recover crash file: {e}")
                # Show error result
                result_dialog = ThreeDERecoveryResultDialog(
                    success=False,
                    error_message=str(e),
                    parent=self.shot_grid,
                )
                _ = result_dialog.exec()

        _ = dialog.recovery_requested.connect(on_recovery_requested)
        _ = dialog.exec()

    def _on_previous_show_filter_requested(self, show: str) -> None:
        """Handle show filter request from Previous Shots grid view."""
        self._apply_show_filter(
            self.previous_shots_item_model,
            self.previous_shots_model,
            show,
            "Previous Shots",
        )

    def _on_previous_text_filter_requested(self, text: str) -> None:
        """Handle text filter request from Previous Shots grid view."""
        filter_text = text.strip() if text else None
        self.previous_shots_model.set_text_filter(filter_text)

        # Update item model with filtered shots
        filtered_shots = self.previous_shots_model.get_filtered_shots()
        # get_filtered_shots returns list[Shot], set_items needs list[ItemType]
        self.previous_shots_item_model.set_items(filtered_shots)

        self.logger.debug(
            f"Previous Shots text filter applied: '{filter_text}' - {len(filtered_shots)} shots"
        )

    def _on_previous_shots_updated(self) -> None:
        """Handle previous shots updated signal."""
        # Populate show filter with available shows
        self.previous_shots_grid.populate_show_filter(self.previous_shots_model)
        self.logger.debug("Previous shots updated, refreshed show filter")

    def _increase_thumbnail_size(self) -> None:
        """Increase thumbnail size."""
        # Get current size from active tab
        tab_index = self.tab_widget.currentIndex()
        if tab_index == 0:
            current = self.shot_grid.size_slider.value()
        elif tab_index == 1:
            current = self.threede_shot_grid.size_slider.value()
        else:
            current = self.previous_shots_grid.size_slider.value()

        new_size = min(current + 20, Config.MAX_THUMBNAIL_SIZE)
        # This will trigger _sync_thumbnail_sizes to update all grids
        if tab_index == 0:
            self.shot_grid.size_slider.setValue(new_size)
        elif tab_index == 1:
            self.threede_shot_grid.size_slider.setValue(new_size)
        else:
            self.previous_shots_grid.size_slider.setValue(new_size)

    def _decrease_thumbnail_size(self) -> None:
        """Decrease thumbnail size."""
        # Get current size from active tab
        tab_index = self.tab_widget.currentIndex()
        if tab_index == 0:
            current = self.shot_grid.size_slider.value()
        elif tab_index == 1:
            current = self.threede_shot_grid.size_slider.value()
        else:
            current = self.previous_shots_grid.size_slider.value()

        new_size = max(current - 20, Config.MIN_THUMBNAIL_SIZE)
        # This will trigger _sync_thumbnail_sizes to update all grids
        if tab_index == 0:
            self.shot_grid.size_slider.setValue(new_size)
        elif tab_index == 1:
            self.threede_shot_grid.size_slider.setValue(new_size)
        else:
            self.previous_shots_grid.size_slider.setValue(new_size)

    def _sync_thumbnail_sizes(self, value: int) -> None:
        """Synchronize thumbnail sizes between all tabs."""
        # Use signal blocking instead of disconnection to prevent race conditions
        # This is thread-safe and guaranteed to work

        # Block signals temporarily to prevent recursion
        shot_grid_was_blocked = self.shot_grid.size_slider.blockSignals(True)
        threede_grid_was_blocked = self.threede_shot_grid.size_slider.blockSignals(True)
        previous_grid_was_blocked = self.previous_shots_grid.size_slider.blockSignals(
            True
        )

        try:
            # Update all sliders without triggering signals
            self.shot_grid.size_slider.setValue(value)
            self.threede_shot_grid.size_slider.setValue(value)
            self.previous_shots_grid.size_slider.setValue(value)

            # All grids now use Model/View, size change is handled by delegates

            # Update size labels
            self.shot_grid.size_label.setText(f"{value}px")
            self.threede_shot_grid.size_label.setText(f"{value}px")
            self.previous_shots_grid.size_label.setText(f"{value}px")
        finally:
            # Always restore signal state, even if an exception occurs
            # This prevents leaving signals permanently blocked
            _ = self.shot_grid.size_slider.blockSignals(shot_grid_was_blocked)
            _ = self.threede_shot_grid.size_slider.blockSignals(
                threede_grid_was_blocked
            )
            _ = self.previous_shots_grid.size_slider.blockSignals(
                previous_grid_was_blocked
            )

    def _update_status(self, message: str) -> None:
        """Update status bar."""
        self.status_bar.showMessage(message)

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

    @property
    def closing(self) -> bool:
        """Public property to check if the window is closing."""
        return self._closing

    @closing.setter
    def closing(self, value: bool) -> None:
        """Set the closing state."""
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
        """Public method to update status bar."""
        self._update_status(message)

    def update_launcher_menu_availability(self, available: bool) -> None:
        """Public method to update launcher menu availability."""
        self.launcher_controller.update_launcher_menu_availability(available)

    def enable_custom_launcher_buttons(self, enabled: bool) -> None:
        """Public method to enable/disable custom launcher buttons."""
        self.launcher_controller.enable_custom_launcher_buttons(enabled)

    def launch_app(self, app_name: str) -> None:
        """Public method to launch an application."""
        self.launcher_controller.launch_app(app_name)

    def cleanup(self) -> None:
        """Explicit cleanup method for proper resource management.

        This method can be called independently of closeEvent, making it
        suitable for test environments where widgets are destroyed without
        proper close events.
        """
        self.logger.debug("Starting explicit MainWindow cleanup")
        # Delegate to CleanupManager
        self.cleanup_manager.perform_cleanup()
        self.logger.debug("Completed explicit MainWindow cleanup")

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Thread-safe close event handler.

        Implements proper shutdown sequence using CleanupManager.
        """
        self.logger.debug("MainWindow closeEvent - starting cleanup")

        # Delegate to CleanupManager
        self.cleanup_manager.perform_cleanup()

        # Save settings before closing
        self.settings_controller.save_settings()

        self.logger.debug("MainWindow closeEvent - cleanup complete")
        event.accept()


# Background refresh methods and BackgroundRefreshWorker removed - ShotModel now uses reactive signals instead of polling
