#!/usr/bin/env python3
"""
Video Converter GUI (Sequential Processing)
A PySide6 application to batch-convert video files (TS, MP4, MOV, etc.) to MP4 (H.264/HEVC/AV1) or Apple ProRes MOV using FFmpeg.
Now with optional hardware‐accelerated decode + encode for NVENC, QSV, and VAAPI.
Includes options to delete source after success, and per-file progress in the list.
"""

import os
import sys
import shutil
import time
from PySide6.QtCore import Qt

# Import custom modules
from file_list_widget import FileListWidget  # Import the enhanced FileListWidget
from process_manager import ProcessManager
from codec_helpers import CodecHelpers  # Import the codec helpers
from config import ProcessConfig, UIConfig, LogConfig, EncodingConfig, HardwareConfig, AppConfig

from PySide6.QtCore import QProcess, QFileInfo, QSettings, QByteArray, QTimer
from PySide6.QtGui import QAction, QIcon, QColor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QLabel,
    QComboBox,
    QSpinBox,
    QProgressBar,
    QPlainTextEdit,
    QMessageBox,
    QSplitter,
    QGroupBox,
    QToolBar,
    QStatusBar,
    QCheckBox,
    QTabWidget,
    QScrollArea,
    QFrame,
)


class MainWindow(QMainWindow):
    """Main application window with sequential processing, delete toggle, hardware‐decode toggle, and per-file progress."""

    # Regex patterns moved to the progress_tracker module

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{AppConfig.APP_NAME} - RTX Optimized")
        self.resize(AppConfig.DEFAULT_WINDOW_WIDTH, AppConfig.DEFAULT_WINDOW_HEIGHT)

        self.settings = QSettings(AppConfig.SETTINGS_ORG, AppConfig.SETTINGS_APP)
        self._check_ffmpeg()

        # QoL state
        self.last_dir = self.settings.value("lastDir", os.getcwd())

        # Initialize process manager
        self.process_manager = ProcessManager(self)

        # Connect process manager signals
        self.process_manager.output_ready.connect(self._log_output)
        self.process_manager.update_progress.connect(self._update_ui)
        self.current_path: str | None = None
        self.parallel_enabled = False

        # The progress tracker is now fully integrated with the ProcessManager

        # Track UI elements for process monitoring
        self.process_widgets = {}
        self.process_logs = {}

        # Performance optimizations
        self.ui_update_timer = QTimer()
        self.ui_update_timer.setInterval(UIConfig.UI_UPDATE_FALLBACK)  # Fallback timer for UI updates
        self.ui_update_timer.timeout.connect(self._update_ui)
        self.ui_update_timer.setSingleShot(False)
        self.pending_process_outputs = {}

        # Track file exists errors
        self.overwrite_mode = True  # Default to overwrite files
        self.batch_start_time: float | None = None
        self.total = 0
        self.completed = 0

        # Auto-balance tracking
        self.auto_balance_enabled = False
        self.file_codec_assignments = {}  # Maps file paths to codec indices

        self._init_ui()
        self._restore_state()

    def _check_ffmpeg(self):
        if not shutil.which("ffmpeg"):
            QMessageBox.critical(
                None,
                "FFmpeg Not Found",
                "FFmpeg executable not found in PATH. Please install or add to PATH.",
            )
            sys.exit(1)

    def _init_ui(self):
        # Detect system capabilities
        self.is_high_end_system = os.cpu_count() >= HardwareConfig.HIGH_END_CPU_CORES
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        add_files_action = QAction(QIcon.fromTheme("document-open"), "Add Files", self)
        add_files_action.setShortcut("Ctrl+O")
        add_files_action.triggered.connect(self.add_files)
        exit_action = QAction(QIcon.fromTheme("application-exit"), "E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(add_files_action)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        tools_menu = menubar.addMenu("&Tools")
        clear_log_action = QAction(QIcon.fromTheme("edit-clear"), "Clear Log", self)
        clear_log_action.setShortcut("Ctrl+L")
        clear_log_action.triggered.connect(lambda: self.log.clear())
        tools_menu.addAction(clear_log_action)

        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        toolbar.addAction(add_files_action)
        toolbar.addAction(clear_log_action)
        toolbar.addAction(exit_action)
        self.addToolBar(toolbar)

        central = QWidget()
        main_layout = QVBoxLayout(central)

        # File list with per-file progress
        self.file_list = FileListWidget()
        self.file_list.setStyleSheet("QListView::item:hover{background:#363b46;}")

        settings_group = QGroupBox("Conversion Settings")
        settings_layout = QHBoxLayout()

        # Codec selector
        self.format_cb = QComboBox()
        self.format_cb.addItems(
            [
                "H.264 NVENC",  # 0
                "HEVC NVENC",  # 1
                "AV1 NVENC",  # 2
                "x264 CPU",  # 3
                "ProRes CPU",  # 4
                "H.264 QSV",  # 5
                "H.264 VAAPI",  # 6
            ]
        )
        # Set H.264 NVENC as default for RTX GPU
        self.format_cb.setCurrentIndex(0)

        # Add performance preset selector
        preset_label = QLabel("Preset:")
        settings_layout.addWidget(preset_label)
        self.preset_cb = QComboBox()
        self.preset_cb.addItems(["Standard", "High Quality", "Fast", "Ultra Fast"])
        self.preset_cb.setCurrentIndex(2)  # Default to Fast for high-end system
        self.preset_cb.setToolTip(
            "Performance preset affects encoding speed vs. quality"
        )
        settings_layout.addWidget(self.preset_cb)

        crf_label = QLabel("CRF:")
        self.crf_sb = QSpinBox()
        self.crf_sb.setRange(0, 51)
        self.crf_sb.setValue(int(self.settings.value("crf", EncodingConfig.DEFAULT_CRF_H264)))
        self.crf_sb.setAccelerated(True)

        # Threads selector
        thread_label = QLabel("Threads:")
        self.threads_sb = QSpinBox()
        max_threads = os.cpu_count() or 4
        self.threads_sb.setRange(1, max_threads)
        # For high-end CPUs, using all threads may not be optimal for all workloads
        # Use optimal threads for CPU encoding on high-end systems
        optimal_threads = min(ProcessConfig.OPTIMAL_CPU_THREADS, max_threads)
        self.threads_sb.setValue(optimal_threads)
        self.threads_sb.setAccelerated(True)

        # Parallel processing option
        self.parallel_cb = QCheckBox("Parallel Processing")
        self.parallel_cb.setToolTip("Enable parallel conversion of multiple files")
        # Enable parallel processing by default for high-end systems
        self.parallel_cb.setChecked(True)

        # Max parallel processes selector
        parallel_label = QLabel("Max Parallel:")
        self.parallel_sb = QSpinBox()
        # Set parallel limit based on system capabilities
        self.parallel_sb.setRange(1, ProcessConfig.MAX_PARALLEL_HIGH_END)
        self.parallel_sb.setValue(4)  # Good balance: 2 sessions per NVENC engine
        self.parallel_sb.setAccelerated(True)
        self.parallel_sb.setToolTip("Maximum number of parallel conversions")

        # Delete source toggle
        self.delete_cb = QCheckBox("Delete source file after successful conversion")
        delete_default = self.settings.value("delete", False, type=bool)
        self.delete_cb.setChecked(delete_default)
        self.delete_cb.stateChanged.connect(
            lambda state: self.settings.setValue("delete", bool(state))
        )

        # Hardware decode toggle
        self.hwdecode_cb = QComboBox()
        self.hwdecode_cb.addItems(["Auto", "NVIDIA", "Intel QSV", "VAAPI"])
        hwdecode_index = int(self.settings.value("hwdecode", 0))
        self.hwdecode_cb.setCurrentIndex(hwdecode_index)
        self.hwdecode_cb.currentIndexChanged.connect(
            lambda idx: self.settings.setValue("hwdecode", idx)
        )

        # Overwrite existing files toggle
        self.overwrite_cb = QCheckBox("Overwrite existing files")
        overwrite_def = self.settings.value("overwrite", True, type=bool)
        self.overwrite_cb.setChecked(overwrite_def)
        self.overwrite_cb.stateChanged.connect(
            lambda s: self.settings.setValue("overwrite", bool(s))
        )

        # Add a smart buffer toggle for performance
        self.smart_buffer_cb = QCheckBox("Smart Buffer Mode")
        self.smart_buffer_cb.setChecked(True)
        self.smart_buffer_cb.setToolTip(
            "Optimize memory usage and CPU overhead during conversion"
        )

        # Add auto-balance toggle for hybrid encoding
        self.auto_balance_cb = QCheckBox("Auto-Balance (CPU+GPU)")
        self.auto_balance_cb.setChecked(True)
        self.auto_balance_cb.setToolTip(
            "Automatically distribute files between GPU and CPU encoders for maximum throughput"
        )

        # Show/hide CRF based on codec
        self.format_cb.currentIndexChanged.connect(
            lambda idx: crf_label.setVisible(idx == 0)
            or self.crf_sb.setVisible(idx == 0)
        )
        crf_label.setVisible(self.format_cb.currentIndex() == 0)
        self.crf_sb.setVisible(self.format_cb.currentIndex() == 0)

        # Lay out settings widgets
        for w in (
            QLabel("Codec:"),
            self.format_cb,
            preset_label,
            self.preset_cb,
            crf_label,
            self.crf_sb,
            thread_label,
            self.threads_sb,
            self.parallel_cb,
            parallel_label,
            self.parallel_sb,
            self.delete_cb,
            self.hwdecode_cb,
            self.overwrite_cb,
            self.smart_buffer_cb,
            self.auto_balance_cb,
        ):
            settings_layout.addWidget(w)
        settings_group.setLayout(settings_layout)

        # Control buttons
        controls_layout = QHBoxLayout()
        add_btn = QPushButton("Add Files")
        add_btn.clicked.connect(self.add_files)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self.remove_selected)
        clear_list_btn = QPushButton("Clear List")
        clear_list_btn.clicked.connect(self.clear_list)
        # Create a more prominent start button with icon and styling
        start_btn = QPushButton("  Start")
        # Use a larger font with bold text
        start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; /* Green */
                color: white;
                font-weight: bold;
                font-size: 14px;
                padding: 8px 16px;
                border-radius: 5px;
                min-width: 120px;
                min-height: 36px;
            }
            QPushButton:hover {
                background-color: #45a049;
                border: 2px solid #357a38;
            }
            QPushButton:pressed {
                background-color: #357a38;
            }
        """)
        # Add a play icon
        start_icon = QIcon.fromTheme("media-playback-start")
        # If system theme icon is not available, we'll use a text-based icon
        if start_icon.isNull():
            start_btn.setText("▶️  Start")
        stop_btn = QPushButton("Stop")
        stop_btn.setEnabled(False)
        start_btn.clicked.connect(lambda: self.start_conversion(start_btn, stop_btn))
        stop_btn.clicked.connect(lambda: self.stop_conversion(start_btn, stop_btn))
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(lambda: self.log.clear())

        # Add start button first on the left side
        controls_layout.addWidget(start_btn)
        # Add a small spacing between start button and other controls
        controls_layout.addSpacing(10)

        # Then add the file management buttons
        for btn in (add_btn, remove_btn, clear_list_btn):
            controls_layout.addWidget(btn)

        controls_layout.addStretch()

        # Other utility buttons on the right
        for btn in (stop_btn, clear_log_btn):
            controls_layout.addWidget(btn)

        # Splitter for list + progress/log
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.addWidget(self.file_list)

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)

        # Overall progress section
        progress_group = QGroupBox("Overall Progress")
        progress_layout = QVBoxLayout(progress_group)
        self.total_progress = QProgressBar()
        self.total_progress.setFormat("Total: %p%")
        progress_layout.addWidget(self.total_progress)
        bottom_layout.addWidget(progress_group)

        # Individual processes section
        self.processes_tab = QTabWidget()
        self.processes_tab.setTabsClosable(False)

        # Main log tab
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.processes_tab.addTab(self.log, "Main Log")

        # Create progress monitoring area
        self.progress_area = QScrollArea()
        self.progress_area.setWidgetResizable(True)
        self.process_containers = QWidget()
        self.process_containers.setLayout(QVBoxLayout())
        self.process_containers.layout().setAlignment(Qt.AlignTop)
        self.process_containers.layout().setSpacing(10)
        self.process_containers.layout().setContentsMargins(10, 10, 10, 10)
        self.progress_area.setWidget(self.process_containers)
        self.progress_area.setStyleSheet("QProgressBar { text-align: center; }")
        self.processes_tab.addTab(self.progress_area, "Individual Processes")

        bottom_layout.addWidget(self.processes_tab)

        # Add to splitter
        self.splitter.addWidget(bottom_widget)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)

        main_layout.addWidget(settings_group)
        main_layout.addLayout(controls_layout)
        main_layout.addWidget(self.splitter)
        self.setCentralWidget(central)

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self.current_file_label = QLabel()
        self.eta_label = QLabel()
        status_bar.addWidget(self.current_file_label)
        status_bar.addPermanentWidget(self.eta_label)

    def _restore_state(self):
        geom = self.settings.value("geometry")
        splitter_state = self.settings.value("splitterState")
        if isinstance(geom, QByteArray):
            self.restoreGeometry(geom)
        if isinstance(splitter_state, QByteArray):
            self.splitter.restoreState(splitter_state)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select video files",
            self.last_dir,
            "Video Files (*.ts *.mp4 *.m4v *.mov);;TS Files (*.ts);;MP4 Files (*.mp4 *.m4v);;MOV Files (*.mov);;All Files (*)",
        )
        if files:
            self.last_dir = os.path.dirname(files[0])
            self.settings.setValue("lastDir", self.last_dir)
        for f in files:
            self.file_list.add_path(f)

    def remove_selected(self):
        from PySide6.QtCore import Qt

        for item in list(self.file_list.selectedItems()):
            path = item.data(int(Qt.UserRole))
            self.file_list.takeItem(self.file_list.row(item))
            self.file_list.path_items.pop(path, None)

    def clear_list(self):
        self.file_list.clear()
        self.file_list.path_items.clear()

    def _create_process_widget(self, process, path):
        """Create UI elements for monitoring an individual process"""
        container = QFrame()
        container.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        container.setLineWidth(1)
        container.setStyleSheet(
            "QFrame { background-color: #f5f5f5; border-radius: 5px; }"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Create header layout for file name and status
        header_layout = QHBoxLayout()

        # Add file name with icon
        name = QFileInfo(path).fileName()
        label = QLabel(f"<b>{name}</b>")
        label.setTextFormat(Qt.RichText)
        label.setStyleSheet("font-size: 11pt;")
        header_layout.addWidget(label, 1)  # Stretch to take available space

        # Add status indicator (will be updated later)
        status_label = QLabel("<b>⏳ Processing</b>")
        status_label.setStyleSheet("color: #0066cc; font-size: 10pt;")
        status_label.setTextFormat(Qt.RichText)
        header_layout.addWidget(status_label)

        layout.addLayout(header_layout)

        # Info layout for codec and settings
        info_layout = QHBoxLayout()

        # Add codec type indicator with icon
        if self.auto_balance_enabled and path in self.file_codec_assignments:
            codec_idx = self.file_codec_assignments[path]
        else:
            codec_idx = self.format_cb.currentIndex()

        codec_info = {
            0: {"name": "H.264 (CPU)", "color": "#555555", "icon": "🖥️"},
            1: {"name": "H.264 (NVENC)", "color": "#00aa00", "icon": "🔥"},
            2: {"name": "HEVC (NVENC)", "color": "#00aa00", "icon": "🔥"},
            3: {"name": "AV1 (NVENC)", "color": "#00aa00", "icon": "🔥"},
            4: {"name": "ProRes 422", "color": "#9900cc", "icon": "🎬"},
            5: {"name": "ProRes 4444", "color": "#9900cc", "icon": "🎬"},
        }

        codec_data = codec_info.get(
            codec_idx, {"name": "Unknown", "color": "#555555", "icon": "❓"}
        )
        codec_label = QLabel(f"{codec_data['icon']} {codec_data['name']}")
        codec_label.setStyleSheet(f"color: {codec_data['color']};")
        info_layout.addWidget(codec_label)

        # Add hardware acceleration indicator if used
        hw_accel = ""
        if self.hwdecode_cb.currentIndex() > 0:
            hw_accel_types = {1: "🚀 NVIDIA", 2: "💻 Intel QSV", 3: "🐧 VAAPI"}
            hw_accel = hw_accel_types.get(self.hwdecode_cb.currentIndex(), "")

        if hw_accel:
            hw_label = QLabel(hw_accel)
            hw_label.setStyleSheet("color: #0066cc;")
            info_layout.addWidget(hw_label)

        # Add spacer to push items to left
        info_layout.addStretch(1)

        # If delete after conversion is enabled, show indicator
        if self.delete_cb.isChecked():
            delete_label = QLabel("🗑️ Delete original")
            delete_label.setStyleSheet("color: #cc0000;")
            info_layout.addWidget(delete_label)

        layout.addLayout(info_layout)

        # Add progress bar with custom style
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(True)
        progress.setFormat("%p% complete")
        progress.setStyleSheet(
            "QProgressBar {border: 1px solid #cccccc; border-radius: 3px; text-align: center;}"
            "QProgressBar::chunk {background-color: #4CAF50; width: 1px;}"
        )
        layout.addWidget(progress)

        # Add stats layout for more detailed information
        stats_layout = QHBoxLayout()

        # ETA label
        eta_label = QLabel("⏱️ ETA: Calculating...")
        stats_layout.addWidget(eta_label)

        # FPS counter
        fps_label = QLabel("📊 FPS: -")
        stats_layout.addWidget(fps_label)

        # Add spacer to push items to left
        stats_layout.addStretch(1)

        # File size estimate (to be updated)
        size_label = QLabel("💾 Size: Calculating...")
        stats_layout.addWidget(size_label)

        layout.addLayout(stats_layout)

        # Add condensed log output with custom style
        log = QPlainTextEdit()
        log.setReadOnly(True)
        log.setMaximumHeight(100)
        log.setMaximumBlockCount(5)  # Keep log size reasonable
        log.setStyleSheet(
            "QPlainTextEdit {background-color: #f0f0f0; border: 1px solid #dddddd; font-family: monospace; font-size: 9pt;}"
        )
        layout.addWidget(log)

        # Add to the process area
        self.process_containers.layout().addWidget(container)

        # Store references to widgets with additional elements
        self.process_widgets[process] = {
            "container": container,
            "label": label,
            "status_label": status_label,
            "codec_label": codec_label,
            "progress": progress,
            "eta_label": eta_label,
            "fps_label": fps_label,
            "size_label": size_label,
            "log": log,
            "path": path,
            "start_time": time.time(),
        }

        # Also create/store a reference to a dedicated log in the tab widget
        process_log = QPlainTextEdit()
        process_log.setReadOnly(True)
        process_log.setMaximumBlockCount(1000)  # Limit memory usage
        process_log.setStyleSheet("font-family: monospace; font-size: 9pt;")
        name = QFileInfo(path).fileName()
        tab_idx = self.processes_tab.addTab(process_log, name)
        self.process_logs[process] = {"log": process_log, "tab_idx": tab_idx}

    def _format_time(self, seconds: float) -> str:
        """Format seconds into a human-readable time string (HH:MM:SS)"""
        if seconds < 0:
            return "--:--:--"

        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

    def _remove_process_widget(self, process):
        """Remove UI elements for a completed process with guaranteed cleanup"""
        # Guaranteed widget cleanup
        if process in self.process_widgets:
            try:
                widgets = self.process_widgets[process]
                
                # Safely remove from layout
                container = widgets.get("container")
                if container and self.process_containers.layout():
                    self.process_containers.layout().removeWidget(container)
                    container.deleteLater()
                
                # Clear all widget references to prevent memory leaks
                for key, widget in widgets.items():
                    if hasattr(widget, 'deleteLater') and key != "container":
                        widget.deleteLater()
                
                # Remove from tracking
                del self.process_widgets[process]
                
            except (KeyError, RuntimeError) as e:
                print(f"Warning: Error during widget cleanup: {e}")

        # Guaranteed tab cleanup
        if process in self.process_logs:
            try:
                log_info = self.process_logs[process]
                tab_idx = log_info.get("tab_idx", -1)
                
                # Safely remove tab if it exists
                if 0 <= tab_idx < self.processes_tab.count():
                    self.processes_tab.removeTab(tab_idx)
                
                # Clean up log widget
                log_widget = log_info.get("log")
                if log_widget:
                    log_widget.deleteLater()
                
                del self.process_logs[process]
                
            except (KeyError, RuntimeError) as e:
                print(f"Warning: Error during log cleanup: {e}")
                
    def _cleanup_all_widgets(self):
        """Emergency cleanup of all process widgets and logs"""
        # Clean up all process widgets
        for process in list(self.process_widgets.keys()):
            self._remove_process_widget(process)
        
        # Clear any remaining references
        self.process_widgets.clear()
        self.process_logs.clear()
        
        # Stop UI update timer
        if hasattr(self, 'ui_update_timer') and self.ui_update_timer.isActive():
            self.ui_update_timer.stop()

    def _auto_balance_workload(self):
        from PySide6.QtCore import Qt

        """Distribute encoding tasks between GPU and CPU for optimal performance"""
        # Reset assignments
        self.file_codec_assignments = {}

        # Get available files
        files = [
            item.data(int(Qt.UserRole))
            for item in self.file_list.findItems("*", Qt.MatchWildcard)
        ]
        if not files:
            return

        # If queue is empty, use all files
        if not self.process_manager.queue:
            # Initialize queue with all files in list
            paths = [
                item.data(Qt.UserRole)
                for item in self.file_list.findItems("*", Qt.MatchWildcard)
            ]
            self.process_manager.queue = paths.copy()

        # System info
        gpu_slots = min(
            ProcessConfig.MAX_GPU_SLOTS, len(files)
        )  # RTX 4090 can handle up to 6 encodes (3 per NVENC block)

        # Determine optimal distribution based on configured ratios
        gpu_count = min(int(len(files) * EncodingConfig.GPU_RATIO_DEFAULT), gpu_slots)

        # Initialize distribution counters
        assigns = {
            0: 0,
            1: 0,
            2: 0,
            3: 0,
        }  # H.264 NVENC, HEVC NVENC, AV1 NVENC, x264 CPU

        # Allocate optimal codec based on system analysis
        has_rtx40 = CodecHelpers.detect_rtx40_series()

        # Determine HEVC vs AV1 slots based on GPU capabilities
        h264_nvenc_count = min(2, gpu_count)  # Start with some H.264 slots
        hevc_nvenc_count = gpu_count - h264_nvenc_count  # Most slots for HEVC
        av1_nvenc_count = 0

        # If system has RTX 40-series, allocate some AV1 slots
        if has_rtx40:
            av1_nvenc_count = min(1, hevc_nvenc_count)  # Take 1 slot from HEVC for AV1
            hevc_nvenc_count -= av1_nvenc_count

        # Assign each file a codec for the upcoming batch
        for file_path in files:
            try:
                # Try to intelligently select codec based on position in the queue
                if assigns[0] < h264_nvenc_count:  # Fill H.264 slots first (fastest)
                    codec = 0  # H.264 NVENC
                    assigns[0] += 1
                elif assigns[1] < hevc_nvenc_count:  # Then HEVC slots
                    codec = 1  # HEVC NVENC
                    assigns[1] += 1
                elif assigns[2] < av1_nvenc_count:  # Fill AV1 slots if enabled
                    codec = 2  # AV1 NVENC
                    assigns[2] += 1
                else:  # Remaining files to CPU
                    codec = 3  # x264 CPU
                    assigns[3] += 1

                self.file_codec_assignments[file_path] = codec
            except (KeyError, ValueError, IndexError):
                # Default to H.264 NVENC if analysis fails
                self.file_codec_assignments[file_path] = 0

    def start_conversion(self, start_btn, stop_btn):
        from PySide6.QtCore import Qt

        """Start the conversion process for all files in the list"""
        if not self.file_list.path_items:
            QMessageBox.warning(self, "No Files", "Please add some video files first!")
            return

        # Disable UI controls during conversion
        start_btn.setEnabled(False)
        stop_btn.setEnabled(True)
        self.log.clear()

        # Get list of ts files to convert
        file_paths = []
        for idx in range(self.file_list.count()):
            item = self.file_list.item(idx)
            file_paths.append(item.data(int(Qt.UserRole)))

        # Get settings from UI
        self.delete_after = self.delete_cb.isChecked()
        self.hardware_decode = self.hwdecode_cb.currentIndex()
        self.parallel_enabled = self.parallel_cb.isChecked()
        self.max_parallel = self.parallel_sb.value()
        self.auto_balance_enabled = (
            self.auto_balance_cb.isChecked() and self.parallel_enabled
        )
        self.overwrite_mode = self.overwrite_cb.isChecked()

        # If auto-balance is enabled, distribute work between GPU and CPU
        if self.auto_balance_enabled:
            self._auto_balance_workload()

        # Reset UI state
        self.total_progress.setValue(0)
        self.current_file_label.clear()
        self.eta_label.clear()
        self.batch_start_time = time.time()

        # Reset per-file labels
        for path, item in self.file_list.path_items.items():
            fname = QFileInfo(path).fileName()
            item.setText(fname)

        # Setup ProcessManager for this batch
        self.process_manager.parallel_enabled = self.parallel_enabled
        self.process_manager.max_parallel = self.max_parallel
        self.process_manager.start_batch(
            file_paths, self.parallel_enabled, self.max_parallel
        )

        # Store total for UI updates
        self.total = len(file_paths)
        self.completed = 0

        # Enable process tab if needed
        if self.processes_tab.count() == 1:  # Only has main log tab
            self.processes_tab.addTab(self.progress_area, "Processes")

        # Log batch start
        self.log.appendPlainText(f"Starting conversion of {self.total} files")
        if self.parallel_enabled:
            self.log.appendPlainText(
                f"Parallel mode enabled with {self.max_parallel} workers"
            )

        # Start processing
        if self.parallel_enabled:
            # Start multiple processes up to max_parallel
            max_parallel = min(self.max_parallel, len(file_paths))
            self.log.appendPlainText(f"Starting {max_parallel} parallel processes")
            for _ in range(max_parallel):
                self._process_next(start_btn, stop_btn)
        else:
            # Start first file only
            self._process_next(start_btn, stop_btn)

    def _process_next(self, start_btn, stop_btn):
        """Process the next file in the queue"""
        # Check if queue is empty
        if not self.process_manager.queue:
            # Only finish if all processes are done in parallel mode
            if not self.parallel_enabled or not self.process_manager.processes:
                self._finish(start_btn, stop_btn)
            return

        # Get next file from queue
        path = self.process_manager.queue.pop(0)
        self.current_path = path
        filename = QFileInfo(path).fileName()

        # Update file list item to show 'processing' status
        if hasattr(self.file_list, "set_status"):
            self.file_list.set_status(path, "processing")

        # Only update the label for the first file in sequential mode
        if not self.parallel_enabled or not self.process_manager.processes:
            self.current_file_label.setText(f"Processing: {filename}")

        # Determine codec and output file extension
        codec_idx = self._get_codec_for_path(path)
        ext = CodecHelpers.get_output_extension(codec_idx)

        # Add _RC suffix to output filename
        out_path = os.path.splitext(path)[0] + "_RC" + ext

        # Create ffmpeg command
        args = []

        # Input options
        # Add hardware acceleration options
        hw_args, hw_message = CodecHelpers.get_hardware_acceleration_args(
            self.hwdecode_cb.currentIndex()
        )
        args.extend(hw_args)
        if hw_message:
            self.log.appendPlainText(hw_message)

        # Check if we need to add the genpts flag for MPEGTS timing issues
        # This applies when restarting a process that had previous issues
        for (
            proc_id,
            proc_data,
        ) in self.process_manager.progress_tracker.processes.items():
            if proc_data.get(
                "path"
            ) == path and self.process_manager.progress_tracker.needs_genpts_flag(
                proc_id
            ):
                self.log.appendPlainText(
                    f"Adding -fflags +genpts to fix MPEGTS timing issues for {path}"
                )
                args.extend(["-fflags", "+genpts"])
                break

        # Input file
        args.extend(["-i", path])

        # Calculate optimal thread count
        thread_count = self._optimize_threads_for_codec(codec_idx)

        # Get encoder configuration and messages
        encoder_args, encoder_message = CodecHelpers.get_encoder_configuration(
            codec_idx, thread_count, self.parallel_enabled, self.crf_sb.value()
        )
        args.extend(encoder_args)
        if encoder_message:
            self.log.appendPlainText(encoder_message)

        # Handle audio codec configuration
        audio_args, audio_message = CodecHelpers.get_audio_codec_args(path, codec_idx)
        args.extend(audio_args)
        if audio_message:
            self.log.appendPlainText(audio_message)

        # Common options
        args.extend(
            [
                "-y",  # Overwrite output files
                out_path,
            ]
        )

        # Start the process using process manager
        process = self.process_manager.start_process(path, args)

        # Connect process finished signal
        process.finished.connect(
            lambda exitCode,
            exitStatus,
            p=process,
            s=start_btn,
            st=stop_btn,
            path=path: self._on_process_finished(p, s, st, path)
        )

        # Create widget to display progress
        self._create_process_widget(process, path)

    def _get_codec_for_path(self, path):
        """Get the appropriate codec index for a given file path"""
        if self.auto_balance_enabled and path in self.file_codec_assignments:
            return self.file_codec_assignments[path]
        return self.format_cb.currentIndex()

    def _optimize_threads_for_codec(self, codec_idx=None):
        """Optimize thread count based on selected codec and parallel processing mode"""
        codec_idx = self.format_cb.currentIndex() if codec_idx is None else codec_idx
        return CodecHelpers.optimize_threads_for_codec(
            codec_idx, self.parallel_enabled, self.file_codec_assignments
        )

    def _log_output(self, process: QProcess, chunk: str):
        """Process output from ffmpeg and update UI"""
        # Skip empty data
        if not chunk:
            return

        # With smart buffer enabled, don't update UI immediately for every output
        if hasattr(self, "smart_buffer_cb") and self.smart_buffer_cb.isChecked():
            # Store the output for batch processing
            if process not in self.pending_process_outputs:
                self.pending_process_outputs[process] = []

            # Add to buffer
            self.pending_process_outputs[process].append(chunk)

            # Start UI update timer if not already running
            if not self.ui_update_timer.isActive():
                self.ui_update_timer.start()
        else:
            # Immediate update mode - just add to logs
            # Progress tracking is now handled by the process manager
            self._add_to_logs(process, chunk)

    def _add_to_logs(self, process, chunk):
        """Add chunk to main log and process-specific log with guaranteed size limits"""
        # Main log with enforced size limits
        self._add_to_main_log(chunk)
        
        # Process-specific log with enforced size limits
        self._add_to_process_log(process, chunk)
    
    def _add_to_main_log(self, chunk):
        """Add to main log with guaranteed size management"""
        MAX_LOG_SIZE = LogConfig.MAIN_LOG_MAX_SIZE
        TRUNCATE_LINES = LogConfig.MAIN_LOG_TRUNCATE_LINES
        
        current_text = self.log.toPlainText()
        if len(current_text) > MAX_LOG_SIZE:
            # Truncate to keep only recent entries
            lines = current_text.split('\n')
            lines_to_keep = lines[-TRUNCATE_LINES:]
            self.log.clear()
            self.log.appendPlainText("[Log truncated to save memory]\n")
            self.log.appendPlainText('\n'.join(lines_to_keep))
        
        self.log.appendPlainText(chunk)
        
        # Auto-scroll to bottom
        vsb = self.log.verticalScrollBar()
        vsb.setValue(vsb.maximum())
    
    def _add_to_process_log(self, process, chunk):
        """Add to process-specific log with guaranteed size management"""
        if process not in self.process_logs:
            return
            
        MAX_PROCESS_LOG_SIZE = LogConfig.PROCESS_LOG_MAX_SIZE
        
        process_log = self.process_logs[process]["log"]
        current_text = process_log.toPlainText()
        
        if len(current_text) > MAX_PROCESS_LOG_SIZE:
            # Truncate to keep only recent entries
            lines = current_text.split('\n')
            lines_to_keep = lines[-LogConfig.PROCESS_LOG_TRUNCATE_LINES:]
            process_log.clear()
            process_log.appendPlainText("[Log truncated to save memory]\n")
            process_log.appendPlainText('\n'.join(lines_to_keep))
        
        process_log.appendPlainText(chunk)
        
        # Auto-scroll to bottom
        vsb = process_log.verticalScrollBar()
        vsb.setValue(vsb.maximum())

    # The _process_output method has been removed as its functionality
    # is now handled by the ProcessManager and ProcessProgressTracker classes

    def _update_ui(self):
        """Batch update the UI with all pending process outputs"""
        # Process all pending outputs
        for process, chunks in list(self.pending_process_outputs.items()):
            # Skip if process is no longer valid
            if process not in [p for p, _ in self.process_manager.processes]:
                self.pending_process_outputs.pop(process, None)
                continue

            # Combine all chunks for this process
            combined_chunk = "".join(chunks)

            # Add to logs
            self._add_to_logs(process, combined_chunk)

            # Process manager handles progress updates through signals
            # so we don't need to manually process output here

            # Clear pending chunks for this process
            self.pending_process_outputs[process] = []

        # Update overall progress
        self._update_overall_progress()

    def _update_process_progress(self):
        """Update individual process progress widgets with detailed information"""
        for process, widgets in list(self.process_widgets.items()):
            # Skip if process is no longer valid
            if process not in [p for p, _ in self.process_manager.processes]:
                continue

            # Get progress data for this process
            progress_data = self.process_manager.get_process_progress(process)
            if not progress_data:
                continue

            # Update progress bar
            percent = int(progress_data.get("current_pct", 0))
            widgets["progress"].setValue(percent)

            # Update file list item with progress percentage
            if (
                "path" in widgets
                and hasattr(self, "file_list")
                and isinstance(self.file_list, FileListWidget)
            ):
                self.file_list.update_progress(widgets["path"], percent)

            # Update status label based on progress
            if percent < 5:
                widgets["status_label"].setText("<b>⏳ Starting...</b>")
                widgets["status_label"].setStyleSheet(
                    "color: #0066cc; font-size: 10pt;"
                )
            elif percent < 100:
                widgets["status_label"].setText(f"<b>⚙️ {percent}%</b>")
                widgets["status_label"].setStyleSheet(
                    "color: #0066cc; font-size: 10pt;"
                )
            else:
                widgets["status_label"].setText("<b>✅ Complete</b>")
                widgets["status_label"].setStyleSheet(
                    "color: #00aa00; font-size: 10pt;"
                )

            # Update FPS display
            fps = progress_data.get("fps", 0)
            widgets["fps_label"].setText(f"📊 FPS: {fps}")

            # Calculate and show estimated file size
            if "file_size" not in widgets:
                # Estimate based on format and duration
                duration = progress_data.get("duration", 0)
                codec_idx = self.format_cb.currentIndex()
                # Rough size estimates in MB per minute based on codec
                size_factors = {0: 8, 1: 8, 2: 6, 3: 5, 4: 50, 5: 80}
                size_factor = size_factors.get(codec_idx, 10)
                est_size_mb = (duration / 60) * size_factor
                widgets["file_size"] = est_size_mb
                widgets["size_label"].setText(f"💾 ~{est_size_mb:.1f} MB")

            # Update ETA display
            remain = progress_data.get("remain", 0)
            elapsed = progress_data.get("elapsed", 0)
            if remain > 0:
                eta_text = progress_data.get("remain_str", "")
                widgets["eta_label"].setText(f"⏱️ ETA: {eta_text}")

                # Calculate and show processing speed (MB/s)
                if elapsed > 0 and "file_size" in widgets:
                    processed_mb = (widgets["file_size"] * percent) / 100
                    speed = processed_mb / elapsed
                    if speed > 0:
                        widgets["size_label"].setText(
                            f"💾 ~{widgets['file_size']:.1f} MB ({speed:.1f} MB/s)"
                        )
            else:
                widgets["eta_label"].setText("⏱️ Finishing...")

    def _update_overall_progress(self):
        """Update overall progress based on tracker data"""
        # First update individual process progress
        self._update_process_progress()

        # Then update overall progress
        overall = self.process_manager.get_overall_progress()
        if not overall:
            # If no progress data available, use a simplified approach
            if self.total > 0 and self.batch_start_time:
                weighted_pct = (self.completed * 100) / self.total
                self.total_progress.setValue(int(weighted_pct))

                # Update window title with percentage
                self.setWindowTitle(f"TS Converter GUI - {weighted_pct:.1f}%")

                # Update current file label with percentage in bold if not in parallel mode
                if not self.parallel_enabled and self.current_path:
                    filename = QFileInfo(self.current_path).fileName()
                    self.current_file_label.setText(
                        f"Processing: {filename} - <b style='font-size: 13pt; color: #0066cc;'>{weighted_pct:.1f}%</b>"
                    )
            return
        # Update total progress bar with weighted percentage
        weighted_pct = overall["weighted_pct"]
        self.total_progress.setValue(int(weighted_pct))

        # Get codec distribution info for status display
        codec_dist = self.process_manager.get_codec_distribution()
        codec_info = ""
        if codec_dist.get("GPU", 0) > 0:
            codec_info += f"{codec_dist['GPU']} GPU"
        if codec_dist.get("CPU", 0) > 0:
            if codec_info:
                codec_info += " + "
            codec_info += f"{codec_dist['CPU']} CPU"

        # Update status bar with ETA information and percentage
        self.eta_label.setText(
            f"Overall ETA: <b>{overall['eta_str']}</b> | "
            f"Elapsed: {overall['elapsed_str']} | "
            f"<span style='font-size: 12pt; font-weight: bold; color: #0066cc;'>{weighted_pct:.1f}%</span>"
        )

        # Update current file label with active files info and percentage
        if self.parallel_enabled:
            self.current_file_label.setText(
                f"Processing {overall['active_count']} file(s) ({codec_info}) - "
                f"<b style='color: #0066cc;'>{weighted_pct:.1f}%</b> - "
                f"Completed: {overall['completed_count']}/{overall['total_count']}"
            )
        elif self.current_path:  # Single file mode
            filename = QFileInfo(self.current_path).fileName()
            self.current_file_label.setText(
                f"Processing: {filename} - <b style='font-size: 13pt; color: #0066cc;'>{weighted_pct:.1f}%</b>"
            )

        # Simplified timer management - ProcessManager handles the main timing
        has_pending_outputs = any(chunks for chunks in self.pending_process_outputs.values())
        
        if has_pending_outputs and not self.ui_update_timer.isActive():
            # Start fallback timer only for pending output processing
            self.ui_update_timer.start()
        elif not has_pending_outputs and self.ui_update_timer.isActive():
            # Stop fallback timer when no pending outputs
            self.ui_update_timer.stop()

        # Duplicate method has been removed

        # Update current file label with active files info
        if self.parallel_enabled:
            self.current_file_label.setText(
                f"Processing {overall['active_count']} file(s) ({codec_info}) - "
                f"Completed: {overall['completed_count']}/{overall['total_count']}"
            )

        # Timer is now managed by ProcessManager, no need for redundant management here

    def _on_process_finished(
        self,
        process: QProcess,
        start_btn: QPushButton,
        stop_btn: QPushButton,
        path: str | None = None,
    ) -> None:
        process_path = path or self.current_path
        # Ensure process_path is a string before use
        if process_path is None:
            self.log.appendPlainText("Error: process_path is None")
            return

        exit_code = process.exitCode()
        error_string = (
            process.errorString()
            if hasattr(process, "errorString")
            else "Unknown error"
        )

        # Print debug information
        self.log.appendPlainText(f"Process finished for: {process_path}")
        self.log.appendPlainText(f"Exit code: {exit_code}, Error: {error_string}")

        # Get the last few lines of process output for debugging
        if (
            process in self.process_manager.process_logs
            and self.process_manager.process_logs[process]
        ):
            last_logs = "\n".join(self.process_manager.process_logs[process][-5:])
            self.log.appendPlainText(f"Last output: {last_logs}")

        # Mark process as completed in the process manager
        self.process_manager.mark_process_finished(
            process, process_path
        )  # Mark as finished and update progress

        # Update process widget with final status
        if process in self.process_widgets:
            widgets = self.process_widgets[process]

            # Set progress to 100% or 0% based on success/failure
            if exit_code == 0:
                widgets["progress"].setValue(100)
                widgets["status_label"].setText("<b>✅ Complete</b>")
                widgets["status_label"].setStyleSheet(
                    "color: #00aa00; font-size: 10pt;"
                )

                # Calculate elapsed time and final stats
                elapsed = time.time() - widgets.get("start_time", time.time())
                elapsed_str = self._format_time(elapsed)
                widgets["eta_label"].setText(f"⏱️ Time: {elapsed_str}")

                # Add completion message to log
                widgets["log"].appendPlainText(f"Conversion complete in {elapsed_str}")

                # If we have size info, update with final size
                try:
                    codec_idx = self._get_codec_for_path(process_path)
                    output_file = os.path.splitext(process_path)[0] + "_RC"
                    if codec_idx in [0, 1, 2, 3, 5, 6]:
                        output_file += ".mp4"
                    elif codec_idx == 4:
                        output_file += ".mov"

                    if os.path.exists(output_file):
                        size_mb = os.path.getsize(output_file) / (1024 * 1024)
                        widgets["size_label"].setText(f"💾 {size_mb:.1f} MB")
                except (OSError, ValueError, KeyError):
                    pass
            else:
                # Failed conversion
                widgets["progress"].setValue(0)
                widgets["status_label"].setText(f"<b>❌ Failed (code {exit_code})</b>")
                widgets["status_label"].setStyleSheet(
                    "color: #cc0000; font-size: 10pt;"
                )
                widgets["eta_label"].setText("⏱️ Process failed")
                widgets["log"].appendPlainText(
                    f"Conversion failed with error {error_string}"
                )

            # Update codec indicator with completion status
            name = QFileInfo(process_path).fileName()
            widgets["label"].setText(f"<b>{name}</b>")

            # Make a subtle background change for completed items
            bgcolor = "#efffef" if exit_code == 0 else "#fff0f0"
            widgets["container"].setStyleSheet(
                f"QFrame {{ background-color: {bgcolor}; border-radius: 5px; }}"
            )

        # Schedule the process widget for removal after a short delay
        # This allows the user to see the final status
        QTimer.singleShot(UIConfig.WIDGET_REMOVAL_DELAY, lambda: self._remove_process_widget(process))

        # finalize per-file display using enhanced FileListWidget methods
        if hasattr(self.file_list, "set_status"):
            status = "completed" if exit_code == 0 else "failed"
            self.file_list.set_status(process_path, status)
        else:
            # Fallback for compatibility if using old file list implementation
            if process_path in self.file_list.path_items:
                item = self.file_list.path_items[process_path]
                name = QFileInfo(process_path).fileName()
                status = "Done" if exit_code == 0 else "Failed"
                item.setText(f"{name} — {status}")

                # Mark completed conversions in green
                if exit_code == 0:
                    item.setForeground(
                        QColor(0, 170, 0)
                    )  # Green color for completed items

        # Delete source if requested and successful
        if (
            exit_code == 0
            and hasattr(self, "delete_cb")
            and self.delete_cb is not None
            and self.delete_cb.isChecked()
        ):
            try:
                os.remove(process_path)
                self.log.appendPlainText(f"Deleted source: {process_path}")
            except Exception as e:
                self.log.appendPlainText(f"Failed to delete {process_path}: {e}")

        # Update totals - only increment counter
        # Progress bar update is now handled by _update_overall_progress
        self.completed += 1

        # In parallel mode, start a new process for each completed one
        if self.parallel_enabled and self.process_manager.queue:
            self._process_next(start_btn, stop_btn)
        # If not parallel, or no more files in the queue
        elif not self.parallel_enabled:
            if self.completed >= self.total:
                self._finish(start_btn, stop_btn)
            else:
                self._process_next(start_btn, stop_btn)
        # Check if all processes are done in parallel mode
        elif not self.process_manager.processes and self.completed >= self.total:
            self._finish(start_btn, stop_btn)

    def stop_conversion(self, start_btn: QPushButton, stop_btn: QPushButton):
        # Stop all processes using the ProcessManager
        stopped_processes = self.process_manager.stop_all_processes()

        # Update status of all process widgets
        for process, _ in stopped_processes:
            if process in self.process_widgets:
                self.process_widgets[process]["label"].setText(
                    f"<b>{QFileInfo(self.process_widgets[process]['path']).fileName()}</b> - Stopped"
                )

        # Schedule removal of all process widgets after a delay
        for process in list(self.process_widgets.keys()):
            QTimer.singleShot(UIConfig.STOPPED_WIDGET_DELAY, lambda p=process: self._remove_process_widget(p))

        self.log.appendPlainText("Conversion stopped by user.")
        start_btn.setEnabled(True)
        stop_btn.setEnabled(False)
        self.eta_label.clear()
        self.current_file_label.clear()

    def _finish(self, start_btn: QPushButton, stop_btn: QPushButton):
        self.log.appendPlainText("All conversions complete.")
        start_btn.setEnabled(True)
        stop_btn.setEnabled(False)
        self.current_file_label.clear()
        self.eta_label.clear()

        # Return to main log tab when finished
        self.processes_tab.setCurrentIndex(0)

    def _show_about(self):
        QMessageBox.information(
            self,
            f"About {AppConfig.APP_NAME}",
            f"{AppConfig.APP_NAME} - {AppConfig.APP_DESCRIPTION}\nVersion {AppConfig.APP_VERSION}\nAdvanced Hybrid Encoding\n"
            + "Optimized for Intel i9-14900HX + RTX 4090\n"
            + "Features: HEVC/AV1 NVENC, multi-format support, audio passthrough, smart auto-balance",
        )

    def closeEvent(self, event):
        running = bool(self.process_manager.processes)
        if running:
            if (
                QMessageBox.question(
                    self,
                    "Conversions running",
                    "Jobs are still in progress. Quit anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                == QMessageBox.StandardButton.No
            ):
                event.ignore()
                return
            # Stop all processes
            self.process_manager.stop_all_processes()

        # Guaranteed cleanup of all resources
        try:
            # Clean up UI elements
            self._cleanup_all_widgets()
            
            # Clean up process manager resources
            self.process_manager.cleanup_all_resources()
            
        except Exception as e:
            print(f"Warning: Error during shutdown cleanup: {e}")

        # Save application settings
        try:
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("splitterState", self.splitter.saveState())
            self.settings.setValue("lastDir", self.last_dir)
        except Exception as e:
            print(f"Warning: Error saving settings: {e}")
            
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
