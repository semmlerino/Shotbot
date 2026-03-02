"""Unit tests for controllers/filter_coordinator.py.

Tests for FilterCoordinator which manages filter logic across My Shots
and Previous Shots tabs, extracted from MainWindow.

Following UNIFIED_TESTING_V2.md best practices:
- Test behavior using protocol-based test doubles
- Cover show/text filter handlers and status bar updates
- Cover previous-shots signal wiring
"""

from __future__ import annotations

from typing import Any

import pytest

from controllers.filter_coordinator import FilterCoordinator
from tests.fixtures.test_doubles import SignalDouble


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
]


# ============================================================================
# Test Doubles
# ============================================================================


class FilterableItemModelDouble:
    """Test double for FilterableItemModel protocol."""

    __test__ = False

    def __init__(self, row_count: int = 0) -> None:
        self._row_count = row_count
        self._show_filter: str | None = None
        self._set_show_filter_calls: list[tuple[Any, str | None]] = []
        self._shots: list[Any] = []

    def set_show_filter(self, model: Any, show_filter: str | None) -> None:
        self._show_filter = show_filter
        self._set_show_filter_calls.append((model, show_filter))

    def rowCount(self) -> int:
        return self._row_count

    def set_shots(self, shots: list[Any]) -> None:
        self._shots = shots
        self._row_count = len(shots)


class ShotModelDouble:
    """Test double for ShotModel / BaseShotModel."""

    __test__ = False

    def __init__(self, shots: list[Any] | None = None) -> None:
        self.shots: list[Any] = shots or []
        self._text_filter: str | None = None
        self._show_filter: str | None = None

    def set_text_filter(self, text: str | None) -> None:
        self._text_filter = text

    def set_show_filter(self, show: str | None) -> None:
        self._show_filter = show

    def get_filtered_shots(self) -> list[Any]:
        if not self._text_filter:
            return list(self.shots)
        return [s for s in self.shots if self._text_filter in str(s)]

    def get_text_filter(self) -> str | None:
        return self._text_filter

    def get_show_filter(self) -> str | None:
        return self._show_filter


class PreviousShotsModelDouble:
    """Test double for PreviousShotsModel."""

    __test__ = False

    def __init__(self, shots: list[Any] | None = None) -> None:
        self._shots: list[Any] = shots or []
        self._text_filter: str | None = None

    def set_text_filter(self, text: str | None) -> None:
        self._text_filter = text

    def get_filtered_shots(self) -> list[Any]:
        if not self._text_filter:
            return list(self._shots)
        return [s for s in self._shots if self._text_filter in str(s)]

    def get_shots(self) -> list[Any]:
        return list(self._shots)


class StatusBarDouble:
    """Test double for QStatusBar."""

    __test__ = False

    def __init__(self) -> None:
        self._last_message: str = ""
        self._last_timeout: int = 0

    def showMessage(self, message: str, timeout: int = 0) -> None:
        self._last_message = message
        self._last_timeout = timeout


class GridViewDouble:
    """Test double for ShotGridView."""

    __test__ = False

    def __init__(self) -> None:
        self.show_filter_requested = SignalDouble()
        self.text_filter_requested = SignalDouble()
        self._show_filter_populated = False
        self._populate_show_filter_model: Any = None

    def populate_show_filter(self, model: Any) -> None:
        self._show_filter_populated = True
        self._populate_show_filter_model = model


class PreviousShotsItemModelDouble(FilterableItemModelDouble):
    """Test double for PreviousShotsItemModel with shots_updated signal."""

    __test__ = False

    def __init__(self, row_count: int = 0) -> None:
        super().__init__(row_count)
        self.shots_updated = SignalDouble()


class FilterTargetDouble:
    """Test double implementing FilterTarget protocol."""

    __test__ = False

    def __init__(self) -> None:
        self.shot_grid = GridViewDouble()
        self.previous_shots_grid = GridViewDouble()

        self.shot_model = ShotModelDouble()
        self.previous_shots_model = PreviousShotsModelDouble()

        self.shot_item_model = FilterableItemModelDouble()
        self.previous_shots_item_model = PreviousShotsItemModelDouble()

        self.status_bar = StatusBarDouble()


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def window() -> FilterTargetDouble:
    """Create a FilterTarget test double."""
    return FilterTargetDouble()


@pytest.fixture
def coordinator(window: FilterTargetDouble) -> FilterCoordinator:
    """Create a FilterCoordinator with test double."""
    return FilterCoordinator(window)  # type: ignore[arg-type]


# ============================================================================
# Test Initialization
# ============================================================================


