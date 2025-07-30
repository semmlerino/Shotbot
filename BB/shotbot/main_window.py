"""Main window for ShotBot application."""

import json
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from command_launcher import CommandLauncher
from config import Config
from log_viewer import LogViewer
from shot_grid import ShotGrid
from shot_info_panel import ShotInfoPanel
from shot_model import Shot, ShotModel


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.shot_model = ShotModel()
        self.command_launcher = CommandLauncher()
        self._setup_ui()
        self._setup_menu()
        self._connect_signals()
        self._load_settings()

        # Initial shot load
        QTimer.singleShot(100, self._initial_load)

        # Set up background refresh timer (every 5 minutes)
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._background_refresh)
        self.refresh_timer.start(5 * 60 * 1000)  # 5 minutes in milliseconds

    def _setup_ui(self):
        """Set up the main UI."""
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

        # Left side - Shot grid
        self.shot_grid = ShotGrid(self.shot_model)
        self.splitter.addWidget(self.shot_grid)

        # Right side - Controls and log
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Shot info panel
        self.shot_info_panel = ShotInfoPanel()
        right_layout.addWidget(self.shot_info_panel)

        # App launcher buttons
        launcher_group = QGroupBox("Launch Applications")
        launcher_layout = QVBoxLayout(launcher_group)

        self.app_buttons: dict[str, QPushButton] = {}
        for app_name, command in Config.APPS.items():
            button = QPushButton(app_name.upper())
            button.clicked.connect(lambda checked, app=app_name: self._launch_app(app))
            button.setEnabled(False)  # Disabled until shot selected
            launcher_layout.addWidget(button)
            self.app_buttons[app_name] = button

        # Add undistortion checkbox
        self.undistortion_checkbox = QCheckBox("Include undistortion nodes (Nuke)")
        self.undistortion_checkbox.setToolTip(
            "When launching Nuke, automatically include the latest undistortion .nk file"
        )
        launcher_layout.addWidget(self.undistortion_checkbox)

        # Add raw plate checkbox
        self.raw_plate_checkbox = QCheckBox("Include raw plate (Nuke)")
        self.raw_plate_checkbox.setToolTip(
            "When launching Nuke, automatically create a Read node for the raw plate"
        )
        launcher_layout.addWidget(self.raw_plate_checkbox)

        right_layout.addWidget(launcher_group)

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
        self._update_status("Ready")

    def _setup_menu(self):
        """Set up menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        refresh_action = QAction("&Refresh Shots", self)
        refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh_action.triggered.connect(self._refresh_shots)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()

        exit_action = QAction("&Exit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        increase_size_action = QAction("&Increase Thumbnail Size", self)
        increase_size_action.setShortcut(QKeySequence.StandardKey.ZoomIn)
        increase_size_action.triggered.connect(self._increase_thumbnail_size)
        view_menu.addAction(increase_size_action)

        decrease_size_action = QAction("&Decrease Thumbnail Size", self)
        decrease_size_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
        decrease_size_action.triggered.connect(self._decrease_thumbnail_size)
        view_menu.addAction(decrease_size_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _connect_signals(self):
        """Connect signals."""
        # Shot selection
        self.shot_grid.shot_selected.connect(self._on_shot_selected)
        self.shot_grid.shot_double_clicked.connect(self._on_shot_double_clicked)

        # Command launcher
        self.command_launcher.command_executed.connect(self.log_viewer.add_command)
        self.command_launcher.command_error.connect(self.log_viewer.add_error)

    def _initial_load(self):
        """Initial shot loading."""
        # First, show cached shots immediately if available
        if self.shot_model.shots:
            self.shot_grid.refresh_shots()
            self._update_status(
                f"Loaded {len(self.shot_model.shots)} shots (from cache)"
            )

            # Restore last selected shot if available
            if hasattr(self, "_last_selected_shot_name"):
                shot = self.shot_model.find_shot_by_name(self._last_selected_shot_name)
                if shot:
                    self.shot_grid.select_shot(shot)

        # Then refresh in background
        QTimer.singleShot(500, self._refresh_shots)

    def _refresh_shots(self):
        """Refresh shot list."""
        self._update_status("Refreshing shots...")

        success, has_changes = self.shot_model.refresh_shots()

        if success:
            if has_changes:
                self.shot_grid.refresh_shots()
                self._update_status(f"Loaded {len(self.shot_model.shots)} shots")
            else:
                self._update_status(f"{len(self.shot_model.shots)} shots (no changes)")

            # Restore last selected shot if available
            if hasattr(self, "_last_selected_shot_name"):
                shot = self.shot_model.find_shot_by_name(self._last_selected_shot_name)
                if shot:
                    self.shot_grid.select_shot(shot)
        else:
            self._update_status("Failed to load shots")
            QMessageBox.warning(
                self,
                "Error",
                "Failed to load shots. Make sure 'ws -sg' command is available.",
            )

    def _background_refresh(self):
        """Refresh shots in background without interrupting user."""
        # Save current selection
        current_shot_name = None
        if hasattr(self, "_last_selected_shot_name"):
            current_shot_name = self._last_selected_shot_name

        # Refresh quietly
        success, has_changes = self.shot_model.refresh_shots()

        if success and has_changes:
            # Only update UI if there were actual changes
            self.shot_grid.refresh_shots()
            self._update_status(
                f"Updated: {len(self.shot_model.shots)} shots (new changes)"
            )

            # Restore selection if possible
            if current_shot_name:
                shot = self.shot_model.find_shot_by_name(current_shot_name)
                if shot:
                    self.shot_grid.select_shot(shot)

    def _on_shot_selected(self, shot: Shot):
        """Handle shot selection."""
        self.command_launcher.set_current_shot(shot)

        # Update shot info panel
        self.shot_info_panel.set_shot(shot)

        # Enable app buttons
        for button in self.app_buttons.values():
            button.setEnabled(True)

        # Update window title
        self.setWindowTitle(f"{Config.APP_NAME} - {shot.full_name} ({shot.show})")

        # Update status
        self._update_status(f"Selected: {shot.full_name} ({shot.show})")

        # Save selection
        self._last_selected_shot_name = shot.full_name
        self._save_settings()

    def _on_shot_double_clicked(self, shot: Shot):
        """Handle shot double click - launch default app."""
        self._launch_app(Config.DEFAULT_APP)

    def _launch_app(self, app_name: str):
        """Launch an application."""
        # Check if we should include undistortion and/or raw plate for Nuke
        include_undistortion = (
            app_name == "nuke" and self.undistortion_checkbox.isChecked()
        )
        include_raw_plate = app_name == "nuke" and self.raw_plate_checkbox.isChecked()

        if self.command_launcher.launch_app(
            app_name, include_undistortion, include_raw_plate
        ):
            self._update_status(f"Launched {app_name}")
        else:
            self._update_status(f"Failed to launch {app_name}")

    def _increase_thumbnail_size(self):
        """Increase thumbnail size."""
        current = self.shot_grid.size_slider.value()
        new_size = min(current + 20, Config.MAX_THUMBNAIL_SIZE)
        self.shot_grid.size_slider.setValue(new_size)

    def _decrease_thumbnail_size(self):
        """Decrease thumbnail size."""
        current = self.shot_grid.size_slider.value()
        new_size = max(current - 20, Config.MIN_THUMBNAIL_SIZE)
        self.shot_grid.size_slider.setValue(new_size)

    def _update_status(self, message: str):
        """Update status bar."""
        self.status_bar.showMessage(message)

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            f"About {Config.APP_NAME}",
            f"{Config.APP_NAME} v{Config.APP_VERSION}\n\n"
            "VFX Shot Launcher\n\n"
            "A tool for browsing and launching applications in shot context.",
        )

    def _load_settings(self):
        """Load settings from file."""
        if Config.SETTINGS_FILE.exists():
            try:
                with open(Config.SETTINGS_FILE, "r") as f:
                    settings = json.load(f)

                # Restore window geometry
                if "geometry" in settings:
                    self.restoreGeometry(bytes.fromhex(settings["geometry"]))

                # Restore splitter state
                if "splitter" in settings:
                    self.splitter.restoreState(bytes.fromhex(settings["splitter"]))

                # Restore last selected shot
                if "last_shot" in settings:
                    self._last_selected_shot_name = settings["last_shot"]

                # Restore thumbnail size
                if "thumbnail_size" in settings:
                    self.shot_grid.size_slider.setValue(settings["thumbnail_size"])

                # Restore undistortion checkbox state
                if "include_undistortion" in settings:
                    self.undistortion_checkbox.setChecked(
                        settings["include_undistortion"]
                    )

                # Restore raw plate checkbox state
                if "include_raw_plate" in settings:
                    self.raw_plate_checkbox.setChecked(settings["include_raw_plate"])

            except Exception as e:
                print(f"Error loading settings: {e}")

    def _save_settings(self):
        """Save settings to file."""
        # Convert QByteArray to string for JSON serialization
        geometry_hex = self.saveGeometry().toHex()
        splitter_hex = self.splitter.saveState().toHex()

        # Convert QByteArray to string
        settings: dict[str, Any] = {
            "geometry": str(geometry_hex.data(), "ascii"),
            "splitter": str(splitter_hex.data(), "ascii"),
            "thumbnail_size": self.shot_grid.size_slider.value(),
            "include_undistortion": self.undistortion_checkbox.isChecked(),
            "include_raw_plate": self.raw_plate_checkbox.isChecked(),
        }

        # Save last selected shot
        if hasattr(self, "_last_selected_shot_name"):
            settings["last_shot"] = self._last_selected_shot_name

        # Create settings directory
        Config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Save to file
        try:
            with open(Config.SETTINGS_FILE, "w") as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle close event."""
        self._save_settings()
        event.accept()
