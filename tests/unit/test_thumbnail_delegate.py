"""Unit tests for BaseThumbnailDelegate - targeted repaint optimization.

This test verifies that the loading animation only repaints items that are
actively loading, not the entire view. This is critical for performance with
large shot grids (20-30+ items).

Following UNIFIED_TESTING_GUIDE best practices:
- Test behavior, not implementation
- Use real components (ShotItemModel with shots)
- Verify targeted repaints using signal spy
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QListView

from base_thumbnail_delegate import BaseThumbnailDelegate, DelegateTheme
from shot_item_model import ShotItemModel
from shot_model import Shot


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.fast,
]


class ConcreteThumbnailDelegate(BaseThumbnailDelegate):
    """Concrete implementation for testing (not a test class itself)."""

    def get_theme(self) -> DelegateTheme:
        """Get default theme."""
        return DelegateTheme()

    def get_item_data(self, index):
        """Extract item data from index."""
        item = index.data(Qt.ItemDataRole.UserRole + 1)  # ObjectRole
        if not item:
            return {"name": "Unknown"}

        return {
            "name": item.full_name,
            "show": item.show,
            "sequence": item.sequence,
            "thumbnail": index.data(Qt.ItemDataRole.DecorationRole),
            "loading_state": index.data(Qt.ItemDataRole.UserRole + 9),  # LoadingStateRole
            "is_selected": False,
        }


def create_mock_shot(index: int) -> Shot:
    """Create a mock shot for testing."""
    return Shot(
        show="test_show",
        sequence="seq01",
        shot=f"shot_{index:04d}",
        workspace_path=f"/tmp/test/shot_{index:04d}",
    )


class TestLoadingAnimationTargetedRepaint:
    """Test that loading animation only repaints loading items."""

    def test_loading_animation_targeted_repaint(self, qtbot: QtBot) -> None:
        """Test loading animation only repaints loading items, not entire view.

        This test verifies the critical optimization:
        - Before: parent.update() repaints all 30 items (600 paint calls over 30s)
        - After: dataChanged.emit() repaints only 2 loading items (40 paint calls)
        - Result: 15x reduction in paint calls (93% waste eliminated)
        """
        # Create view and model first
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        # Create delegate with view as parent (critical for parent() to work)
        delegate = ConcreteThumbnailDelegate(parent=view)
        view.setItemDelegate(delegate)

        # Add 30 shots to simulate realistic grid
        shots = [create_mock_shot(i) for i in range(30)]
        model.set_items(shots)

        # Mark 2 items as loading (typical scenario)
        model._loading_states["seq01_shot_0000"] = "loading"
        model._loading_states["seq01_shot_0001"] = "loading"

        # Spy on dataChanged signal to track repaints
        spy = QSignalSpy(model.dataChanged)

        # Trigger one animation update (happens 20x/second during loading)
        delegate._update_loading_animation()

        # Verify: Should emit exactly 2 signals (one per loading item)
        assert spy.count() == 2, f"Expected 2 dataChanged signals, got {spy.count()}"

        # Verify: Each signal should target a single item (not range)
        for i in range(spy.count()):
            signal_args = spy.at(i)
            top_left = signal_args[0]
            bottom_right = signal_args[1]
            # Verify it's a single item (top_left == bottom_right)
            assert top_left.row() == bottom_right.row(), (
                f"Expected single-item repaint, got range "
                f"{top_left.row()}-{bottom_right.row()}"
            )

        # Verify: Repaints should be for loading items only
        repainted_rows = {spy.at(i)[0].row() for i in range(spy.count())}
        assert repainted_rows == {0, 1}, (
            f"Expected rows {{0, 1}} to be repainted, got {repainted_rows}"
        )

    def test_loading_animation_no_loading_items(self, qtbot: QtBot) -> None:
        """Test that animation does nothing when no items are loading."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        delegate = ConcreteThumbnailDelegate(parent=view)
        view.setItemDelegate(delegate)

        # Add shots but don't mark any as loading
        shots = [create_mock_shot(i) for i in range(10)]
        model.set_items(shots)

        # Spy on dataChanged
        spy = QSignalSpy(model.dataChanged)

        # Trigger animation
        delegate._update_loading_animation()

        # Should emit no signals (no items loading)
        assert spy.count() == 0, f"Expected 0 signals for no loading items, got {spy.count()}"

    def test_loading_animation_all_items_loading(self, qtbot: QtBot) -> None:
        """Test animation when all items are loading (worst case)."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        delegate = ConcreteThumbnailDelegate(parent=view)
        view.setItemDelegate(delegate)

        # Add 5 shots
        shots = [create_mock_shot(i) for i in range(5)]
        model.set_items(shots)

        # Mark ALL as loading
        for shot in shots:
            model._loading_states[shot.full_name] = "loading"

        # Spy on dataChanged
        spy = QSignalSpy(model.dataChanged)

        # Trigger animation
        delegate._update_loading_animation()

        # Should emit 5 signals (one per item)
        assert spy.count() == 5, f"Expected 5 signals for 5 loading items, got {spy.count()}"

        # Verify all rows repainted
        repainted_rows = {spy.at(i)[0].row() for i in range(spy.count())}
        assert repainted_rows == {0, 1, 2, 3, 4}

    def test_get_loading_rows_identifies_correct_items(self, qtbot: QtBot) -> None:
        """Test that _get_loading_rows correctly identifies loading items."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        delegate = ConcreteThumbnailDelegate(parent=view)
        view.setItemDelegate(delegate)

        # Add shots
        shots = [create_mock_shot(i) for i in range(10)]
        model.set_items(shots)

        # Mark specific items as loading
        model._loading_states["seq01_shot_0002"] = "loading"
        model._loading_states["seq01_shot_0005"] = "loading"
        model._loading_states["seq01_shot_0007"] = "loading"

        # Get loading rows
        loading_rows = delegate._get_loading_rows()

        # Should return rows 2, 5, 7
        assert set(loading_rows) == {2, 5, 7}, (
            f"Expected rows {{2, 5, 7}}, got {set(loading_rows)}"
        )

    def test_animation_angle_updates(self, qtbot: QtBot) -> None:
        """Test that animation angle increments correctly."""
        view = QListView()
        model = ShotItemModel()
        view.setModel(model)
        qtbot.addWidget(view)

        # Create delegate with view as parent
        delegate = ConcreteThumbnailDelegate(parent=view)
        view.setItemDelegate(delegate)

        # Initial angle
        initial_angle = delegate._loading_angle

        # Update animation (no items, so no repaints but angle should update)
        delegate._update_loading_animation()

        # Angle should increment by 10
        assert delegate._loading_angle == (initial_angle + 10) % 360

        # Update 36 times (full rotation)
        for _ in range(35):
            delegate._update_loading_animation()

        # Should be back to initial angle (modulo 360)
        assert delegate._loading_angle == initial_angle
