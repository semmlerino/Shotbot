"""Unit tests for controllers/thumbnail_size_manager.py.

Tests for ThumbnailSizeManager which manages thumbnail size synchronization
across My Shots, 3DE Scenes, and Previous Shots tabs.

Following UNIFIED_TESTING_V2.md best practices:
- Test behavior using protocol-based test doubles
- Cover sync, increase/decrease size, and per-tab slider dispatch
"""

from __future__ import annotations

from typing import Any

import pytest

from config import Config
from controllers.thumbnail_size_manager import ThumbnailSizeManager


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# ============================================================================
# Test Doubles
# ============================================================================


class SliderDouble:
    """Test double for QSlider with blockSignals support."""

    __test__ = False

    def __init__(self, initial_value: int = Config.Thumbnail.DEFAULT_SIZE) -> None:
        self._value = initial_value
        self._signals_blocked = False
        # Track calls for assertion
        self.block_signals_calls: list[bool] = []

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        self._value = value

    def blockSignals(self, block: bool) -> bool:
        previous = self._signals_blocked
        self._signals_blocked = block
        self.block_signals_calls.append(block)
        return previous


class LabelDouble:
    """Test double for QLabel."""

    __test__ = False

    def __init__(self) -> None:
        self._text = ""

    def setText(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class SignalConnectorDouble:
    """Test double for a Qt signal (valueChanged) supporting .connect()."""

    __test__ = False

    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def connect(self, callback: Any) -> None:
        self.callbacks.append(callback)


class GridWithSizeDouble:
    """Test double for a grid view with size_slider and size_label."""

    __test__ = False

    def __init__(self, initial_value: int = Config.Thumbnail.DEFAULT_SIZE) -> None:
        self.size_slider = SliderDouble(initial_value)
        self.size_label = LabelDouble()
        # Expose a valueChanged-compatible attribute so _setup_signals can connect
        self.size_slider.valueChanged = SignalConnectorDouble()  # type: ignore[attr-defined]


class TabWidgetDouble:
    """Test double for QTabWidget."""

    __test__ = False

    def __init__(self, current_index: int = 0) -> None:
        self._current_index = current_index

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        self._current_index = index


class ThumbnailSizeTargetDouble:
    """Test double implementing ThumbnailSizeTarget protocol."""

    __test__ = False

    def __init__(self, tab_index: int = 0) -> None:
        self.shot_grid = GridWithSizeDouble()
        self.threede_shot_grid = GridWithSizeDouble()
        self.previous_shots_grid = GridWithSizeDouble()
        self.tab_widget = TabWidgetDouble(tab_index)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def window() -> ThumbnailSizeTargetDouble:
    """Create a ThumbnailSizeTarget test double (tab 0 active)."""
    return ThumbnailSizeTargetDouble(tab_index=0)


@pytest.fixture
def manager(window: ThumbnailSizeTargetDouble) -> ThumbnailSizeManager:
    """Create a ThumbnailSizeManager with test double."""
    return ThumbnailSizeManager(window)  # type: ignore[arg-type]


# ============================================================================
# Test Initialization
# ============================================================================


class TestThumbnailSizeManagerInit:
    """Test ThumbnailSizeManager initialization."""

    def test_setup_signals_connects_all_sliders(
        self, window: ThumbnailSizeTargetDouble
    ) -> None:
        """Constructor connects valueChanged on all three sliders."""
        ThumbnailSizeManager(window)  # type: ignore[arg-type]
        assert len(window.shot_grid.size_slider.valueChanged.callbacks) == 1  # type: ignore[attr-defined]
        assert len(window.threede_shot_grid.size_slider.valueChanged.callbacks) == 1  # type: ignore[attr-defined]
        assert len(window.previous_shots_grid.size_slider.valueChanged.callbacks) == 1  # type: ignore[attr-defined]


# ============================================================================
# Test sync_thumbnail_sizes
# ============================================================================


class TestSyncThumbnailSizes:
    """Test sync_thumbnail_sizes method."""

    def test_sync_sets_value_on_all_sliders(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """sync_thumbnail_sizes sets the value on all three sliders."""
        manager.sync_thumbnail_sizes(600)

        assert window.shot_grid.size_slider._value == 600
        assert window.threede_shot_grid.size_slider._value == 600
        assert window.previous_shots_grid.size_slider._value == 600

    def test_sync_updates_all_size_labels(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """sync_thumbnail_sizes updates the size_label text on all three grids."""
        manager.sync_thumbnail_sizes(700)

        assert window.shot_grid.size_label._text == "700px"
        assert window.threede_shot_grid.size_label._text == "700px"
        assert window.previous_shots_grid.size_label._text == "700px"

    def test_sync_blocks_signals_during_update(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """sync_thumbnail_sizes blocks signals to prevent recursion."""
        manager.sync_thumbnail_sizes(500)

        # blockSignals(True) must have been called at least once per slider
        assert True in window.shot_grid.size_slider.block_signals_calls
        assert True in window.threede_shot_grid.size_slider.block_signals_calls
        assert True in window.previous_shots_grid.size_slider.block_signals_calls

    def test_sync_restores_signal_state_after_update(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """Signals are unblocked after sync completes (finally clause)."""
        manager.sync_thumbnail_sizes(500)

        assert window.shot_grid.size_slider._signals_blocked is False
        assert window.threede_shot_grid.size_slider._signals_blocked is False
        assert window.previous_shots_grid.size_slider._signals_blocked is False

    def test_sync_min_value(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """sync_thumbnail_sizes works at the minimum allowed size."""
        manager.sync_thumbnail_sizes(Config.Thumbnail.MIN_SIZE)

        assert window.shot_grid.size_slider._value == Config.Thumbnail.MIN_SIZE
        assert window.shot_grid.size_label._text == f"{Config.Thumbnail.MIN_SIZE}px"

    def test_sync_max_value(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """sync_thumbnail_sizes works at the maximum allowed size."""
        manager.sync_thumbnail_sizes(Config.Thumbnail.MAX_SIZE)

        assert window.shot_grid.size_slider._value == Config.Thumbnail.MAX_SIZE
        assert window.shot_grid.size_label._text == f"{Config.Thumbnail.MAX_SIZE}px"


# ============================================================================
# Test increase_size
# ============================================================================


class TestIncreaseSize:
    """Test increase_size method."""

    def test_increase_size_by_20_on_tab0(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """increase_size increments slider value by 20 on tab 0 (My Shots)."""
        window.tab_widget.setCurrentIndex(0)
        window.shot_grid.size_slider._value = 500

        manager.increase_size()

        assert window.shot_grid.size_slider._value == 520

    def test_increase_size_by_20_on_tab1(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """increase_size increments slider value by 20 on tab 1 (3DE)."""
        window.tab_widget.setCurrentIndex(1)
        window.threede_shot_grid.size_slider._value = 500

        manager.increase_size()

        assert window.threede_shot_grid.size_slider._value == 520

    def test_increase_size_by_20_on_tab2(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """increase_size increments slider value by 20 on tab 2 (Previous Shots)."""
        window.tab_widget.setCurrentIndex(2)
        window.previous_shots_grid.size_slider._value = 500

        manager.increase_size()

        assert window.previous_shots_grid.size_slider._value == 520

    def test_increase_size_caps_at_max(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """increase_size does not exceed MAX_THUMBNAIL_SIZE."""
        window.tab_widget.setCurrentIndex(0)
        window.shot_grid.size_slider._value = Config.Thumbnail.MAX_SIZE

        manager.increase_size()

        assert window.shot_grid.size_slider._value == Config.Thumbnail.MAX_SIZE

    def test_increase_size_caps_when_close_to_max(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """increase_size caps at MAX even when adding 20 would overshoot."""
        window.tab_widget.setCurrentIndex(0)
        window.shot_grid.size_slider._value = Config.Thumbnail.MAX_SIZE - 10

        manager.increase_size()

        assert window.shot_grid.size_slider._value == Config.Thumbnail.MAX_SIZE

    def test_increase_size_dispatches_to_active_tab_slider_only(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """increase_size only sets the slider for the active tab."""
        window.tab_widget.setCurrentIndex(0)
        window.shot_grid.size_slider._value = 500
        initial_3de = window.threede_shot_grid.size_slider._value
        initial_prev = window.previous_shots_grid.size_slider._value

        manager.increase_size()

        # Active tab slider changed
        assert window.shot_grid.size_slider._value == 520
        # Other sliders unchanged by increase_size itself
        assert window.threede_shot_grid.size_slider._value == initial_3de
        assert window.previous_shots_grid.size_slider._value == initial_prev


# ============================================================================
# Test decrease_size
# ============================================================================


class TestDecreaseSize:
    """Test decrease_size method."""

    def test_decrease_size_by_20_on_tab0(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """decrease_size decrements slider value by 20 on tab 0 (My Shots)."""
        window.tab_widget.setCurrentIndex(0)
        window.shot_grid.size_slider._value = 600

        manager.decrease_size()

        assert window.shot_grid.size_slider._value == 580

    def test_decrease_size_by_20_on_tab1(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """decrease_size decrements slider value by 20 on tab 1 (3DE)."""
        window.tab_widget.setCurrentIndex(1)
        window.threede_shot_grid.size_slider._value = 600

        manager.decrease_size()

        assert window.threede_shot_grid.size_slider._value == 580

    def test_decrease_size_by_20_on_tab2(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """decrease_size decrements slider value by 20 on tab 2 (Previous Shots)."""
        window.tab_widget.setCurrentIndex(2)
        window.previous_shots_grid.size_slider._value = 600

        manager.decrease_size()

        assert window.previous_shots_grid.size_slider._value == 580

    def test_decrease_size_floors_at_min(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """decrease_size does not go below MIN_THUMBNAIL_SIZE."""
        window.tab_widget.setCurrentIndex(0)
        window.shot_grid.size_slider._value = Config.Thumbnail.MIN_SIZE

        manager.decrease_size()

        assert window.shot_grid.size_slider._value == Config.Thumbnail.MIN_SIZE

    def test_decrease_size_floors_when_close_to_min(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """decrease_size floors at MIN even when subtracting 20 would undershoot."""
        window.tab_widget.setCurrentIndex(0)
        window.shot_grid.size_slider._value = Config.Thumbnail.MIN_SIZE + 10

        manager.decrease_size()

        assert window.shot_grid.size_slider._value == Config.Thumbnail.MIN_SIZE

    def test_decrease_size_dispatches_to_active_tab_slider_only(
        self, manager: ThumbnailSizeManager, window: ThumbnailSizeTargetDouble
    ) -> None:
        """decrease_size only sets the slider for the active tab."""
        window.tab_widget.setCurrentIndex(2)
        window.previous_shots_grid.size_slider._value = 600
        initial_shot = window.shot_grid.size_slider._value
        initial_3de = window.threede_shot_grid.size_slider._value

        manager.decrease_size()

        assert window.previous_shots_grid.size_slider._value == 580
        assert window.shot_grid.size_slider._value == initial_shot
        assert window.threede_shot_grid.size_slider._value == initial_3de
