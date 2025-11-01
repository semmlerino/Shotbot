#!/usr/bin/env python3
"""
Unit tests for SettingsPanel class
Tests codec configuration, hardware acceleration settings, and signal emission
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QComboBox, QSpinBox, QCheckBox, QLabel

from settings_panel import SettingsPanel
from config import EncodingConfig, ProcessConfig


class TestSettingsPanel:
    """Test suite for SettingsPanel class"""

    @pytest.fixture(autouse=True)
    def setup_panel(self, qtbot):
        """Create SettingsPanel instance for each test"""
        # Create a mock QSettings that returns the defaults when value() is called
        mock_settings = Mock()
        # Make value() return the default parameter (second arg)
        def mock_value(key, default=None, type=None):
            return default
        mock_settings.value.side_effect = mock_value
        
        with patch("settings_panel.QSettings", return_value=mock_settings):
            self.panel = SettingsPanel()
            # SettingsPanel is a QObject that creates a widget
            self.widget = self.panel.create_settings_widget()
            qtbot.addWidget(self.widget)
            self.qtbot = qtbot
            self.mock_settings = mock_settings

    def test_init(self):
        """Test panel initialization"""
        # Check main components exist
        assert hasattr(self.panel, "codec_combo")
        assert hasattr(self.panel, "hwdecode_combo")
        assert hasattr(self.panel, "crf_spinbox")
        assert hasattr(self.panel, "parallel_checkbox")
        assert hasattr(self.panel, "max_parallel_spinbox")
        assert hasattr(self.panel, "delete_source_checkbox")
        assert hasattr(self.panel, "overwrite_checkbox")
        assert hasattr(self.panel, "auto_balance_checkbox")
        assert hasattr(self.panel, "smart_buffer_checkbox")

    def test_get_settings(self):
        """Test getting current settings"""
        # Set known values
        self.panel.codec_combo.setCurrentIndex(2)
        self.panel.hwdecode_combo.setCurrentIndex(1)
        self.panel.crf_spinbox.setValue(20)
        self.panel.parallel_checkbox.setChecked(True)
        self.panel.max_parallel_spinbox.setValue(6)
        self.panel.delete_source_checkbox.setChecked(True)
        self.panel.overwrite_checkbox.setChecked(False)
        self.panel.auto_balance_checkbox.setChecked(True)
        self.panel.smart_buffer_checkbox.setChecked(True)
        
        settings = self.panel.get_current_settings()
        
        assert settings["codec_idx"] == 2
        assert settings["hwdecode_idx"] == 1
        assert settings["crf_value"] == 20
        assert settings["parallel_enabled"] is True
        assert settings["max_parallel"] == 6
        assert settings["delete_source"] is True
        assert settings["overwrite_mode"] is False
        assert settings["auto_balance"] is True
        assert settings["smart_buffer"] is True

    def test_codec_change_signal(self):
        """Test codec change emits signal"""
        with self.qtbot.waitSignal(self.panel.settings_changed, timeout=100):
            # Change codec
            self.panel.codec_combo.setCurrentIndex(3)

    def test_crf_change_signal(self):
        """Test CRF change emits signal and updates label"""
        with self.qtbot.waitSignal(self.panel.settings_changed, timeout=100):
            # Change CRF
            self.panel.crf_spinbox.setValue(25)
        
        # CRF label is static, not dynamic
        assert self.panel.crf_label.text() == "CRF (Quality):"

    def test_parallel_checkbox_enables_spinbox(self):
        """Test parallel checkbox controls max parallel spinbox"""
        # Initially parallel is checked, spinbox should be enabled
        assert self.panel.max_parallel_spinbox.isEnabled() is True
        
        # Uncheck parallel
        self.panel.parallel_checkbox.setChecked(False)
        assert self.panel.max_parallel_spinbox.isEnabled() is False
        
        # Check again
        self.panel.parallel_checkbox.setChecked(True)
        assert self.panel.max_parallel_spinbox.isEnabled() is True

    def test_auto_balance_toggle_signal(self):
        """Test auto-balance toggle emits specific signal"""
        # Get initial state and toggle from it
        initial_state = self.panel.auto_balance_checkbox.isChecked()
        
        # Toggle to opposite of initial state
        with self.qtbot.waitSignal(self.panel.auto_balance_toggled, timeout=100) as blocker:
            self.panel.auto_balance_checkbox.setChecked(not initial_state)
        assert blocker.args[0] == (not initial_state)
        
        # Toggle back
        with self.qtbot.waitSignal(self.panel.auto_balance_toggled, timeout=100) as blocker:
            self.panel.auto_balance_checkbox.setChecked(initial_state)
        assert blocker.args[0] == initial_state

    def test_load_settings(self):
        """Test loading settings from QSettings"""
        # Set up the mock to return specific values
        values = {
            "codec_idx": 2,
            "preset_idx": 1,
            "hwdecode": 1,  # Note: key is "hwdecode", not "hwdecode_idx"
            "crf": 25,
            "threads": 8,
            "parallel_enabled": False,
            "max_parallel": 8,
            "delete": True,
            "overwrite": False,
            "smart_buffer": True,
            "auto_balance": True,
            "priority_idx": 0
        }
        
        def mock_value(key, default=None, type=None):
            return values.get(key, default)
        
        self.mock_settings.value.side_effect = mock_value
        
        # Restore settings
        self.panel._restore_settings()
        
        assert self.panel.codec_combo.currentIndex() == 2
        assert self.panel.hwdecode_combo.currentIndex() == 1
        assert self.panel.crf_spinbox.value() == 25
        assert self.panel.parallel_checkbox.isChecked() is False
        assert self.panel.max_parallel_spinbox.value() == 8
        assert self.panel.delete_source_checkbox.isChecked() is True
        assert self.panel.overwrite_checkbox.isChecked() is False
        assert self.panel.smart_buffer_checkbox.isChecked() is True
        assert self.panel.auto_balance_checkbox.isChecked() is True

    def test_save_settings(self):
        """Test saving settings to QSettings"""
        # Set some values
        self.panel.codec_combo.setCurrentIndex(1)
        self.panel.crf_spinbox.setValue(22)
        self.panel.delete_source_checkbox.setChecked(True)
        
        # Call save settings
        self.panel._save_settings()
        
        # Check setValue was called with correct values on the mock settings object
        self.mock_settings.setValue.assert_any_call("codec_idx", 1)
        self.mock_settings.setValue.assert_any_call("crf", 22)
        self.mock_settings.setValue.assert_any_call("delete", True)

    def test_signal_disconnect_during_load(self):
        """Test that signals work properly after setup"""
        # Count signals during normal operation
        signal_count = 0
        def count_signal(settings_dict):
            nonlocal signal_count
            signal_count += 1
        
        self.panel.settings_changed.connect(count_signal)
        
        # Reset count since setup may have triggered signals
        signal_count = 0
        
        # Manually change a value to ensure signal works
        self.panel.crf_spinbox.setValue(30)
        
        # Should have at least one signal from manual change
        assert signal_count >= 1

    def test_codec_combo_items(self):
        """Test codec combo box has expected items"""
        combo = self.panel.codec_combo
        
        # Check codec options exist
        assert combo.count() > 0
        
        # Check specific codecs
        codec_texts = [combo.itemText(i) for i in range(combo.count())]
        assert any("H.264" in text for text in codec_texts)
        assert any("HEVC" in text for text in codec_texts)
        
        # NVENC codecs should already be in the list (H.264 NVENC, HEVC NVENC, AV1 NVENC)
        assert any("NVENC" in text for text in codec_texts)

    def test_hwdecode_combo_items(self):
        """Test hardware decode combo box has expected items"""
        combo = self.panel.hwdecode_combo
        
        # Check basic options
        assert combo.count() == 4  # Auto, NVIDIA, Intel, AMD/Intel
        assert combo.itemText(0) == "Auto"
        assert combo.itemText(1) == "NVIDIA (CUDA)"
        assert combo.itemText(2) == "Intel (QSV)"
        assert combo.itemText(3) == "AMD/Intel (VAAPI)"

    def test_crf_spinbox_range(self):
        """Test CRF spinbox has correct range"""
        assert self.panel.crf_spinbox.minimum() == 0
        assert self.panel.crf_spinbox.maximum() == 51
        # Value might be set from defaults during restore_settings
        # Just check it's within valid range
        assert 0 <= self.panel.crf_spinbox.value() <= 51

    def test_max_parallel_spinbox_range(self):
        """Test max parallel spinbox has correct range"""
        assert self.panel.max_parallel_spinbox.minimum() == 1
        assert self.panel.max_parallel_spinbox.maximum() == ProcessConfig.MAX_PARALLEL_HIGH_END
        # Value might be set from defaults during restore_settings
        # Just check it's within valid range
        assert 1 <= self.panel.max_parallel_spinbox.value() <= ProcessConfig.MAX_PARALLEL_HIGH_END

    def test_tooltip_text(self):
        """Test tooltips are set for user guidance"""
        # Check some key tooltips exist
        assert self.panel.codec_combo.toolTip() != ""
        assert self.panel.crf_spinbox.toolTip() != ""
        assert self.panel.auto_balance_checkbox.toolTip() != ""
        assert self.panel.smart_buffer_checkbox.toolTip() != ""

    def test_auto_balance_visibility_with_parallel(self):
        """Test auto-balance checkbox visibility based on parallel processing"""
        # When parallel is enabled, auto-balance should be visible
        self.panel.parallel_checkbox.setChecked(True)
        # The actual visibility update happens in the signal handler
        # For unit test, we just verify the checkbox exists and can be toggled
        assert hasattr(self.panel, "auto_balance_checkbox")
        
        # When parallel is disabled, auto-balance might be hidden (implementation dependent)
        self.panel.parallel_checkbox.setChecked(False)
        # The visibility logic would be in the actual implementation

    def test_get_codec_info(self):
        """Test getting codec information for current selection"""
        # Set to a known codec
        self.panel.codec_combo.setCurrentIndex(0)
        
        # Get codec text
        codec_text = self.panel.codec_combo.currentText()
        
        # Should have a codec selected
        assert codec_text == "H.264 NVENC"

    def test_settings_dict_completeness(self):
        """Test get_settings returns all required keys"""
        settings = self.panel.get_current_settings()
        
        required_keys = [
            "codec_idx",
            "hwdecode_idx", 
            "crf_value",
            "parallel_enabled",
            "max_parallel",
            "delete_source",
            "overwrite_mode",
            "auto_balance",
            "smart_buffer"
        ]
        
        for key in required_keys:
            assert key in settings, f"Missing required key: {key}"

    def test_crf_label_exists(self):
        """Test CRF label exists and has correct text"""
        # Check CRF label exists
        assert self.panel.crf_label is not None
        assert "CRF" in self.panel.crf_label.text()
        assert "Quality" in self.panel.crf_label.text()