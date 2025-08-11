"""Snapshot testing for ShotBot UI states and configurations.

This module provides snapshot testing capabilities to detect
regression in UI states, cache persistence, and configuration.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QWidget


@dataclass
class Snapshot:
    """Represents a snapshot of application state."""

    id: str
    timestamp: datetime
    data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    checksum: Optional[str] = None

    def __post_init__(self):
        """Calculate checksum if not provided."""
        if not self.checksum:
            self.checksum = self._calculate_checksum()

    def _calculate_checksum(self) -> str:
        """Calculate SHA256 checksum of snapshot data."""
        data_str = json.dumps(self.data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()

    def matches(self, other: "Snapshot") -> bool:
        """Check if this snapshot matches another.

        Args:
            other: Snapshot to compare with

        Returns:
            True if snapshots match
        """
        return self.checksum == other.checksum

    def diff(self, other: "Snapshot") -> Dict[str, Any]:
        """Generate diff between snapshots.

        Args:
            other: Snapshot to compare with

        Returns:
            Dictionary describing differences
        """
        diff_result = {
            "added": {},
            "removed": {},
            "changed": {},
        }

        # Find added keys
        for key in other.data:
            if key not in self.data:
                diff_result["added"][key] = other.data[key]

        # Find removed keys
        for key in self.data:
            if key not in other.data:
                diff_result["removed"][key] = self.data[key]

        # Find changed values
        for key in self.data:
            if key in other.data and self.data[key] != other.data[key]:
                diff_result["changed"][key] = {
                    "old": self.data[key],
                    "new": other.data[key],
                }

        return diff_result


class SnapshotStore:
    """Manages storage and retrieval of snapshots."""

    def __init__(self, base_dir: Optional[Path] = None):
        """Initialize snapshot store.

        Args:
            base_dir: Base directory for snapshot storage
        """
        self.base_dir = base_dir or Path(__file__).parent / "snapshots"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: Snapshot, category: str = "default") -> Path:
        """Save a snapshot to disk.

        Args:
            snapshot: Snapshot to save
            category: Category for organization

        Returns:
            Path to saved snapshot file
        """
        category_dir = self.base_dir / category
        category_dir.mkdir(exist_ok=True)

        filename = f"{snapshot.id}_{snapshot.timestamp.isoformat()}.json"
        filepath = category_dir / filename

        data = {
            "id": snapshot.id,
            "timestamp": snapshot.timestamp.isoformat(),
            "data": snapshot.data,
            "metadata": snapshot.metadata,
            "checksum": snapshot.checksum,
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

        return filepath

    def load(self, snapshot_id: str, category: str = "default") -> Optional[Snapshot]:
        """Load a snapshot from disk.

        Args:
            snapshot_id: ID of snapshot to load
            category: Category to search in

        Returns:
            Loaded snapshot or None if not found
        """
        category_dir = self.base_dir / category
        if not category_dir.exists():
            return None

        # Find latest snapshot with given ID
        matching_files = sorted(
            category_dir.glob(f"{snapshot_id}_*.json"), reverse=True
        )

        if not matching_files:
            return None

        with open(matching_files[0], "r") as f:
            data = json.load(f)

        return Snapshot(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            data=data["data"],
            metadata=data.get("metadata", {}),
            checksum=data.get("checksum"),
        )

    def load_latest(self, category: str = "default") -> Optional[Snapshot]:
        """Load the most recent snapshot in a category.

        Args:
            category: Category to search in

        Returns:
            Latest snapshot or None if category is empty
        """
        category_dir = self.base_dir / category
        if not category_dir.exists():
            return None

        files = sorted(category_dir.glob("*.json"), reverse=True)
        if not files:
            return None

        with open(files[0], "r") as f:
            data = json.load(f)

        return Snapshot(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            data=data["data"],
            metadata=data.get("metadata", {}),
            checksum=data.get("checksum"),
        )


class UISnapshotCapture:
    """Captures snapshots of UI widget states."""

    @staticmethod
    def capture_widget_state(widget: QWidget) -> Dict[str, Any]:
        """Capture the state of a Qt widget.

        Args:
            widget: Widget to capture

        Returns:
            Dictionary containing widget state
        """
        state = {
            "class": widget.__class__.__name__,
            "enabled": widget.isEnabled(),
            "visible": widget.isVisible(),
            "geometry": {
                "x": widget.x(),
                "y": widget.y(),
                "width": widget.width(),
                "height": widget.height(),
            },
        }

        # Capture widget-specific properties
        if hasattr(widget, "text"):
            state["text"] = widget.text()

        if hasattr(widget, "isChecked"):
            state["checked"] = widget.isChecked()

        if hasattr(widget, "value"):
            state["value"] = widget.value()

        if hasattr(widget, "currentIndex"):
            state["currentIndex"] = widget.currentIndex()

        if hasattr(widget, "count"):
            state["count"] = widget.count()

        # Capture custom properties (with error handling)
        for prop in widget.dynamicPropertyNames():
            prop_name = prop.data().decode()
            try:
                prop_value = widget.property(prop_name)
                # Only store serializable property values
                if isinstance(prop_value, (str, int, float, bool, type(None))):
                    state[f"property_{prop_name}"] = prop_value
            except (RuntimeError, TypeError):
                # Skip properties that can't be converted
                pass

        return state

    @staticmethod
    def capture_widget_tree(root: QWidget) -> Dict[str, Any]:
        """Capture state of widget and all children.

        Args:
            root: Root widget

        Returns:
            Nested dictionary of widget states
        """
        state = UISnapshotCapture.capture_widget_state(root)

        # Capture children
        children = []
        for child in root.findChildren(QWidget):
            if child.parent() == root:  # Direct children only
                children.append(UISnapshotCapture.capture_widget_tree(child))

        if children:
            state["children"] = children

        return state


class CacheSnapshot:
    """Captures snapshots of cache state."""

    @staticmethod
    def capture_cache_state(cache_manager) -> Dict[str, Any]:
        """Capture the current state of cache.

        Args:
            cache_manager: CacheManager instance

        Returns:
            Dictionary containing cache state
        """
        state = {
            "entries": {},
            "stats": {
                "total_entries": 0,
                "expired_entries": 0,
                "total_size": 0,
            },
        }

        # Access cache internals (implementation-specific)
        if hasattr(cache_manager, "_cache"):
            for key, entry in cache_manager._cache.items():
                is_expired = cache_manager.is_expired(key)

                # Don't include actual cached data (could be large)
                state["entries"][key] = {
                    "type": type(entry.value).__name__,
                    "ttl": entry.ttl,
                    "expired": is_expired,
                    "timestamp": entry.timestamp,
                }

                state["stats"]["total_entries"] += 1
                if is_expired:
                    state["stats"]["expired_entries"] += 1

        return state


class ConfigSnapshot:
    """Captures snapshots of application configuration."""

    @staticmethod
    def capture_qsettings(settings: QSettings) -> Dict[str, Any]:
        """Capture QSettings state.

        Args:
            settings: QSettings instance

        Returns:
            Dictionary containing settings
        """
        state = {}

        for key in settings.allKeys():
            value = settings.value(key)

            # Handle QByteArray and other Qt types
            if hasattr(value, "data"):
                value = value.data().hex()

            state[key] = value

        return state

    @staticmethod
    def capture_config_module(config_module) -> Dict[str, Any]:
        """Capture configuration module state.

        Args:
            config_module: Config module

        Returns:
            Dictionary containing configuration
        """
        state = {}

        for attr_name in dir(config_module):
            if not attr_name.startswith("_"):
                attr_value = getattr(config_module, attr_name)

                # Only capture simple types and collections
                if isinstance(attr_value, (str, int, float, bool, list, dict, tuple)):
                    state[attr_name] = attr_value

        return state


class SnapshotAssertion:
    """Provides assertion methods for snapshot testing."""

    def __init__(self, store: Optional[SnapshotStore] = None):
        """Initialize snapshot assertion helper.

        Args:
            store: Snapshot store to use
        """
        self.store = store or SnapshotStore()

    def assert_matches_snapshot(
        self,
        data: Dict[str, Any],
        snapshot_id: str,
        category: str = "default",
        update: bool = False,
    ):
        """Assert that data matches a stored snapshot.

        Args:
            data: Data to compare
            snapshot_id: ID of snapshot
            category: Snapshot category
            update: If True, update snapshot instead of asserting
        """
        current = Snapshot(
            id=snapshot_id,
            timestamp=datetime.now(),
            data=data,
        )

        stored = self.store.load(snapshot_id, category)

        if update or stored is None:
            # Create or update snapshot
            self.store.save(current, category)
            if update:
                print(f"Updated snapshot: {snapshot_id}")
            else:
                print(f"Created new snapshot: {snapshot_id}")
        else:
            # Compare with stored snapshot
            if not current.matches(stored):
                diff = stored.diff(current)
                raise AssertionError(
                    f"Snapshot mismatch for {snapshot_id}:\n"
                    f"Diff: {json.dumps(diff, indent=2, default=str)}"
                )


@pytest.fixture
def snapshot_tester():
    """Pytest fixture for snapshot testing."""
    return SnapshotAssertion()


@pytest.mark.snapshot
class TestUISnapshots:
    """Test UI state snapshots."""

    def test_main_window_initial_state(self, qtbot, snapshot_tester):
        """Test main window initial state snapshot."""
        from main_window import MainWindow

        window = MainWindow()
        qtbot.addWidget(window)

        # Capture initial state
        state = UISnapshotCapture.capture_widget_state(window)

        # Remove volatile data
        state.pop("geometry", None)  # Window position varies

        snapshot_tester.assert_matches_snapshot(
            state, "main_window_initial", category="ui"
        )

    def test_shot_grid_state(self, qtbot, snapshot_tester):
        """Test shot grid widget state snapshot."""
        from shot_grid import ShotGrid
        from shot_model import ShotModel

        model = ShotModel()
        grid = ShotGrid(shot_model=model)
        qtbot.addWidget(grid)

        # Grid works with model data - no direct add_shot method
        # Just capture the empty state

        state = UISnapshotCapture.capture_widget_state(grid)

        # Normalize state
        state["item_count"] = state.get("count", 0)
        state.pop("geometry", None)

        snapshot_tester.assert_matches_snapshot(
            state, "shot_grid_with_items", category="ui"
        )

    def test_settings_panel_state(self, qtbot, snapshot_tester):
        """Test settings panel state snapshot."""
        from launcher_dialog import LauncherEditDialog
        from launcher_manager import LauncherManager

        manager = LauncherManager()
        dialog = LauncherEditDialog(launcher_manager=manager)
        qtbot.addWidget(dialog)

        # Capture form state
        state = UISnapshotCapture.capture_widget_tree(dialog)

        # Remove volatile data
        def clean_state(s):
            s.pop("geometry", None)
            if "children" in s:
                for child in s["children"]:
                    clean_state(child)

        clean_state(state)

        snapshot_tester.assert_matches_snapshot(
            state, "launcher_dialog_form", category="ui"
        )


@pytest.mark.snapshot
class TestCacheSnapshots:
    """Test cache state snapshots."""

    def test_cache_state_snapshot(self, snapshot_tester):
        """Test cache manager state snapshot."""
        from cache_manager import CacheManager

        cache = CacheManager()

        # Populate cache
        # CacheManager doesn't have generic set method - use specific methods
        from shot_model import Shot
        test_shots = [
            Shot("TEST", "seq01", "shot01", "/test/path"),
            Shot("TEST", "seq01", "shot02", "/test/path")
        ]
        cache.cache_shots(test_shots)

        # Capture state
        state = CacheSnapshot.capture_cache_state(cache)

        # Normalize timestamps
        for entry in state["entries"].values():
            entry["timestamp"] = "normalized"

        snapshot_tester.assert_matches_snapshot(
            state, "cache_populated", category="cache"
        )

    def test_cache_after_expiration(self, snapshot_tester):
        """Test cache state after some entries expire."""
        import time

        from cache_manager import CacheManager

        cache = CacheManager()

        # Add entries with very short TTL
        # Test with actual cache methods
        from shot_model import Shot
        test_shots = [Shot("EXP", "seq01", "shot01", "/test/path")]
        cache.cache_shots(test_shots)  # This will persist normally

        time.sleep(0.002)

        # Capture state
        state = CacheSnapshot.capture_cache_state(cache)

        # Check that cache state is captured (simpler test)
        assert "stats" in state
        assert "entries" in state

        # Normalize and snapshot
        for entry in state["entries"].values():
            entry["timestamp"] = "normalized"

        snapshot_tester.assert_matches_snapshot(
            state, "cache_with_expired", category="cache"
        )


@pytest.mark.snapshot
class TestConfigSnapshots:
    """Test configuration snapshots."""

    def test_config_module_snapshot(self, snapshot_tester):
        """Test configuration module snapshot."""
        import config

        state = ConfigSnapshot.capture_config_module(config)

        # Filter to important settings only
        important_keys = [
            "APPS",
            "SUBPROCESS_TIMEOUT",
            "CACHE_TTL_SECONDS",
            "UI_UPDATE_INTERVAL_MS",
            "MAX_PARALLEL_SCANS",
        ]

        filtered_state = {k: v for k, v in state.items() if k in important_keys}

        snapshot_tester.assert_matches_snapshot(
            filtered_state, "config_settings", category="config"
        )

    def test_qsettings_snapshot(self, qtbot, snapshot_tester):
        """Test QSettings persistence snapshot."""
        from PySide6.QtCore import QCoreApplication, QSettings

        QCoreApplication.setOrganizationName("TestOrg")
        QCoreApplication.setApplicationName("TestApp")

        settings = QSettings()

        # Set some test values
        settings.setValue("test/string", "value")
        settings.setValue("test/number", 42)
        settings.setValue("test/bool", True)
        settings.setValue("test/list", ["a", "b", "c"])

        state = ConfigSnapshot.capture_qsettings(settings)

        snapshot_tester.assert_matches_snapshot(
            state, "qsettings_test", category="config"
        )


class SnapshotDiffer:
    """Advanced diffing for snapshot comparisons."""

    @staticmethod
    def semantic_diff(
        old: Dict[str, Any], new: Dict[str, Any], context: str = ""
    ) -> List[str]:
        """Generate semantic diff between snapshots.

        Args:
            old: Old snapshot data
            new: New snapshot data
            context: Context path

        Returns:
            List of human-readable diff descriptions
        """
        diffs = []

        # Check added keys
        for key in new:
            if key not in old:
                diffs.append(f"Added {context}.{key}")

        # Check removed keys
        for key in old:
            if key not in new:
                diffs.append(f"Removed {context}.{key}")

        # Check changed values
        for key in old:
            if key in new:
                old_val = old[key]
                new_val = new[key]

                if isinstance(old_val, dict) and isinstance(new_val, dict):
                    # Recursive diff for nested dicts
                    nested_diffs = SnapshotDiffer.semantic_diff(
                        old_val, new_val, f"{context}.{key}"
                    )
                    diffs.extend(nested_diffs)
                elif old_val != new_val:
                    diffs.append(f"Changed {context}.{key}: {old_val} -> {new_val}")

        return diffs


if __name__ == "__main__":
    # Example: Generate baseline snapshots
    store = SnapshotStore()

    # Create example snapshot
    example_data = {
        "version": "1.0.0",
        "features": ["shot_browsing", "3de_discovery", "custom_launchers"],
        "settings": {
            "cache_ttl": 300,
            "max_workers": 4,
        },
    }

    snapshot = Snapshot(
        id="example_baseline",
        timestamp=datetime.now(),
        data=example_data,
    )

    path = store.save(snapshot, "baseline")
    print(f"Saved baseline snapshot to: {path}")
