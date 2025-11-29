"""Tests for QuickLaunchBar widget."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from PySide6.QtCore import Qt

from quick_launch_bar import (
    DEFAULT_QUICK_LAUNCH_CONFIGS,
    QuickLaunchBar,
    QuickLaunchConfig,
)
from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


class TestQuickLaunchBarInit:
    """Tests for QuickLaunchBar initialization."""

    def test_default_configs(self, qtbot: QtBot) -> None:
        """Uses default configs when none provided."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)

        # Should have buttons for all default apps
        assert len(bar._buttons) == len(DEFAULT_QUICK_LAUNCH_CONFIGS)
        for config in DEFAULT_QUICK_LAUNCH_CONFIGS:
            assert config.app_name in bar._buttons

    def test_custom_configs(self, qtbot: QtBot) -> None:
        """Accepts custom configurations."""
        configs = [
            QuickLaunchConfig("app1", "App One", "1", "#ff0000"),
            QuickLaunchConfig("app2", "App Two", "2", "#00ff00"),
        ]
        bar = QuickLaunchBar(configs=configs)
        qtbot.addWidget(bar)

        assert len(bar._buttons) == 2
        assert "app1" in bar._buttons
        assert "app2" in bar._buttons

    def test_buttons_disabled_initially(self, qtbot: QtBot) -> None:
        """Buttons are disabled until shot is set."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)

        for btn in bar._buttons.values():
            assert not btn.isEnabled()


class TestQuickLaunchBarButtonLabels:
    """Tests for button labels and shortcuts."""

    def test_button_shows_name_and_shortcut(self, qtbot: QtBot) -> None:
        """Button text includes app name and shortcut."""
        configs = [QuickLaunchConfig("test", "Test App", "T", "#333333")]
        bar = QuickLaunchBar(configs=configs)
        qtbot.addWidget(bar)

        btn = bar._buttons["test"]
        text = btn.text()

        assert "Test App" in text
        assert "(T)" in text

    def test_default_buttons_have_correct_shortcuts(self, qtbot: QtBot) -> None:
        """Default buttons show correct shortcuts."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)

        # Check expected shortcuts
        assert "(3)" in bar._buttons["3de"].text()
        assert "(N)" in bar._buttons["nuke"].text()
        assert "(M)" in bar._buttons["maya"].text()
        assert "(R)" in bar._buttons["rv"].text()


class TestQuickLaunchBarShotHandling:
    """Tests for shot selection handling."""

    def test_set_shot_enables_buttons(self, qtbot: QtBot) -> None:
        """Setting a shot enables all buttons."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)

        # Create mock shot
        mock_shot = MagicMock()

        bar.set_shot(mock_shot)

        for btn in bar._buttons.values():
            assert btn.isEnabled()

    def test_clear_shot_disables_buttons(self, qtbot: QtBot) -> None:
        """Clearing shot disables all buttons."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)

        mock_shot = MagicMock()
        bar.set_shot(mock_shot)
        bar.set_shot(None)

        for btn in bar._buttons.values():
            assert not btn.isEnabled()

    def test_set_enabled_controls_all_buttons(self, qtbot: QtBot) -> None:
        """set_enabled affects all buttons."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)

        bar.set_enabled(True)
        for btn in bar._buttons.values():
            assert btn.isEnabled()

        bar.set_enabled(False)
        for btn in bar._buttons.values():
            assert not btn.isEnabled()


class TestQuickLaunchBarLaunchSignal:
    """Tests for launch signal emission."""

    def test_click_emits_launch_requested(self, qtbot: QtBot) -> None:
        """Clicking button emits launch_requested signal."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)

        # Enable buttons with mock shot
        mock_shot = MagicMock()
        bar.set_shot(mock_shot)

        # Click 3de button
        with qtbot.waitSignal(bar.launch_requested, timeout=1000) as blocker:
            qtbot.mouseClick(bar._buttons["3de"], Qt.MouseButton.LeftButton)
            process_qt_events()

        assert blocker.args == ["3de"]

    def test_no_signal_without_shot(self, qtbot: QtBot) -> None:
        """No signal emitted when no shot selected."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)

        # Enable button manually but don't set shot
        bar._buttons["3de"].setEnabled(True)

        signals_received = []
        bar.launch_requested.connect(signals_received.append)

        # Clicking should not emit (no shot)
        bar._on_button_clicked("3de")
        process_qt_events()

        assert len(signals_received) == 0

    def test_different_buttons_emit_correct_app_names(self, qtbot: QtBot) -> None:
        """Each button emits its correct app name."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)
        bar.set_shot(MagicMock())

        for app_name in ["3de", "nuke", "maya", "rv"]:
            with qtbot.waitSignal(bar.launch_requested, timeout=1000) as blocker:
                qtbot.mouseClick(bar._buttons[app_name], Qt.MouseButton.LeftButton)
                process_qt_events()

            assert blocker.args == [app_name]


class TestQuickLaunchBarVersionInfo:
    """Tests for version info in tooltips."""

    def test_set_latest_version_updates_tooltip(self, qtbot: QtBot) -> None:
        """Setting version info updates button tooltip."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)

        bar.set_latest_version("3de", "v005")

        tooltip = bar._buttons["3de"].toolTip()
        assert "v005" in tooltip

    def test_clear_version_info(self, qtbot: QtBot) -> None:
        """Version info can be cleared."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)

        bar.set_latest_version("3de", "v005")
        bar.set_latest_version("3de", None)

        # Should still have tooltip but without version
        tooltip = bar._buttons["3de"].toolTip()
        assert "v005" not in tooltip

    def test_clear_all_versions(self, qtbot: QtBot) -> None:
        """All version info can be cleared at once."""
        bar = QuickLaunchBar()
        qtbot.addWidget(bar)

        bar.set_latest_version("3de", "v005")
        bar.set_latest_version("nuke", "v012")

        bar.clear_latest_versions()

        assert "v005" not in bar._buttons["3de"].toolTip()
        assert "v012" not in bar._buttons["nuke"].toolTip()
