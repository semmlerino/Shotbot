#!/usr/bin/env python3
"""
Refactored Main Window for PyMPEG
Uses focused classes for better separation of concerns
"""

import shutil
import sys
from pathlib import Path

from conversion_controller import ConversionController

# Import our focused classes
from file_list_widget import FileListWidget
from process_manager import ProcessManager
from process_monitor import ProcessMonitor
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from settings_panel import SettingsPanel

from config import AppConfig, LogConfig
from ui_update_manager import UIUpdateManager


class MainWindow(QMainWindow):
    """Simplified main window using focused component classes"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{AppConfig.APP_NAME} - RTX Optimized")
        self.resize(AppConfig.DEFAULT_WINDOW_WIDTH, AppConfig.DEFAULT_WINDOW_HEIGHT)

        self.settings = QSettings(AppConfig.SETTINGS_ORG, AppConfig.SETTINGS_APP)
        self._check_ffmpeg()

        # State
        self.last_dir = self.settings.value("lastDir", str(Path.cwd()))
        self.is_converting = False

        # Initialize core components
        self.process_manager = ProcessManager(self)
        self.conversion_controller = ConversionController(self.process_manager, self)
        self.settings_panel = SettingsPanel(self)

        # Initialize UI update manager for efficient updates
        self.ui_update_manager = UIUpdateManager(self)
        _ = self.ui_update_manager.update_ui.connect(self._handle_ui_updates)
        self.ui_update_manager.start()

        # UI Components (will be created in _init_ui)
        self.file_list: FileListWidget
        self.process_monitor: ProcessMonitor
        self.main_log: QPlainTextEdit
        self.overall_progress_bar: QProgressBar
        self.start_btn: QPushButton
        self.stop_btn: QPushButton
        self.status_bar: QStatusBar

        self._init_ui()
        self._connect_signals()
        self._restore_state()

        # Connect process monitor to conversion controller after UI is created
        if self.process_monitor:
            self.conversion_controller.set_process_monitor(self.process_monitor)

        # Connect file list widget to conversion controller for status updates
        if self.file_list:
            self.conversion_controller.set_file_list_widget(self.file_list)

    def _check_ffmpeg(self):
        """Check if FFmpeg is available"""
        if not shutil.which("ffmpeg"):
            QMessageBox.critical(
                None,
                "FFmpeg Not Found",
                "FFmpeg executable not found in PATH. Please install or add to PATH.",
            )
            sys.exit(1)

    def _init_ui(self):
        """Initialize the user interface"""
        # Create menu bar
        self._create_menu_bar()

        # Create toolbar
        self._create_toolbar()

        # Create central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # Create main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Left panel - File list and settings
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)

        # Right panel - Process monitoring and logs
        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)

        # Set splitter proportions
        splitter.setSizes([400, 600])

        # Control buttons
        button_layout = self._create_button_layout()
        main_layout.addLayout(button_layout)

        # Overall progress bar
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setVisible(False)
        main_layout.addWidget(self.overall_progress_bar)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _create_menu_bar(self):
        """Create the menu bar"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        add_files_action = QAction(QIcon.fromTheme("document-open"), "Add Files", self)
        add_files_action.setShortcut("Ctrl+O")
        _ = add_files_action.triggered.connect(self.add_files)

        # Batch operations
        select_all_action = QAction("Select All", self)
        select_all_action.setShortcut("Ctrl+A")
        _ = select_all_action.triggered.connect(self.select_all_files)

        clear_completed_action = QAction("Clear Completed", self)
        clear_completed_action.setShortcut("Ctrl+Shift+C")
        _ = clear_completed_action.triggered.connect(self.clear_completed_files)

        remove_failed_action = QAction("Remove Failed", self)
        remove_failed_action.setShortcut("Ctrl+Shift+F")
        _ = remove_failed_action.triggered.connect(self.remove_failed_files)

        exit_action = QAction(QIcon.fromTheme("application-exit"), "E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        _ = exit_action.triggered.connect(self.close)

        file_menu.addAction(add_files_action)
        file_menu.addSeparator()
        file_menu.addAction(select_all_action)
        file_menu.addAction(clear_completed_action)
        file_menu.addAction(remove_failed_action)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")

        clear_log_action = QAction(QIcon.fromTheme("edit-clear"), "Clear Log", self)
        clear_log_action.setShortcut("Ctrl+L")
        _ = clear_log_action.triggered.connect(self._clear_main_log)
        tools_menu.addAction(clear_log_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        _ = about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_toolbar(self):
        """Create the toolbar"""
        toolbar = self.addToolBar("Main Toolbar")
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)

        # Add files action
        add_action = QAction(QIcon.fromTheme("document-open"), "Add Files", self)
        _ = add_action.triggered.connect(self.add_files)
        toolbar.addAction(add_action)

        toolbar.addSeparator()

        # Clear log action
        clear_action = QAction(QIcon.fromTheme("edit-clear"), "Clear Log", self)
        _ = clear_action.triggered.connect(self._clear_main_log)
        toolbar.addAction(clear_action)

    def _create_left_panel(self) -> QWidget:
        """Create the left panel with file list and settings"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        # File list section
        file_group = QGroupBox("📁 Files to Convert")
        file_layout = QVBoxLayout(file_group)

        # File list widget
        self.file_list = FileListWidget()
        file_layout.addWidget(self.file_list)

        # File list buttons
        file_button_layout = QHBoxLayout()

        add_btn = QPushButton("Add Files")
        _ = add_btn.clicked.connect(self.add_files)
        file_button_layout.addWidget(add_btn)

        remove_btn = QPushButton("Remove Selected")
        _ = remove_btn.clicked.connect(self.remove_selected)
        file_button_layout.addWidget(remove_btn)

        clear_btn = QPushButton("Clear All")
        _ = clear_btn.clicked.connect(self.clear_list)
        file_button_layout.addWidget(clear_btn)

        file_layout.addLayout(file_button_layout)

        # Batch operation buttons with enhanced styling
        batch_button_layout = QHBoxLayout()

        select_all_btn = QPushButton("📋 Select All")
        select_all_btn.setToolTip("Select all files in the list (Ctrl+A)")
        _ = select_all_btn.clicked.connect(self.select_all_files)
        batch_button_layout.addWidget(select_all_btn)

        clear_completed_btn = QPushButton("✅ Clear Completed")
        clear_completed_btn.setToolTip("Remove all completed files (Ctrl+Shift+C)")
        clear_completed_btn.setStyleSheet("""
            QPushButton {
                color: #2e7d32;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e8f5e8;
            }
        """)
        _ = clear_completed_btn.clicked.connect(self.clear_completed_files)
        batch_button_layout.addWidget(clear_completed_btn)

        remove_failed_btn = QPushButton("❌ Remove Failed")
        remove_failed_btn.setToolTip("Remove all failed files (Ctrl+Shift+F)")
        remove_failed_btn.setStyleSheet("""
            QPushButton {
                color: #d32f2f;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ffebee;
            }
        """)
        _ = remove_failed_btn.clicked.connect(self.remove_failed_files)
        batch_button_layout.addWidget(remove_failed_btn)

        file_layout.addLayout(batch_button_layout)
        layout.addWidget(file_group)

        # Settings panel
        settings_widget = self.settings_panel.create_settings_widget()
        layout.addWidget(settings_widget)

        return panel

    def _create_right_panel(self) -> QWidget:
        """Create the right panel with process monitoring and logs"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        # Tab widget for different views
        tabs = QTabWidget()

        # Process monitoring tab
        process_scroll = QScrollArea()
        process_scroll.setWidgetResizable(True)
        process_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        # Initialize process monitor
        self.process_monitor = ProcessMonitor(
            self.process_manager, process_scroll, self
        )

        tabs.addTab(process_scroll, "🔄 Active Processes")

        # Main log tab
        self.main_log = QPlainTextEdit()
        self.main_log.setReadOnly(True)
        self.main_log.setMaximumBlockCount(LogConfig.MAIN_LOG_TRUNCATE_LINES * 10)
        tabs.addTab(self.main_log, "📋 Conversion Log")

        layout.addWidget(tabs)

        return panel

    def _create_button_layout(self) -> QHBoxLayout:
        """Create the control button layout"""
        layout = QHBoxLayout()

        layout.addStretch()

        self.start_btn = QPushButton("🚀 Start Conversion")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """)
        _ = self.start_btn.clicked.connect(self._start_conversion)
        layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("🛑 Stop Conversion")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """)
        _ = self.stop_btn.clicked.connect(self._stop_conversion)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn)

        layout.addStretch()

        return layout

    def _connect_signals(self):
        """Connect signals between components"""
        # Conversion controller signals
        _ = self.conversion_controller.conversion_started.connect(
            self._on_conversion_started
        )
        _ = self.conversion_controller.conversion_finished.connect(
            self._on_conversion_finished
        )
        _ = self.conversion_controller.conversion_stopped.connect(
            self._on_conversion_stopped
        )
        _ = self.conversion_controller.log_message.connect(self._add_to_main_log)
        _ = self.conversion_controller.progress_updated.connect(
            self._update_overall_progress
        )

        # Settings panel signals
        _ = self.settings_panel.auto_balance_toggled.connect(
            self.conversion_controller.enable_auto_balance
        )
        _ = self.settings_panel.settings_changed.connect(self._on_settings_changed)

        # Process manager signals for logging
        _ = self.process_manager.output_ready.connect(self._log_process_output)

        # Process monitor signals
        if self.process_monitor:
            _ = self.process_monitor.progress_updated.connect(self._update_overall_progress)

    def add_files(self):
        """Add files to the conversion list"""
        if self.file_list is None:
            raise RuntimeError("File list widget not initialized")

        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Video Files",
            str(self.last_dir),
            "Video Files (*.ts *.mp4 *.m4v *.mov *.avi *.mkv);;All Files (*)",
        )

        if file_paths:
            self.file_list.add_files(file_paths)
            self.last_dir = str(Path(file_paths[0]).parent)
            self.settings.setValue("lastDir", self.last_dir)
            self._add_to_main_log(f"📁 Added {len(file_paths)} files")

            # Update status bar with estimated sizes
            self._update_status_with_estimates()

    def remove_selected(self):
        """Remove selected files from the list"""
        if self.file_list is None:
            raise RuntimeError("File list widget not initialized")

        removed_count = self.file_list.remove_selected()
        if removed_count > 0:
            self._add_to_main_log(f"🗑️ Removed {removed_count} files")
            self._update_status_with_estimates()

    def clear_list(self):
        """Clear all files from the list"""
        if self.file_list is None:
            raise RuntimeError("File list widget not initialized")

        count = self.file_list.get_file_count()
        self.file_list.clear()
        if count > 0:
            self._add_to_main_log(f"🗑️ Cleared {count} files")
            self._update_status_with_estimates()

    def select_all_files(self):
        """Select all files in the list"""
        if self.file_list is None:
            raise RuntimeError("File list widget not initialized")

        self.file_list.select_all_files()

    def clear_completed_files(self):
        """Clear all completed files from the list"""
        if self.file_list is None:
            raise RuntimeError("File list widget not initialized")

        removed_count = self.file_list.clear_completed_files()
        if removed_count > 0:
            self._add_to_main_log(f"✅ Cleared {removed_count} completed files")
            self._update_status_with_estimates()

    def remove_failed_files(self):
        """Remove all failed files from the list"""
        if self.file_list is None:
            raise RuntimeError("File list widget not initialized")

        removed_count = self.file_list.remove_failed_files()
        if removed_count > 0:
            self._add_to_main_log(f"❌ Removed {removed_count} failed files")
            self._update_status_with_estimates()

    def _start_conversion(self):
        """Start the conversion process"""
        if self.is_converting:
            return

        if self.file_list is None:
            raise RuntimeError("File list widget not initialized")

        file_paths = self.file_list.get_file_paths_in_order()
        if not file_paths:
            QMessageBox.warning(self, "No Files", "Please add files to convert first.")
            return

        # Get settings from settings panel
        settings = self.settings_panel.get_current_settings()

        # Validate settings
        is_valid, error_msg = self.settings_panel.validate_settings()
        if not is_valid:
            QMessageBox.warning(self, "Invalid Settings", error_msg)
            return

        # Start conversion
        success = self.conversion_controller.start_conversion(
            file_paths=file_paths,
            codec_idx=settings["codec_idx"],
            hwdecode_idx=settings["hwdecode_idx"],
            crf_value=settings["crf_value"],
            parallel_enabled=settings["parallel_enabled"],
            max_parallel=settings["max_parallel"],
            delete_source=settings["delete_source"],
            overwrite_mode=True,  # Always overwrite for now
        )

        if success:
            self.is_converting = True

    def _stop_conversion(self):
        """Stop the conversion process"""
        if not self.is_converting:
            return

        self.conversion_controller.stop_conversion()

    def _on_conversion_started(self):
        """Handle conversion started signal"""
        if (
            self.start_btn is None
            or self.stop_btn is None
            or self.overall_progress_bar is None
            or self.status_bar is None
        ):
            raise RuntimeError("UI components not properly initialized")

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.overall_progress_bar.setVisible(True)
        self.overall_progress_bar.setValue(0)
        self.status_bar.showMessage("Converting...")

    def _on_conversion_finished(self):
        """Handle conversion finished signal"""
        if (
            self.start_btn is None
            or self.stop_btn is None
            or self.overall_progress_bar is None
            or self.status_bar is None
        ):
            raise RuntimeError("UI components not properly initialized")

        self.is_converting = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.overall_progress_bar.setVisible(False)
        self.status_bar.showMessage("Conversion completed")

        # Refresh drag-and-drop functionality after conversion completion
        if self.file_list:
            self.file_list.refresh_drag_drop_state()

    def _on_conversion_stopped(self):
        """Handle conversion stopped signal"""
        if (
            self.start_btn is None
            or self.stop_btn is None
            or self.overall_progress_bar is None
            or self.status_bar is None
        ):
            raise RuntimeError("UI components not properly initialized")

        self.is_converting = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.overall_progress_bar.setVisible(False)
        self.status_bar.showMessage("Conversion stopped")

        # Refresh drag-and-drop functionality after conversion stopped
        if self.file_list:
            self.file_list.refresh_drag_drop_state()

    def _update_overall_progress(self, progress_data=None):
        """Mark progress components as dirty for efficient batch updates"""
        if progress_data:
            # Mark components as dirty with their data
            self.ui_update_manager.mark_dirty("progress_bar", progress_data)
            self.ui_update_manager.mark_dirty("status_label", progress_data)

        # Update individual file progress in the file list
        self._update_file_list_progress()

    def _update_file_list_progress(self):
        """Update file list widget with current progress for active processes"""
        if not self.file_list or not self.process_manager:
            return

        # Get all active processes and their paths
        for process, path in self.process_manager.processes:
            # Get progress data for this specific process
            process_progress = self.process_manager.get_process_progress(process)
            if process_progress:
                # Extract progress percentage
                progress_pct = process_progress.get("current_pct", 0)

                # Only update status and progress for pending/processing files
                # Don't overwrite completed/failed status
                current_status = self.file_list.get_item_status(path)
                if progress_pct > 0 and current_status in ["pending", "processing"]:
                    if current_status == "pending":
                        self.file_list.set_status(path, "processing")
                    self.file_list.update_progress(path, progress_pct)

    def _handle_ui_updates(self, updates: dict):
        """Handle batched UI updates from the update manager"""
        # Update progress bar
        if "progress_bar" in updates and self.overall_progress_bar:
            progress_data = updates["progress_bar"]
            if "weighted_pct" in progress_data:
                pct = min(100, max(0, round(progress_data["weighted_pct"])))
                self.overall_progress_bar.setValue(pct)

        # Update status bar
        if "status_label" in updates and self.status_bar:
            progress_data = updates["status_label"]
            if progress_data.get("eta_str"):
                active_count = progress_data.get("active_count", 0)
                completed_count = progress_data.get("completed_count", 0)
                total_count = progress_data.get("total_count", 0)

                status_msg = f"Converting: {completed_count}/{total_count} completed, {active_count} active"
                if progress_data["eta_str"] != "00:00:00":
                    status_msg += f" • ETA: {progress_data['eta_str']}"

                self.status_bar.showMessage(status_msg)

    def _on_settings_changed(self, settings: dict):
        """Handle settings changes and update file size estimates"""
        if self.file_list is None or self.status_bar is None:
            return

        # Update file list with new estimates
        codec_idx = settings.get("codec_idx", 0)
        crf_value = settings.get("crf_value", 16)

        # Update all file displays with new estimates
        self.file_list.update_all_display_with_settings(codec_idx, crf_value)

        # Update status bar with total estimated size if not converting
        if not self.is_converting:
            total_estimated = self.file_list.get_total_estimated_size(
                codec_idx, crf_value
            )
            file_count = self.file_list.get_file_count()
            if file_count > 0:
                self.status_bar.showMessage(
                    f"Ready • {file_count} files • Est. total: {total_estimated}"
                )
            else:
                self.status_bar.showMessage("Ready")

    def _update_status_with_estimates(self):
        """Update status bar with current file estimates"""
        if self.file_list is None or self.status_bar is None or self.is_converting:
            return

        settings = self.settings_panel.get_current_settings()
        codec_idx = settings.get("codec_idx", 0)
        crf_value = settings.get("crf_value", 16)

        total_estimated = self.file_list.get_total_estimated_size(codec_idx, crf_value)
        file_count = self.file_list.get_file_count()

        if file_count > 0:
            self.status_bar.showMessage(
                f"Ready • {file_count} files • Est. total: {total_estimated}"
            )
        else:
            self.status_bar.showMessage("Ready")

    def _add_to_main_log(self, message: str):
        """Add message to main log"""
        if self.main_log is None:
            raise RuntimeError("Main log widget not initialized")

        self.main_log.appendPlainText(message)

        # Limit log size
        if self.main_log.blockCount() > LogConfig.MAIN_LOG_TRUNCATE_LINES:
            cursor = self.main_log.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(
                cursor.MoveOperation.Down,
                cursor.MoveMode.KeepAnchor,
                self.main_log.blockCount() - LogConfig.MAIN_LOG_TRUNCATE_LINES,
            )
            cursor.removeSelectedText()

    def _log_process_output(self, process, chunk: str):
        """Log process output (can be filtered/processed as needed)"""
        # For now, we don't log raw FFmpeg output to main log to keep it clean
        # The process monitor handles individual process progress

    def _clear_main_log(self):
        """Clear the main log"""
        if self.main_log is None:
            raise RuntimeError("Main log widget not initialized")

        self.main_log.clear()
        self._add_to_main_log("📋 Log cleared")

    def _show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About PyFFMPEG",
            f"{AppConfig.APP_NAME} v{AppConfig.APP_VERSION}\n"
            f"{AppConfig.APP_DESCRIPTION}\n\n"
            "A high-performance video converter with RTX acceleration support.",
        )

    def _restore_state(self):
        """Restore window state"""
        # Restore window geometry if available
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

        # Restore window state
        window_state = self.settings.value("windowState")
        if window_state:
            self.restoreState(window_state)

    def closeEvent(self, event):
        """Handle window close event"""
        # Stop any active conversions
        if self.is_converting:
            reply = QMessageBox.question(
                self,
                "Conversion Active",
                "Conversion is in progress. Stop and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

            self.conversion_controller.stop_conversion()

        # Save window state
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())

        # Clean up resources
        self.ui_update_manager.stop()
        self.process_manager.cleanup_all_resources()
        if self.process_monitor:
            self.process_monitor.cleanup_all_widgets()

        event.accept()


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName(AppConfig.APP_NAME)
    app.setApplicationVersion(AppConfig.APP_VERSION)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
