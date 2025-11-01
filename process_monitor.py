#!/usr/bin/env python3
"""
Process Monitor Module for PyMPEG
Handles process widget creation, monitoring, and progress display
"""

import os
import time
from typing import Dict, Any
from PySide6.QtCore import QObject, Signal, QProcess, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QFrame,
)

from process_manager import ProcessManager
from config import UIConfig
from logging_config import get_logger


class ProcessMonitor(QObject):
    """Monitors and displays progress for active processes"""

    # Signals for UI updates
    widget_created = Signal(QWidget, QProcess, str)  # widget, process, path
    widget_removed = Signal(QWidget, QProcess)  # widget, process
    progress_updated = Signal(dict)  # progress data

    def __init__(
        self, process_manager: ProcessManager, scroll_area: QScrollArea, parent=None
    ):
        super().__init__(parent)
        self.logger = get_logger()
        self.process_manager = process_manager
        self.scroll_area = scroll_area

        # Track process widgets and their data
        self.process_widgets: Dict[QProcess, Dict[str, Any]] = {}

        # Widget removal timer
        self.removal_timer = QTimer()
        self.removal_timer.timeout.connect(self._cleanup_old_widgets)
        self.removal_timer.start(UIConfig.WIDGET_REMOVAL_DELAY)

        # Connect to process manager signals
        self.process_manager.update_progress.connect(self._update_all_progress)
        self.process_manager.process_finished.connect(self._on_process_finished)

    def create_process_widget(self, process: QProcess, path: str) -> QWidget:
        """Create a progress widget for a process"""
        try:
            if process in self.process_widgets:
                return self.process_widgets[process]["widget"]

            # Create main widget
            widget = QFrame()
            widget.setFrameStyle(QFrame.Shape.StyledPanel)
            widget.setStyleSheet(
                "QFrame { border: 1px solid #ccc; margin: 2px; padding: 4px; }"
            )

            layout = QVBoxLayout(widget)
            layout.setContentsMargins(8, 8, 8, 8)

            # File info header
            header_layout = QHBoxLayout()
            file_label = QLabel(f"📂 {os.path.basename(path)}")
            file_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
            header_layout.addWidget(file_label)
            header_layout.addStretch()

            status_label = QLabel("Starting...")
            status_label.setStyleSheet("color: #7f8c8d; font-size: 11px;")
            header_layout.addWidget(status_label)

            layout.addLayout(header_layout)

            # Progress bar
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #bdc3c7;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 11px;
                }
                QProgressBar::chunk {
                    background-color: #3498db;
                    border-radius: 2px;
                }
            """)
            layout.addWidget(progress_bar)

            # Details layout
            details_layout = QHBoxLayout()

            # Progress info
            progress_info = QLabel("0% • 0.0 fps")
            progress_info.setStyleSheet("color: #7f8c8d; font-size: 10px;")
            details_layout.addWidget(progress_info)

            details_layout.addStretch()

            # Time info
            time_info = QLabel("00:00:00 / 00:00:00")
            time_info.setStyleSheet("color: #7f8c8d; font-size: 10px;")
            details_layout.addWidget(time_info)

            layout.addLayout(details_layout)

            # Store widget data
            self.process_widgets[process] = {
                "widget": widget,
                "path": path,
                "progress_bar": progress_bar,
                "status_label": status_label,
                "progress_info": progress_info,
                "time_info": time_info,
                "file_label": file_label,
                "created_time": time.time(),
                "finished_time": None,
                "cleanup_scheduled": False,
            }

            # Add to scroll area
            self._add_widget_to_scroll_area(widget)

            # Emit signal
            self.widget_created.emit(widget, process, path)

            return widget

        except Exception as e:
            self.logger.error(
                f"Failed to create process widget: {e}",
                extra_info={"path": path},
                suggestion="Check UI components are accessible and initialized",
            )
            # Return a minimal error widget
            error_widget = QFrame()
            error_label = QLabel(
                f"⚠️ Widget creation failed for {os.path.basename(path)}"
            )
            error_layout = QVBoxLayout(error_widget)
            error_layout.addWidget(error_label)
            return error_widget

    def remove_process_widget(self, process: QProcess) -> None:
        """Schedule removal of a process widget"""
        if process not in self.process_widgets:
            return

        widget_data = self.process_widgets[process]
        widget_data["finished_time"] = time.time()
        widget_data["cleanup_scheduled"] = True

        # Update status to show completion
        status_label = widget_data["status_label"]
        progress_bar = widget_data["progress_bar"]

        if process.exitCode() == 0:
            status_label.setText("✅ Completed")
            status_label.setStyleSheet(
                "color: #27ae60; font-size: 11px; font-weight: bold;"
            )
            progress_bar.setValue(100)
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #27ae60;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 11px;
                }
                QProgressBar::chunk {
                    background-color: #2ecc71;
                    border-radius: 2px;
                }
            """)
        else:
            status_label.setText("❌ Failed")
            status_label.setStyleSheet(
                "color: #e74c3c; font-size: 11px; font-weight: bold;"
            )
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #e74c3c;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 11px;
                }
                QProgressBar::chunk {
                    background-color: #e74c3c;
                    border-radius: 2px;
                }
            """)

        # Emit signal
        self.widget_removed.emit(widget_data["widget"], process)

    def _update_all_progress(self) -> None:
        """Update progress for all active process widgets"""
        overall_progress = self.process_manager.get_overall_progress()

        # Update individual process widgets
        for process, widget_data in list(self.process_widgets.items()):
            if widget_data["cleanup_scheduled"]:
                continue

            # Get process-specific progress
            process_progress = self.process_manager.get_process_progress(process)
            if process_progress:
                self._update_process_widget(process, process_progress, widget_data)

        # Emit overall progress signal
        self.progress_updated.emit(overall_progress)

    def _update_process_widget(
        self,
        process: QProcess,
        progress_data: Dict[str, Any],
        widget_data: Dict[str, Any],
    ) -> None:
        """Update a specific process widget with progress data"""
        try:
            pct = progress_data.get("current_pct", 0)
            fps = progress_data.get("fps", 0)
            elapsed_str = progress_data.get("elapsed_str", "00:00:00")
            remain_str = progress_data.get("remain_str", "00:00:00")

            # Update progress bar
            progress_bar = widget_data.get("progress_bar")
            if progress_bar is not None:
                progress_bar.setValue(pct)

            # Update progress info
            progress_info = widget_data.get("progress_info")
            if progress_info is not None:
                progress_info.setText(f"{pct}% • {fps} fps")

            # Update time info
            time_info = widget_data.get("time_info")
            if time_info is not None:
                time_info.setText(f"{elapsed_str} / {remain_str}")

            # Update status
            status_label = widget_data.get("status_label")
            if status_label is not None and pct > 0:
                status_label.setText(f"Encoding ({pct}%)")
                status_label.setStyleSheet("color: #3498db; font-size: 11px;")

        except Exception as e:
            self.logger.error(
                f"Error updating process widget: {e}",
                extra_info={
                    "process_state": process.state() if process else "unknown",
                    "widget_exists": bool(widget_data.get("widget")),
                },
                suggestion="Check if widget is still valid and accessible",
            )

    def _add_widget_to_scroll_area(self, widget: QWidget) -> None:
        """Add a widget to the scroll area"""
        scroll_widget = self.scroll_area.widget()
        if scroll_widget is None:
            # Create scroll widget if it doesn't exist
            scroll_widget = QWidget()
            scroll_layout = QVBoxLayout(scroll_widget)
            scroll_layout.setContentsMargins(4, 4, 4, 4)
            scroll_layout.addStretch()
            self.scroll_area.setWidget(scroll_widget)

        layout = scroll_widget.layout()
        if layout is not None and isinstance(layout, QVBoxLayout):
            # Insert before the stretch
            layout.insertWidget(layout.count() - 1, widget)

    def _cleanup_old_widgets(self) -> None:
        """Clean up widgets that have been finished for a while"""
        current_time = time.time()
        widgets_to_remove = []

        for process, widget_data in self.process_widgets.items():
            if (
                widget_data["cleanup_scheduled"]
                and widget_data["finished_time"]
                and current_time - widget_data["finished_time"]
                > UIConfig.WIDGET_REMOVAL_DELAY / 1000
            ):
                widgets_to_remove.append(process)

        for process in widgets_to_remove:
            self._remove_widget_from_scroll_area(process)

    def _remove_widget_from_scroll_area(self, process: QProcess) -> None:
        """Remove a widget from the scroll area"""
        if process not in self.process_widgets:
            return

        widget_data = self.process_widgets[process]
        widget = widget_data["widget"]

        # Remove from scroll area
        scroll_widget = self.scroll_area.widget()
        if scroll_widget:
            layout = scroll_widget.layout()
            if layout is not None:
                layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()

        # Remove from tracking
        del self.process_widgets[process]

    def _on_process_finished(
        self, process: QProcess, exit_code: int, process_path: str
    ) -> None:
        """Handle process finished signal"""
        self.remove_process_widget(process)

    def cleanup_all_widgets(self) -> None:
        """Clean up all process widgets"""
        for process in list(self.process_widgets.keys()):
            self._remove_widget_from_scroll_area(process)

        # Clear the scroll area
        scroll_widget = self.scroll_area.widget()
        if scroll_widget:
            layout = scroll_widget.layout()
            if layout is not None:
                while layout.count() > 1:  # Keep the stretch
                    item = layout.takeAt(0)
                    if item and item.widget():
                        item.widget().deleteLater()

    def get_active_widget_count(self) -> int:
        """Get the number of active process widgets"""
        return len(
            [w for w in self.process_widgets.values() if not w["cleanup_scheduled"]]
        )

    def get_total_widget_count(self) -> int:
        """Get the total number of process widgets"""
        return len(self.process_widgets)
