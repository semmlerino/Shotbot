#!/usr/bin/env python3
"""
UI Update Manager for PyMPEG
Implements efficient UI updates with dirty flags and batching
"""

import time
from collections import defaultdict

from PySide6.QtCore import QObject, QTimer, Signal


class UIUpdateManager(QObject):
    """Manages efficient UI updates with dirty flags and batching"""

    # Signal emitted when UI updates should be performed
    update_ui = Signal(dict)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        # Dirty flags for different UI components
        self.dirty_flags: dict[str, bool] = defaultdict(bool)

        # Pending updates to be batched
        self.pending_updates: dict[str, object] = {}

        # Track update frequencies for adaptive timing
        self.update_stats: dict[str, float] = defaultdict(float)
        self.last_update_time: dict[str, float] = defaultdict(float)

        # Animation frame timing (60 FPS = 16.67ms)
        self.frame_time = 16.67 / 1000.0  # Convert to seconds
        self.last_frame_time = 0

        # Update timer with adaptive interval
        self.update_timer = QTimer()
        _ = self.update_timer.timeout.connect(self._process_updates)
        self.base_interval = 100  # Base interval in ms
        self.current_interval = self.base_interval
        self.min_interval = 16  # Minimum 60 FPS
        self.max_interval = 1000  # Maximum 1 second

        # Activity tracking
        self.last_activity_time = time.time()
        self.high_activity_threshold = 0.5  # seconds
        self.low_activity_threshold = 2.0  # seconds

        # Component priorities
        self.component_priorities = {
            "progress_bar": 1,
            "status_label": 2,
            "fps_display": 3,
            "eta_display": 4,
            "log_display": 5,
            "file_list": 6,
        }

    def start(self):
        """Start the update manager"""
        self.update_timer.start(self.current_interval)

    def stop(self):
        """Stop the update manager"""
        self.update_timer.stop()

    def mark_dirty(self, component: str, data: object = None):
        """Mark a component as needing update"""
        self.dirty_flags[component] = True
        if data is not None:
            self.pending_updates[component] = data
        self.last_activity_time = time.time()

    def is_dirty(self, component: str) -> bool:
        """Check if a component needs updating"""
        return self.dirty_flags.get(component, False)

    def _process_updates(self):
        """Process pending updates based on dirty flags"""
        current_time = time.time()

        # Skip if too soon since last frame
        if current_time - self.last_frame_time < self.frame_time:
            return

        # Collect updates to perform
        updates_to_perform = {}
        components_to_update = []

        # Sort components by priority
        sorted_components = sorted(
            self.dirty_flags.keys(), key=lambda c: self.component_priorities.get(c, 999)
        )

        # Process dirty components
        for component in sorted_components:
            if not self.dirty_flags[component]:
                continue

            # Check if enough time has passed for this component
            last_update = self.last_update_time[component]
            min_interval = self._get_component_interval(component)

            if current_time - last_update >= min_interval:
                components_to_update.append(component)
                if component in self.pending_updates:
                    updates_to_perform[component] = self.pending_updates[component]
                self.last_update_time[component] = current_time

        # Clear dirty flags for updated components
        for component in components_to_update:
            self.dirty_flags[component] = False
            self.pending_updates.pop(component, None)

        # Emit updates if any
        if updates_to_perform:
            self.update_ui.emit(updates_to_perform)
            self.last_frame_time = current_time

        # Adjust update interval based on activity
        self._adjust_update_interval()

    def _get_component_interval(self, component: str) -> float:
        """Get minimum update interval for a component"""
        # High-priority components update more frequently
        base_intervals = {
            "progress_bar": 0.1,  # 100ms
            "status_label": 0.25,  # 250ms
            "fps_display": 0.5,  # 500ms
            "eta_display": 1.0,  # 1 second
            "log_display": 0.5,  # 500ms
            "file_list": 0.25,  # 250ms
        }
        return base_intervals.get(component, 1.0)

    def _adjust_update_interval(self):
        """Dynamically adjust update timer interval based on activity"""
        current_time = time.time()
        time_since_activity = current_time - self.last_activity_time

        # Count active dirty flags
        active_count = sum(1 for dirty in self.dirty_flags.values() if dirty)

        # Determine new interval
        if active_count > 5 or time_since_activity < self.high_activity_threshold:
            # High activity - fast updates
            new_interval = self.min_interval
        elif active_count > 0 and time_since_activity < self.low_activity_threshold:
            # Medium activity
            new_interval = self.base_interval
        else:
            # Low activity - slow updates
            new_interval = self.max_interval

        # Apply change if significant
        if abs(new_interval - self.current_interval) > 10:
            self.current_interval = new_interval
            if self.update_timer.isActive():
                self.update_timer.setInterval(new_interval)

    def batch_update(self, updates: dict[str, object]):
        """Batch multiple updates together"""
        for component, data in updates.items():
            self.mark_dirty(component, data)

    def force_update(self, component: str | None = None):
        """Force immediate update of component(s)"""
        if component:
            # Force update specific component
            if self.dirty_flags.get(component):
                self.last_update_time[component] = 0
        else:
            # Force update all dirty components
            for comp in self.dirty_flags:
                if self.dirty_flags[comp]:
                    self.last_update_time[comp] = 0

        # Trigger immediate update
        self._process_updates()

    def get_update_stats(self) -> dict[str, dict[str, float]]:
        """Get statistics about update frequencies"""
        stats = {}
        current_time = time.time()

        for component in self.dirty_flags:
            last_update = self.last_update_time.get(component, 0)
            stats[component] = {
                "last_update_ago": current_time - last_update
                if last_update > 0
                else -1,
                "is_dirty": self.dirty_flags[component],
                "min_interval": self._get_component_interval(component),
            }

        return stats
