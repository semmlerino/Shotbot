"""Unit tests for PreviousShotsItemModel with thread safety focus.

Tests the thread safety improvements and resource management
in the PreviousShotsItemModel class.
"""

# Standard library imports

# Third-party imports
import pytest
from PySide6.QtCore import Qt

from config import Config

# Local application imports
from previous_shots.item_model import PreviousShotsItemModel

# Following UNIFIED_TESTING_GUIDE: Use test doubles instead of Mock(spec=)
from tests.fixtures.test_doubles import SignalDouble, TestCacheManager
from type_definitions import Shot


pytestmark = [pytest.mark.unit, pytest.mark.qt]


class MockPreviousShotsModel:
    """Test double for PreviousShotsModel following UNIFIED_TESTING_GUIDE."""

    def __init__(self) -> None:
        self.shots_updated = SignalDouble()
        self.scan_started = SignalDouble()
        self.scan_finished = SignalDouble()
        self.scan_progress = SignalDouble()
        self._shots = []

    def get_shots(self):
        """Return test shots."""
        return self._shots

    def add_shot(self, shot) -> None:
        """Add a test shot."""
        self._shots.append(shot)
        self.shots_updated.emit()


@pytest.fixture
def model(qtbot, tmp_path):
    """Create a PreviousShotsItemModel instance for testing."""
    # Use test doubles instead of Mock(spec=)
    cache_manager = TestCacheManager(cache_dir=tmp_path / "cache")
    previous_shots_model = MockPreviousShotsModel()

    # Create the item model with required arguments
    model = PreviousShotsItemModel(previous_shots_model, cache_manager)
    yield model
    # Manual cleanup for QObject (not a widget)
    model.deleteLater()


@pytest.fixture
def test_shots(tmp_path, monkeypatch):
    """Create test Shot objects for previous/approved shots."""
    # Isolate Config.SHOWS_ROOT to tmp_path per UNIFIED_TESTING_V2.md section 2
    monkeypatch.setattr("config.Config.SHOWS_ROOT", str(tmp_path))

    return [
        Shot(
            show="proj1",
            sequence="010",
            shot="0010",
            workspace_path=f"{Config.SHOWS_ROOT}/proj1/shots/010/010_0010",
        ),
        Shot(
            show="proj2",
            sequence="020",
            shot="0020",
            workspace_path=f"{Config.SHOWS_ROOT}/proj2/shots/020/020_0020",
        ),
        Shot(
            show="proj3",
            sequence="030",
            shot="0030",
            workspace_path=f"{Config.SHOWS_ROOT}/proj3/shots/030/030_0030",
        ),
    ]


class TestPreviousShotsThreadSafety:
    """Test thread safety in PreviousShotsItemModel."""

    def test_concurrent_rowcount_and_data_access(self, model, test_shots) -> None:
        """rowCount() and data() remain consistent under concurrent read access."""
        import concurrent.futures

        model._underlying_model._shots = test_shots
        model._update_from_underlying_model()

        errors: list[Exception] = []

        def read_model() -> None:
            try:
                for _ in range(20):
                    count = model.rowCount()
                    assert count == len(test_shots)
                    if count > 0:
                        index = model.index(0, 0)
                        data = model.data(index, Qt.ItemDataRole.DisplayRole)
                        assert data == test_shots[0].full_name
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(read_model) for _ in range(4)]
            concurrent.futures.wait(futures, timeout=5.0)

        assert errors == [], f"Concurrent access raised: {errors}"
        assert model.rowCount() == len(test_shots)

    def test_data_roles_thread_safety(self, model, test_shots) -> None:
        """Test data() method with various roles."""
        # Local application imports
        from ui.base_item_model import (
            BaseItemRole as UnifiedRole,
        )

        # Update the underlying model's shots
        model._underlying_model._shots = test_shots
        # Manually trigger update
        model._update_from_underlying_model()

        index = model.index(0, 0)
        shot = test_shots[0]

        # Test all custom roles
        roles = [
            Qt.ItemDataRole.DisplayRole,
            UnifiedRole.ObjectRole,  # Shot object
            UnifiedRole.FullNameRole,  # Full name
            UnifiedRole.ShowRole,  # Show
            UnifiedRole.SequenceRole,  # Sequence
            UnifiedRole.ItemSpecificRole1,  # Shot number (shot.shot)
        ]

        for role in roles:
            data = model.data(index, role)
            # Should not crash or raise exceptions
            if role == Qt.ItemDataRole.DisplayRole:
                assert (
                    data == shot.full_name
                )  # PreviousShotsItemModel returns full_name for DisplayRole
            elif role == UnifiedRole.ObjectRole:
                assert data == shot
            elif role == UnifiedRole.FullNameRole:
                assert data == shot.full_name
            elif role == UnifiedRole.ShowRole:
                assert data == shot.show
            elif role == UnifiedRole.SequenceRole:
                assert data == shot.sequence
            elif role == UnifiedRole.ItemSpecificRole1:
                assert data == shot.shot

    def test_rapid_scene_changes(self, model, test_shots, qtbot) -> None:
        """Test rapid shot list changes."""
        # Rapidly change shots
        for _ in range(10):
            # Update the underlying model's shots
            model._underlying_model._shots = test_shots
            # Manually trigger update
            model._update_from_underlying_model()

            # Update the underlying model's shots to empty list
            model._underlying_model._shots = []
            # Manually trigger update
            model._update_from_underlying_model()

            model._underlying_model._shots = test_shots[:1]
            model._update_from_underlying_model()

            # Update the underlying model's shots
            model._underlying_model._shots = test_shots
            # Manually trigger update
            model._update_from_underlying_model()

        # Final state should be consistent
        assert model.rowCount() == len(test_shots)
        assert len(model.shots) == len(test_shots)


