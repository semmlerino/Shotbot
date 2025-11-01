#!/usr/bin/env python3
"""
Settings Panel Module for PyMPEG
Handles all UI controls and settings management
"""

from typing import Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QSettings
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QPushButton,
)

from config import ProcessConfig, EncodingConfig, AppConfig


class SettingsPanel(QObject):
    """Manages conversion settings and UI controls"""

    # Signals for settings changes
    settings_changed = Signal(dict)  # Emitted when any setting changes
    auto_balance_toggled = Signal(bool)  # Emitted when auto-balance is toggled

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings(AppConfig.SETTINGS_ORG, AppConfig.SETTINGS_APP)

        # UI Controls (will be set by create_settings_widget)
        self.codec_combo: QComboBox
        self.preset_combo: QComboBox
        self.hwdecode_combo: QComboBox
        self.crf_spinbox: QSpinBox
        self.crf_label: QLabel
        self.threads_spinbox: QSpinBox
        self.parallel_checkbox: QCheckBox
        self.max_parallel_spinbox: QSpinBox
        self.delete_source_checkbox: QCheckBox
        self.overwrite_checkbox: QCheckBox
        self.smart_buffer_checkbox: QCheckBox
        self.auto_balance_checkbox: QCheckBox
        self.hevc_10bit_checkbox: QCheckBox
        self.nvenc_settings_button: QPushButton

        # Advanced NVENC settings
        self.nvenc_b_adapt: int = 2
        self.nvenc_ref_frames: int = 4
        self.nvenc_rc_mode: str = "vbr"
        self.nvenc_aq_strength: int = 1

        self._widget: Optional[QWidget] = None
        self.priority_combo: QComboBox

    def create_settings_widget(self) -> QWidget:
        """Create and return the settings widget"""
        if self._widget is not None:
            return self._widget

        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(8, 8, 8, 8)

        # Codec Settings Group
        codec_group = self._create_codec_settings_group()
        layout.addWidget(codec_group)

        # Performance Settings Group
        performance_group = self._create_performance_settings_group()
        layout.addWidget(performance_group)

        # Advanced Settings Group
        advanced_group = self._create_advanced_settings_group()
        layout.addWidget(advanced_group)

        # Load saved settings
        self._restore_settings()

        # Connect signals
        self._connect_signals()

        # Set up codec-dependent visibility (CRF only visible for x264 CPU)
        self._setup_codec_visibility()

        return self._widget

    def _create_codec_settings_group(self) -> QGroupBox:
        """Create the codec settings group"""
        group = QGroupBox("🎬 Codec Settings")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layout = QVBoxLayout(group)

        # Codec selection
        codec_layout = QHBoxLayout()
        codec_layout.addWidget(QLabel("Video Codec:"))

        self.codec_combo = QComboBox()
        self.codec_combo.addItems(
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
        self.codec_combo.setToolTip("Select video codec for encoding")
        codec_layout.addWidget(self.codec_combo)
        layout.addLayout(codec_layout)

        # Hardware decode
        hwdecode_layout = QHBoxLayout()
        hwdecode_layout.addWidget(QLabel("Hardware Decode:"))

        self.hwdecode_combo = QComboBox()
        self.hwdecode_combo.addItems(
            ["Auto", "NVIDIA (CUDA)", "Intel (QSV)", "AMD/Intel (VAAPI)"]
        )
        self.hwdecode_combo.setCurrentIndex(1)  # Default to NVIDIA for RTX 4090
        self.hwdecode_combo.setToolTip("Hardware acceleration for decoding")
        hwdecode_layout.addWidget(self.hwdecode_combo)
        layout.addLayout(hwdecode_layout)

        # Performance preset
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Preset:"))

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Standard", "High Quality", "Fast", "Ultra Fast"])
        self.preset_combo.setCurrentIndex(0)  # Default to Standard for better quality
        self.preset_combo.setToolTip(
            "Performance preset affects encoding speed vs. quality"
        )
        preset_layout.addWidget(self.preset_combo)
        layout.addLayout(preset_layout)

        # CRF/Quality
        crf_layout = QHBoxLayout()
        self.crf_label = QLabel("CRF (Quality):")
        crf_layout.addWidget(self.crf_label)

        self.crf_spinbox = QSpinBox()
        self.crf_spinbox.setRange(0, 51)
        self.crf_spinbox.setValue(EncodingConfig.DEFAULT_CRF_H264)
        self.crf_spinbox.setAccelerated(True)
        self.crf_spinbox.setToolTip(
            "Lower = better quality, larger file (18 recommended)"
        )
        crf_layout.addWidget(self.crf_spinbox)

        crf_layout.addWidget(QLabel("(18=high, 23=medium, 28=low)"))
        layout.addLayout(crf_layout)

        # Threads selector
        threads_layout = QHBoxLayout()
        threads_layout.addWidget(QLabel("Threads:"))

        import os

        self.threads_spinbox = QSpinBox()
        max_threads = os.cpu_count() or 4
        self.threads_spinbox.setRange(1, max_threads)
        optimal_threads = min(ProcessConfig.OPTIMAL_CPU_THREADS, max_threads)
        self.threads_spinbox.setValue(optimal_threads)
        self.threads_spinbox.setAccelerated(True)
        self.threads_spinbox.setToolTip("Number of threads for encoding")
        threads_layout.addWidget(self.threads_spinbox)
        layout.addLayout(threads_layout)

        return group

    def _create_performance_settings_group(self) -> QGroupBox:
        """Create the performance settings group"""
        group = QGroupBox("⚡ Performance Settings")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layout = QVBoxLayout(group)

        # Parallel processing
        parallel_layout = QHBoxLayout()
        self.parallel_checkbox = QCheckBox("Enable Parallel Processing")
        self.parallel_checkbox.setToolTip("Process multiple files simultaneously")
        parallel_layout.addWidget(self.parallel_checkbox)
        layout.addLayout(parallel_layout)

        # Max parallel processes
        max_parallel_layout = QHBoxLayout()
        max_parallel_layout.addWidget(QLabel("Max Parallel Processes:"))

        self.max_parallel_spinbox = QSpinBox()
        self.max_parallel_spinbox.setRange(1, ProcessConfig.MAX_PARALLEL_HIGH_END)
        self.max_parallel_spinbox.setValue(ProcessConfig.MAX_PARALLEL_DEFAULT)
        self.max_parallel_spinbox.setToolTip("Maximum number of simultaneous processes")
        max_parallel_layout.addWidget(self.max_parallel_spinbox)
        layout.addLayout(max_parallel_layout)

        # Auto-balance
        auto_balance_layout = QHBoxLayout()
        self.auto_balance_checkbox = QCheckBox("Auto-balance GPU/CPU workload")
        self.auto_balance_checkbox.setToolTip(
            "Automatically distribute files between GPU and CPU encoding"
        )
        auto_balance_layout.addWidget(self.auto_balance_checkbox)
        layout.addLayout(auto_balance_layout)

        # Process priority
        priority_layout = QHBoxLayout()
        priority_layout.addWidget(QLabel("Process Priority:"))

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Normal", "Low", "High"])
        self.priority_combo.setCurrentIndex(0)  # Default to Normal
        self.priority_combo.setToolTip(
            "Set FFmpeg process priority (High may affect system responsiveness)"
        )
        priority_layout.addWidget(self.priority_combo)
        layout.addLayout(priority_layout)

        return group

    def _create_advanced_settings_group(self) -> QGroupBox:
        """Create the advanced settings group"""
        group = QGroupBox("🔧 Advanced Settings")
        group.setStyleSheet("QGroupBox { font-weight: bold; }")
        layout = QVBoxLayout(group)

        # Delete source files
        delete_layout = QHBoxLayout()
        self.delete_source_checkbox = QCheckBox(
            "Delete source files after successful conversion"
        )
        self.delete_source_checkbox.setToolTip(
            "⚠️ This will permanently delete the original files!"
        )
        self.delete_source_checkbox.setStyleSheet("QCheckBox { color: #e74c3c; }")
        delete_layout.addWidget(self.delete_source_checkbox)
        layout.addLayout(delete_layout)

        # Overwrite existing files
        overwrite_layout = QHBoxLayout()
        self.overwrite_checkbox = QCheckBox("Overwrite existing files")
        self.overwrite_checkbox.setChecked(True)  # Default to True
        self.overwrite_checkbox.setToolTip(
            "Overwrite output files if they already exist"
        )
        overwrite_layout.addWidget(self.overwrite_checkbox)
        layout.addLayout(overwrite_layout)

        # Smart buffer mode
        smart_buffer_layout = QHBoxLayout()
        self.smart_buffer_checkbox = QCheckBox("Smart Buffer Mode")
        self.smart_buffer_checkbox.setChecked(True)
        self.smart_buffer_checkbox.setToolTip(
            "Optimize memory usage and CPU overhead during conversion"
        )
        smart_buffer_layout.addWidget(self.smart_buffer_checkbox)
        layout.addLayout(smart_buffer_layout)

        # 10-bit HEVC encoding
        hevc_10bit_layout = QHBoxLayout()
        self.hevc_10bit_checkbox = QCheckBox("Enable 10-bit HEVC encoding")
        self.hevc_10bit_checkbox.setToolTip(
            "Use 10-bit color depth for HEVC encoding (better quality, larger files)"
        )
        hevc_10bit_layout.addWidget(self.hevc_10bit_checkbox)
        layout.addLayout(hevc_10bit_layout)

        # Advanced NVENC Settings Button
        nvenc_button_layout = QHBoxLayout()
        self.nvenc_settings_button = QPushButton("⚙️ Advanced NVENC Settings")
        self.nvenc_settings_button.clicked.connect(self._show_nvenc_settings)
        nvenc_button_layout.addWidget(self.nvenc_settings_button)
        layout.addLayout(nvenc_button_layout)

        return group

    def _connect_signals(self) -> None:
        """Connect UI control signals"""
        required_controls = [
            self.codec_combo,
            self.preset_combo,
            self.hwdecode_combo,
            self.crf_spinbox,
            self.threads_spinbox,
            self.parallel_checkbox,
            self.max_parallel_spinbox,
            self.delete_source_checkbox,
            self.overwrite_checkbox,
            self.smart_buffer_checkbox,
            self.auto_balance_checkbox,
            self.priority_combo,
            self.hevc_10bit_checkbox,
        ]

        if not all(required_controls):
            return

        # Assert widgets are not None for type checker
        assert self.codec_combo is not None
        assert self.preset_combo is not None
        assert self.hwdecode_combo is not None
        assert self.crf_spinbox is not None
        assert self.threads_spinbox is not None
        assert self.parallel_checkbox is not None
        assert self.max_parallel_spinbox is not None
        assert self.delete_source_checkbox is not None
        assert self.overwrite_checkbox is not None
        assert self.smart_buffer_checkbox is not None
        assert self.auto_balance_checkbox is not None
        assert self.priority_combo is not None
        assert self.hevc_10bit_checkbox is not None

        # Connect all controls to emit settings_changed
        self.codec_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.preset_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.hwdecode_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.crf_spinbox.valueChanged.connect(self._on_settings_changed)
        self.threads_spinbox.valueChanged.connect(self._on_settings_changed)
        self.parallel_checkbox.toggled.connect(self._on_settings_changed)
        self.max_parallel_spinbox.valueChanged.connect(self._on_settings_changed)
        self.delete_source_checkbox.toggled.connect(self._on_settings_changed)
        self.overwrite_checkbox.toggled.connect(self._on_settings_changed)
        self.smart_buffer_checkbox.toggled.connect(self._on_settings_changed)

        # Special handling for auto-balance
        self.auto_balance_checkbox.toggled.connect(self._on_auto_balance_toggled)
        self.priority_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.hevc_10bit_checkbox.toggled.connect(self._on_settings_changed)

        # Enable/disable max parallel based on parallel checkbox
        def update_max_parallel_enabled(enabled: bool):
            assert self.max_parallel_spinbox is not None
            self.max_parallel_spinbox.setEnabled(enabled)

        self.parallel_checkbox.toggled.connect(update_max_parallel_enabled)

    def _setup_codec_visibility(self) -> None:
        """Set up codec-dependent UI visibility"""
        if not self.codec_combo or not self.crf_label or not self.crf_spinbox:
            return

        # Assert widgets are not None for type checker
        assert self.codec_combo is not None
        assert self.crf_label is not None
        assert self.crf_spinbox is not None

        def update_crf_visibility():
            # CRF is only relevant for x264 CPU (index 3)
            assert self.codec_combo is not None
            assert self.crf_label is not None
            assert self.crf_spinbox is not None

            is_x264 = self.codec_combo.currentIndex() == 3
            self.crf_label.setVisible(is_x264)
            self.crf_spinbox.setVisible(is_x264)

        # Connect codec change to visibility update
        self.codec_combo.currentIndexChanged.connect(update_crf_visibility)

        # Set initial visibility
        update_crf_visibility()

    def _on_settings_changed(self) -> None:
        """Handle settings change"""
        settings = self.get_current_settings()
        self.settings_changed.emit(settings)
        self._save_settings()

    def _on_auto_balance_toggled(self, enabled: bool) -> None:
        """Handle auto-balance toggle"""
        self.auto_balance_toggled.emit(enabled)
        self._on_settings_changed()  # Also emit general settings change

    def get_current_settings(self) -> Dict[str, Any]:
        """Get current settings from UI controls"""
        required_controls = [
            self.codec_combo,
            self.preset_combo,
            self.hwdecode_combo,
            self.crf_spinbox,
            self.threads_spinbox,
            self.parallel_checkbox,
            self.max_parallel_spinbox,
            self.delete_source_checkbox,
            self.overwrite_checkbox,
            self.smart_buffer_checkbox,
            self.auto_balance_checkbox,
            self.priority_combo,
            self.hevc_10bit_checkbox,
        ]

        if not all(required_controls):
            return {}

        # Assert widgets are not None for type checker
        assert self.codec_combo is not None
        assert self.preset_combo is not None
        assert self.hwdecode_combo is not None
        assert self.crf_spinbox is not None
        assert self.threads_spinbox is not None
        assert self.parallel_checkbox is not None
        assert self.max_parallel_spinbox is not None
        assert self.delete_source_checkbox is not None
        assert self.overwrite_checkbox is not None
        assert self.smart_buffer_checkbox is not None
        assert self.auto_balance_checkbox is not None
        assert self.priority_combo is not None
        assert self.hevc_10bit_checkbox is not None

        return {
            "codec_idx": self.codec_combo.currentIndex(),
            "preset_idx": self.preset_combo.currentIndex(),
            "hwdecode_idx": self.hwdecode_combo.currentIndex(),
            "crf_value": self.crf_spinbox.value(),
            "threads": self.threads_spinbox.value(),
            "parallel_enabled": self.parallel_checkbox.isChecked(),
            "max_parallel": self.max_parallel_spinbox.value(),
            "delete_source": self.delete_source_checkbox.isChecked(),
            "overwrite_mode": self.overwrite_checkbox.isChecked(),
            "smart_buffer": self.smart_buffer_checkbox.isChecked(),
            "auto_balance": self.auto_balance_checkbox.isChecked(),
            "priority_idx": self.priority_combo.currentIndex(),
            "hevc_10bit": self.hevc_10bit_checkbox.isChecked(),
            "nvenc_b_adapt": self.nvenc_b_adapt,
            "nvenc_ref_frames": self.nvenc_ref_frames,
            "nvenc_rc_mode": self.nvenc_rc_mode,
            "nvenc_aq_strength": self.nvenc_aq_strength,
        }

    def set_settings(self, settings: Dict[str, Any]) -> None:
        """Set UI controls from settings dictionary"""
        required_controls = [
            self.codec_combo,
            self.preset_combo,
            self.hwdecode_combo,
            self.crf_spinbox,
            self.threads_spinbox,
            self.parallel_checkbox,
            self.max_parallel_spinbox,
            self.delete_source_checkbox,
            self.overwrite_checkbox,
            self.smart_buffer_checkbox,
            self.auto_balance_checkbox,
            self.priority_combo,
            self.hevc_10bit_checkbox,
        ]

        if not all(required_controls):
            return

        # Assert widgets are not None for type checker
        assert self.codec_combo is not None
        assert self.preset_combo is not None
        assert self.hwdecode_combo is not None
        assert self.crf_spinbox is not None
        assert self.threads_spinbox is not None
        assert self.parallel_checkbox is not None
        assert self.max_parallel_spinbox is not None
        assert self.delete_source_checkbox is not None
        assert self.overwrite_checkbox is not None
        assert self.smart_buffer_checkbox is not None
        assert self.auto_balance_checkbox is not None
        assert self.priority_combo is not None
        assert self.hevc_10bit_checkbox is not None

        # Temporarily disconnect signals to avoid loops
        self._disconnect_signals()

        if "codec_idx" in settings:
            self.codec_combo.setCurrentIndex(settings["codec_idx"])
        if "preset_idx" in settings:
            self.preset_combo.setCurrentIndex(settings["preset_idx"])
        if "hwdecode_idx" in settings:
            self.hwdecode_combo.setCurrentIndex(settings["hwdecode_idx"])
        if "crf_value" in settings:
            self.crf_spinbox.setValue(settings["crf_value"])
        if "threads" in settings:
            self.threads_spinbox.setValue(settings["threads"])
        if "parallel_enabled" in settings:
            self.parallel_checkbox.setChecked(settings["parallel_enabled"])
        if "max_parallel" in settings:
            self.max_parallel_spinbox.setValue(settings["max_parallel"])
        if "delete_source" in settings:
            self.delete_source_checkbox.setChecked(settings["delete_source"])
        if "overwrite_mode" in settings:
            self.overwrite_checkbox.setChecked(settings["overwrite_mode"])
        if "smart_buffer" in settings:
            self.smart_buffer_checkbox.setChecked(settings["smart_buffer"])
        if "auto_balance" in settings:
            self.auto_balance_checkbox.setChecked(settings["auto_balance"])
        if "priority_idx" in settings:
            self.priority_combo.setCurrentIndex(settings["priority_idx"])

        # Unblock signals that were blocked during loading
        self.codec_combo.blockSignals(False)
        self.preset_combo.blockSignals(False)
        self.hwdecode_combo.blockSignals(False)
        self.crf_spinbox.blockSignals(False)
        self.threads_spinbox.blockSignals(False)
        self.parallel_checkbox.blockSignals(False)
        self.max_parallel_spinbox.blockSignals(False)
        self.delete_source_checkbox.blockSignals(False)
        self.overwrite_checkbox.blockSignals(False)
        self.smart_buffer_checkbox.blockSignals(False)
        self.auto_balance_checkbox.blockSignals(False)
        self.priority_combo.blockSignals(False)
        self.hevc_10bit_checkbox.blockSignals(False)

        # Reconnect signals
        self._connect_signals()

        # Update dependent controls
        self.max_parallel_spinbox.setEnabled(self.parallel_checkbox.isChecked())

    def _disconnect_signals(self) -> None:
        """Temporarily disconnect signals"""
        required_controls = [
            self.codec_combo,
            self.preset_combo,
            self.hwdecode_combo,
            self.crf_spinbox,
            self.threads_spinbox,
            self.parallel_checkbox,
            self.max_parallel_spinbox,
            self.delete_source_checkbox,
            self.overwrite_checkbox,
            self.smart_buffer_checkbox,
            self.auto_balance_checkbox,
            self.priority_combo,
            self.hevc_10bit_checkbox,
        ]

        if not all(required_controls):
            return

        # Assert widgets are not None for type checker
        assert self.codec_combo is not None
        assert self.preset_combo is not None
        assert self.hwdecode_combo is not None
        assert self.crf_spinbox is not None
        assert self.threads_spinbox is not None
        assert self.parallel_checkbox is not None
        assert self.max_parallel_spinbox is not None
        assert self.delete_source_checkbox is not None
        assert self.overwrite_checkbox is not None
        assert self.smart_buffer_checkbox is not None
        assert self.auto_balance_checkbox is not None
        assert self.priority_combo is not None
        assert self.hevc_10bit_checkbox is not None

        # Disconnect each signal individually to avoid issues
        # Block signals instead of disconnecting to avoid warnings
        self.codec_combo.blockSignals(True)
        self.preset_combo.blockSignals(True)
        self.hwdecode_combo.blockSignals(True)
        self.crf_spinbox.blockSignals(True)
        self.threads_spinbox.blockSignals(True)
        self.parallel_checkbox.blockSignals(True)
        self.max_parallel_spinbox.blockSignals(True)
        self.delete_source_checkbox.blockSignals(True)
        self.overwrite_checkbox.blockSignals(True)
        self.smart_buffer_checkbox.blockSignals(True)
        self.auto_balance_checkbox.blockSignals(True)
        self.priority_combo.blockSignals(True)
        self.hevc_10bit_checkbox.blockSignals(True)

    def _save_settings(self) -> None:
        """Save current settings to QSettings"""
        settings = self.get_current_settings()

        # Map to original QSettings keys for compatibility
        key_mapping = {
            "hwdecode_idx": "hwdecode",
            "crf_value": "crf",
            "delete_source": "delete",
            "overwrite_mode": "overwrite",
        }

        for key, value in settings.items():
            save_key = key_mapping.get(key, key)
            self.settings.setValue(save_key, value)

    def _restore_settings(self) -> None:
        """Restore settings from QSettings"""
        import os

        saved_settings = {
            "codec_idx": self.settings.value("codec_idx", 0, type=int),
            "preset_idx": self.settings.value(
                "preset_idx", 2, type=int
            ),  # Default to Fast
            "hwdecode_idx": self.settings.value(
                "hwdecode", 0, type=int
            ),  # Match original key
            "crf_value": self.settings.value(
                "crf", EncodingConfig.DEFAULT_CRF_H264, type=int
            ),  # Match original key
            "threads": self.settings.value(
                "threads",
                min(ProcessConfig.OPTIMAL_CPU_THREADS, os.cpu_count() or 4),
                type=int,
            ),
            "parallel_enabled": self.settings.value(
                "parallel_enabled", True, type=bool
            ),  # Default enabled for high-end
            "max_parallel": self.settings.value(
                "max_parallel", 4, type=int
            ),  # Default 4
            "delete_source": self.settings.value(
                "delete", False, type=bool
            ),  # Match original key
            "overwrite_mode": self.settings.value(
                "overwrite", True, type=bool
            ),  # Match original key
            "smart_buffer": self.settings.value("smart_buffer", True, type=bool),
            "auto_balance": self.settings.value(
                "auto_balance", True, type=bool
            ),  # Default enabled
            "priority_idx": self.settings.value(
                "priority_idx", 0, type=int
            ),  # Default to Normal
        }

        self.set_settings(saved_settings)

    def get_widget(self) -> QWidget:
        """Get the settings widget (create if necessary)"""
        if self._widget is None:
            return self.create_settings_widget()
        return self._widget

    def validate_settings(self) -> tuple[bool, str]:
        """Validate current settings and return (is_valid, error_message)"""
        settings = self.get_current_settings()

        # Check if AV1 is selected on non-RTX 40 systems
        if settings.get("codec_idx") == 3:  # AV1 NVENC
            # This would require hardware detection, for now just warn
            return True, "⚠️ AV1 NVENC requires RTX 40 series GPU"

        # Check parallel processing limits
        if (
            settings.get("parallel_enabled")
            and settings.get("max_parallel", 1) > ProcessConfig.MAX_PARALLEL_HIGH_END
        ):
            return (
                False,
                f"Maximum parallel processes cannot exceed {ProcessConfig.MAX_PARALLEL_HIGH_END}",
            )

        return True, ""

    def _show_nvenc_settings(self) -> None:
        """Show advanced NVENC settings dialog"""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout

        dialog = QDialog(self._widget)
        dialog.setWindowTitle("Advanced NVENC Settings")
        dialog.setModal(True)

        layout = QFormLayout()

        # B-adapt mode
        b_adapt_combo = QComboBox()
        b_adapt_combo.addItems(["Disabled", "Spatial", "Full"])
        b_adapt_combo.setCurrentIndex(self.nvenc_b_adapt)
        b_adapt_combo.setToolTip("B-frame adaptation mode for better compression")
        layout.addRow("B-frame Adaptation:", b_adapt_combo)

        # Reference frames
        ref_frames_spinbox = QSpinBox()
        ref_frames_spinbox.setRange(1, 16)
        ref_frames_spinbox.setValue(self.nvenc_ref_frames)
        ref_frames_spinbox.setToolTip(
            "Number of reference frames (higher = better quality, more VRAM)"
        )
        layout.addRow("Reference Frames:", ref_frames_spinbox)

        # Rate control mode
        rc_mode_combo = QComboBox()
        rc_mode_combo.addItems(
            ["VBR (Variable)", "CBR (Constant)", "CQP (Constant QP)"]
        )
        rc_mode_combo.setCurrentIndex(
            {"vbr": 0, "cbr": 1, "cqp": 2}.get(self.nvenc_rc_mode, 0)
        )
        rc_mode_combo.setToolTip("Rate control mode affects quality/bitrate balance")
        layout.addRow("Rate Control Mode:", rc_mode_combo)

        # AQ strength
        aq_strength_spinbox = QSpinBox()
        aq_strength_spinbox.setRange(0, 15)
        aq_strength_spinbox.setValue(self.nvenc_aq_strength)
        aq_strength_spinbox.setToolTip("Adaptive quantization strength (0=off, 15=max)")
        layout.addRow("AQ Strength:", aq_strength_spinbox)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        dialog.setLayout(layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Save settings
            self.nvenc_b_adapt = b_adapt_combo.currentIndex()
            self.nvenc_ref_frames = ref_frames_spinbox.value()
            self.nvenc_rc_mode = ["vbr", "cbr", "cqp"][rc_mode_combo.currentIndex()]
            self.nvenc_aq_strength = aq_strength_spinbox.value()

            # Emit settings changed
            self._on_settings_changed()