class TestFilterCoordinatorInit:
    """Test FilterCoordinator initialization."""

    def test_init_stores_window_reference(self, window: FilterTargetDouble) -> None:
        """Coordinator holds a reference to the window double."""
        coordinator = FilterCoordinator(window)  # type: ignore[arg-type]
        assert coordinator.window is window

    def test_setup_signals_connects_shot_grid(
        self, window: FilterTargetDouble
    ) -> None:
        """Constructor connects shot_grid filter signals."""
        FilterCoordinator(window)  # type: ignore[arg-type]
        assert len(window.shot_grid.show_filter_requested.callbacks) == 1
        assert len(window.shot_grid.text_filter_requested.callbacks) == 1

    def test_setup_signals_connects_previous_shots_grid(
        self, window: FilterTargetDouble
    ) -> None:
        """Constructor connects previous_shots_grid filter signals."""
        FilterCoordinator(window)  # type: ignore[arg-type]
        assert len(window.previous_shots_grid.show_filter_requested.callbacks) == 1
        assert len(window.previous_shots_grid.text_filter_requested.callbacks) == 1

    def test_setup_signals_connects_shots_updated(
        self, window: FilterTargetDouble
    ) -> None:
        """Constructor connects previous_shots_item_model.shots_updated signal."""
        FilterCoordinator(window)  # type: ignore[arg-type]
        assert len(window.previous_shots_item_model.shots_updated.callbacks) == 1


# ============================================================================
# Test _apply_show_filter
# ============================================================================