class TestDataConsistency:
    """Test data consistency with thread-safe operations."""

    def test_shot_data_integrity(self, model, test_shots) -> None:
        """Test that shot data remains consistent."""
        # Local application imports
        from ui.base_item_model import (
            BaseItemRole as UnifiedRole,
        )

        # Update the underlying model's shots
        model._underlying_model._shots = test_shots
        # Manually trigger update
        model._update_from_underlying_model()

        for i, shot in enumerate(test_shots):
            index = model.index(i, 0)

            # Verify data integrity using correct UnifiedRole values
            assert model.data(index, UnifiedRole.ObjectRole) == shot
            assert model.data(index, UnifiedRole.FullNameRole) == shot.full_name
            assert model.data(index, UnifiedRole.ShowRole) == shot.show
            assert model.data(index, UnifiedRole.SequenceRole) == shot.sequence
            assert model.data(index, UnifiedRole.ItemSpecificRole1) == shot.shot

    def test_empty_model_handling(self, model) -> None:
        """Test empty model edge cases."""
        # Update the underlying model's shots to empty list
        model._underlying_model._shots = []
        # Manually trigger update
        model._update_from_underlying_model()

        assert model.rowCount() == 0

        # Invalid index should return None/empty
        invalid_index = model.index(0, 0)
        assert model.data(invalid_index, Qt.ItemDataRole.DisplayRole) is None

        # PreviousShotsItemModel doesn't have update_visible_range or _load_visible_thumbnails
        # Just verify the model handles empty state gracefully


class TestPreviousShotsSorting:
    """Compact contract tests for PreviousShotsItemModel sorting."""

    @pytest.fixture
    def shots_with_times(self, tmp_path, monkeypatch) -> list[Shot]:
        """Create test shots with different discovered_at timestamps."""
        monkeypatch.setattr("config.Config.SHOWS_ROOT", str(tmp_path))

        return [
            Shot(
                show="proj1",
                sequence="010",
                shot="0010",
                workspace_path=f"{Config.SHOWS_ROOT}/proj1/shots/010/010_0010",
                discovered_at=1000.0,
            ),
            Shot(
                show="proj2",
                sequence="020",
                shot="0020",
                workspace_path=f"{Config.SHOWS_ROOT}/proj2/shots/020/020_0020",
                discovered_at=3000.0,
            ),
            Shot(
                show="proj3",
                sequence="030",
                shot="0030",
                workspace_path=f"{Config.SHOWS_ROOT}/proj3/shots/030/030_0030",
                discovered_at=2000.0,
            ),
        ]

    def test_default_date_sort_order(self, model, shots_with_times) -> None:
        """Item model stores all shots in insertion order (proxy handles date sort)."""
        model._underlying_model._shots = shots_with_times
        model._update_from_underlying_model()

        assert len(model._items) == 3
        assert {shot.full_name for shot in model._items} == {"010_0010", "020_0020", "030_0030"}

    def test_switch_to_name_sort_reorders_items(self, model, shots_with_times, qtbot) -> None:
        """Switching sort mode should reorder and emit layout signals."""
        model._underlying_model._shots = shots_with_times
        model._update_from_underlying_model()

        with qtbot.waitSignals(
            [model.layoutAboutToBeChanged, model.layoutChanged], timeout=1000
        ):
            model.set_sort_order("name")

        assert [shot.full_name for shot in model._items] == ["010_0010", "020_0020", "030_0030"]

    def test_setting_same_sort_order_is_noop(self, model, shots_with_times, qtbot) -> None:
        """Setting the same order should not trigger relayout churn."""
        model._underlying_model._shots = shots_with_times
        model._update_from_underlying_model()

        with qtbot.assertNotEmitted(model.layoutChanged):
            model.set_sort_order("date")