class TestApplyShowFilter:
    """Test the _apply_show_filter helper."""

    def test_apply_show_filter_calls_set_show_filter_with_show(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """_apply_show_filter passes the show name to set_show_filter."""
        coordinator._apply_show_filter(
            window.shot_item_model, window.shot_model, "myshow", "My Shots"
        )
        assert window.shot_item_model._show_filter == "myshow"

    def test_apply_show_filter_converts_empty_string_to_none(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """_apply_show_filter converts empty string to None (all shows)."""
        coordinator._apply_show_filter(
            window.shot_item_model, window.shot_model, "", "My Shots"
        )
        assert window.shot_item_model._show_filter is None

    def test_apply_show_filter_shows_status_message(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """_apply_show_filter shows a non-empty status bar message."""
        coordinator._apply_show_filter(
            window.shot_item_model, window.shot_model, "myshow", "My Shots"
        )
        assert window.status_bar._last_message != ""
        assert window.status_bar._last_timeout > 0

    def test_apply_show_filter_status_contains_tab_name(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Status message contains the tab name."""
        coordinator._apply_show_filter(
            window.shot_item_model, window.shot_model, "myshow", "My Shots"
        )
        assert "My Shots" in window.status_bar._last_message

    def test_apply_show_filter_status_describes_all_shows_for_empty(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Status message uses 'All Shows' when show is empty string."""
        coordinator._apply_show_filter(
            window.shot_item_model, window.shot_model, "", "My Shots"
        )
        assert "All Shows" in window.status_bar._last_message


# ============================================================================
# Test _on_shot_show_filter_requested
# ============================================================================


class TestShotShowFilter:
    """Test _on_shot_show_filter_requested."""

    def test_show_name_applies_filter_to_shot_item_model(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Non-empty show name applies filter to shot_item_model."""
        coordinator._on_shot_show_filter_requested("show1")
        assert window.shot_item_model._show_filter == "show1"

    def test_empty_string_clears_filter(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Empty string clears the show filter (sets None)."""
        coordinator._on_shot_show_filter_requested("show1")
        coordinator._on_shot_show_filter_requested("")
        assert window.shot_item_model._show_filter is None

    def test_show_filter_updates_status_bar(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Handler updates the status bar."""
        coordinator._on_shot_show_filter_requested("show1")
        assert "My Shots" in window.status_bar._last_message

    def test_signal_emission_triggers_handler(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """show_filter_requested signal emission triggers the handler."""
        window.shot_grid.show_filter_requested.emit("show_from_signal")
        assert window.shot_item_model._show_filter == "show_from_signal"


# ============================================================================
# Test _on_shot_text_filter_requested
# ============================================================================


class TestShotTextFilter:
    """Test _on_shot_text_filter_requested."""

    def test_text_filter_sets_filter_on_shot_model(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Non-empty text sets text filter on shot_model."""
        window.shot_model.shots = ["shot_abc", "shot_xyz"]
        coordinator._on_shot_text_filter_requested("abc")
        assert window.shot_model._text_filter == "abc"

    def test_text_filter_updates_shot_item_model_shots(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Handler updates shot_item_model with filtered shots."""
        window.shot_model.shots = ["shot_abc", "shot_xyz"]
        coordinator._on_shot_text_filter_requested("abc")
        assert window.shot_item_model._shots == ["shot_abc"]

    def test_empty_text_clears_filter(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Empty string clears the text filter."""
        window.shot_model.shots = ["shot_abc", "shot_xyz"]
        coordinator._on_shot_text_filter_requested("abc")
        coordinator._on_shot_text_filter_requested("")
        assert window.shot_model._text_filter is None

    def test_empty_text_restores_all_shots(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Clearing text filter restores all shots in item model."""
        window.shot_model.shots = ["shot_abc", "shot_xyz"]
        coordinator._on_shot_text_filter_requested("abc")
        coordinator._on_shot_text_filter_requested("")
        assert len(window.shot_item_model._shots) == 2

    def test_text_filter_shows_status_with_filter_info(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Status bar shows filter text when filter is active."""
        window.shot_model.shots = ["shot_abc"]
        coordinator._on_shot_text_filter_requested("abc")
        assert "abc" in window.status_bar._last_message

    def test_clear_text_filter_shows_total_count(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Status bar shows total shot count when filter is cleared."""
        window.shot_model.shots = ["shot_abc", "shot_xyz"]
        coordinator._on_shot_text_filter_requested("")
        assert "My Shots" in window.status_bar._last_message

    def test_signal_emission_triggers_handler(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """text_filter_requested signal emission triggers the handler."""
        window.shot_model.shots = ["shot_abc", "shot_xyz"]
        window.shot_grid.text_filter_requested.emit("abc")
        assert window.shot_model._text_filter == "abc"


# ============================================================================
# Test _on_previous_show_filter_requested
# ============================================================================


class TestPreviousShowFilter:
    """Test _on_previous_show_filter_requested."""

    def test_show_name_applies_filter_to_previous_item_model(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Non-empty show name applies filter to previous_shots_item_model."""
        coordinator._on_previous_show_filter_requested("showA")
        assert window.previous_shots_item_model._show_filter == "showA"

    def test_empty_string_clears_filter(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Empty string clears the show filter."""
        coordinator._on_previous_show_filter_requested("showA")
        coordinator._on_previous_show_filter_requested("")
        assert window.previous_shots_item_model._show_filter is None

    def test_show_filter_updates_status_bar(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Handler updates the status bar with Previous Shots tab name."""
        coordinator._on_previous_show_filter_requested("showA")
        assert "Previous Shots" in window.status_bar._last_message

    def test_signal_emission_triggers_handler(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """show_filter_requested signal on previous_shots_grid triggers handler."""
        window.previous_shots_grid.show_filter_requested.emit("showB")
        assert window.previous_shots_item_model._show_filter == "showB"


# ============================================================================
# Test _on_previous_text_filter_requested
# ============================================================================


class TestPreviousTextFilter:
    """Test _on_previous_text_filter_requested."""

    def test_text_filter_sets_filter_on_previous_shots_model(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Non-empty text sets text filter on previous_shots_model."""
        window.previous_shots_model._shots = ["shot_abc", "shot_xyz"]
        coordinator._on_previous_text_filter_requested("abc")
        assert window.previous_shots_model._text_filter == "abc"

    def test_text_filter_updates_previous_item_model_shots(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Handler updates previous_shots_item_model with filtered shots."""
        window.previous_shots_model._shots = ["shot_abc", "shot_xyz"]
        coordinator._on_previous_text_filter_requested("abc")
        assert window.previous_shots_item_model._shots == ["shot_abc"]

    def test_empty_text_clears_filter(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Empty string clears the text filter."""
        window.previous_shots_model._shots = ["shot_abc", "shot_xyz"]
        coordinator._on_previous_text_filter_requested("abc")
        coordinator._on_previous_text_filter_requested("")
        assert window.previous_shots_model._text_filter is None

    def test_empty_text_restores_all_shots(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Clearing text filter restores all shots in item model."""
        window.previous_shots_model._shots = ["shot_abc", "shot_xyz"]
        coordinator._on_previous_text_filter_requested("abc")
        coordinator._on_previous_text_filter_requested("")
        assert len(window.previous_shots_item_model._shots) == 2

    def test_text_filter_shows_status_with_filter_info(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """Status bar shows filter text when filter is active."""
        window.previous_shots_model._shots = ["shot_abc"]
        coordinator._on_previous_text_filter_requested("abc")
        assert "abc" in window.status_bar._last_message

    def test_signal_emission_triggers_handler(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """text_filter_requested signal on previous_shots_grid triggers handler."""
        window.previous_shots_model._shots = ["shot_abc", "shot_xyz"]
        window.previous_shots_grid.text_filter_requested.emit("xyz")
        assert window.previous_shots_model._text_filter == "xyz"


# ============================================================================
# Test _on_previous_shots_updated
# ============================================================================


class TestPreviousShotsUpdated:
    """Test _on_previous_shots_updated."""

    def test_shots_updated_calls_populate_show_filter(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """shots_updated signal triggers populate_show_filter on previous grid."""
        coordinator._on_previous_shots_updated()
        assert window.previous_shots_grid._show_filter_populated is True

    def test_shots_updated_passes_previous_shots_model(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """populate_show_filter receives the previous_shots_model."""
        coordinator._on_previous_shots_updated()
        assert window.previous_shots_grid._populate_show_filter_model is window.previous_shots_model

    def test_signal_emission_triggers_handler(
        self, coordinator: FilterCoordinator, window: FilterTargetDouble
    ) -> None:
        """shots_updated signal emission triggers handler via signal wiring."""
        window.previous_shots_item_model.shots_updated.emit()
        assert window.previous_shots_grid._show_filter_populated is True
