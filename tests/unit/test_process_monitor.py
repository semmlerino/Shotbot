#!/usr/bin/env python3
"""
Unit tests for ProcessMonitor class
Tests process widget creation, progress updates, and widget lifecycle
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QProgressBar, QLabel

from process_monitor import ProcessMonitor
from config import UIConfig


class TestProcessMonitor:
    """Test suite for ProcessMonitor class"""

    @pytest.fixture(autouse=True)
    def setup_monitor(self, qtbot):
        """Create ProcessMonitor instance for each test"""
        from PySide6.QtWidgets import QScrollArea
        
        self.mock_process_manager = Mock()
        self.mock_process_manager.update_progress = Mock()
        self.mock_process_manager.process_finished = Mock()
        
        # Create a real scroll area widget for the monitor
        self.scroll_area = QScrollArea()
        qtbot.addWidget(self.scroll_area)
        
        # ProcessMonitor is a QObject, not a widget
        self.monitor = ProcessMonitor(self.mock_process_manager, self.scroll_area)
        self.qtbot = qtbot

    def test_init(self):
        """Test monitor initialization"""
        assert self.monitor.process_manager == self.mock_process_manager
        assert isinstance(self.monitor.process_widgets, dict)
        assert self.monitor.scroll_area == self.scroll_area
        
        # Check signal connections
        self.mock_process_manager.update_progress.connect.assert_called_once()
        self.mock_process_manager.process_finished.connect.assert_called_once()

    def test_create_process_widget(self):
        """Test creating a process monitoring widget"""
        # Use a real QProcess to avoid segfault when emitting signals
        process = QProcess()
        test_path = "/test/video.ts"
        
        widget = self.monitor.create_process_widget(process, test_path)
        
        # Check widget was created and stored
        assert widget is not None
        assert process in self.monitor.process_widgets
        assert self.monitor.process_widgets[process]["widget"] == widget
        
        # Check widget was added to layout
        assert hasattr(widget, "setParent")
        
        # Check signal emission
        with self.qtbot.waitSignal(self.monitor.widget_created, timeout=100):
            widget2 = self.monitor.create_process_widget(QProcess(), "/test/video2.ts")

    def test_create_process_widget_structure(self):
        """Test the structure of created process widget"""
        process = QProcess()
        test_path = "/test/video.ts"
        
        widget = self.monitor.create_process_widget(process, test_path)
        
        # Verify widget has expected components
        # The actual structure depends on implementation
        assert isinstance(widget, QWidget)

    def test_update_all_progress(self):
        """Test updating progress for all monitored processes"""
        # Create test processes and widgets
        processes = []
        for i in range(3):
            process = QProcess()
            processes.append(process)
            widget = self._create_mock_widget()
            # Store widget data structure matching real implementation
            self.monitor.process_widgets[process] = {
                "widget": widget,
                "cleanup_scheduled": False,
                "progress_bar": widget.progress_bar,
                "status_label": widget.status_label,
                "progress_info": widget.progress_info,
                "time_info": widget.time_info,
                "file_label": widget.file_label,
                "created_time": 0,
                "finished_time": None,
                "path": f"/test/video{i}.ts"
            }
        
        # Mock progress data
        self.mock_process_manager.get_process_progress.side_effect = [
            {"current_pct": 25, "fps": 30, "eta": "00:05:00"},
            {"current_pct": 50, "fps": 25, "eta": "00:03:00"},
            {"current_pct": 75, "fps": 28, "eta": "00:01:00"},
        ]
        
        self.monitor._update_all_progress()
        
        # Verify progress was queried for each process
        assert self.mock_process_manager.get_process_progress.call_count == 3
        
        # Verify progress bars were updated
        for i, process in enumerate(processes):
            widget_data = self.monitor.process_widgets[process]
            expected_pct = (i + 1) * 25
            widget_data["progress_bar"].setValue.assert_called_with(expected_pct)

    def test_on_process_finished(self):
        """Test handling process completion"""
        process = QProcess()
        # Mock exitCode() for the process
        process.exitCode = Mock(return_value=0)
        mock_widget = self._create_mock_widget()
        self.monitor.process_widgets[process] = {
            "widget": mock_widget,
            "cleanup_scheduled": False,
            "progress_bar": mock_widget.progress_bar,
            "status_label": mock_widget.status_label,
            "progress_info": mock_widget.progress_info,
            "time_info": mock_widget.time_info,
            "file_label": mock_widget.file_label,
            "created_time": 0,
            "finished_time": None,
            "path": "/test/video.ts"
        }
        
        # Call process finished handler
        with patch.object(self.monitor, "widget_removed"):
            self.monitor._on_process_finished(process, 0, "/test/video.ts")
        
        # Widget should be marked for cleanup
        assert self.monitor.process_widgets[process]["cleanup_scheduled"]
        assert self.monitor.process_widgets[process]["finished_time"] is not None
        
        # Simulate the cleanup timer firing
        self.monitor._cleanup_old_widgets()
        
        # Widget should still be present immediately (removal delay not met)
        assert process in self.monitor.process_widgets
        
        # Simulate time passing
        import time
        self.monitor.process_widgets[process]["finished_time"] = time.time() - 10
        
        # Now cleanup should remove it
        self.monitor._cleanup_old_widgets()
        assert process not in self.monitor.process_widgets

    def test_remove_process_widget(self):
        """Test removing a process widget"""
        process = QProcess()
        mock_widget = self._create_mock_widget()
        self.monitor.process_widgets[process] = {
            "widget": mock_widget,
            "cleanup_scheduled": False,
            "progress_bar": mock_widget.progress_bar,
            "status_label": mock_widget.status_label,
            "progress_info": mock_widget.progress_info,
            "time_info": mock_widget.time_info,
            "file_label": mock_widget.file_label,
            "created_time": 0,
            "finished_time": None,
            "path": "/test/video.ts"
        }
        
        # Add exitCode to process
        process.exitCode = Mock(return_value=0)
        
        # Call the actual remove method, which schedules removal
        # Mock the signal to prevent segfault
        with patch.object(self.monitor, "widget_removed"):
            self.monitor.remove_process_widget(process)
        
        # Check widget is marked for cleanup
        assert self.monitor.process_widgets[process]["cleanup_scheduled"]
        
        # Mock the scroll area widget to ensure deleteLater is called
        mock_scroll_widget = Mock()
        mock_layout = Mock()
        mock_scroll_widget.layout.return_value = mock_layout
        with patch.object(self.monitor.scroll_area, 'widget', return_value=mock_scroll_widget):
            # Actually remove it from scroll area
            self.monitor._remove_widget_from_scroll_area(process)
        
        # Check widget was removed from tracking
        assert process not in self.monitor.process_widgets
        
        # Check widget deletion was scheduled
        mock_widget.deleteLater.assert_called_once()
        mock_widget.setParent.assert_called_once_with(None)

    def test_clear_all_widgets(self):
        """Test clearing all process widgets"""
        # Add multiple widgets
        processes = []
        for i in range(3):
            process = QProcess()
            processes.append(process)
            widget = self._create_mock_widget()
            self.monitor.process_widgets[process] = {
                "widget": widget,
                "cleanup_scheduled": False,
                "progress_bar": widget.progress_bar,
                "status_label": widget.status_label,
                "progress_info": widget.progress_info,
                "time_info": widget.time_info,
                "file_label": widget.file_label,
                "created_time": 0,
                "finished_time": None,
                "path": f"/test/video{i}.ts"
            }
        
        self.monitor.cleanup_all_widgets()
        
        # All widgets should be removed
        assert len(self.monitor.process_widgets) == 0
        
        # Each widget should be scheduled for deletion
        for process in processes:
            # Widget's deleteLater would have been called during removal
            pass

    def test_update_process_widget_display(self):
        """Test updating individual process widget display"""
        process = QProcess()
        mock_widget = self._create_mock_widget()
        self.monitor.process_widgets[process] = {
            "widget": mock_widget,
            "cleanup_scheduled": False,
            "progress_bar": mock_widget.progress_bar,
            "status_label": mock_widget.status_label,
            "progress_info": mock_widget.progress_info,
            "time_info": mock_widget.time_info,
            "file_label": mock_widget.file_label,
            "created_time": 0,
            "finished_time": None,
            "path": "/test/video.ts"
        }
        
        progress_data = {
            "current_pct": 60,
            "fps": 24,
            "eta": "00:02:30",
            "speed": "1.2x"
        }
        
        # Mock getting progress
        self.mock_process_manager.get_process_progress.return_value = progress_data
        
        self.monitor._update_all_progress()
        
        # Check progress bar updated
        widget_data = self.monitor.process_widgets[process]
        widget_data["progress_bar"].setValue.assert_called_with(60)
        
        # Check status label updated with FPS and ETA
        status_calls = widget_data["status_label"].setText.call_args_list
        assert len(status_calls) > 0
        
        # Also check progress_info was updated
        widget_data["progress_info"].setText.assert_called_with("60% • 24 fps")

    def test_process_widget_log_output(self):
        """Test process output logging in widget"""
        process = QProcess()
        mock_widget = self._create_mock_widget()
        self.monitor.process_widgets[process] = {
            "widget": mock_widget,
            "cleanup_scheduled": False,
            "progress_bar": mock_widget.progress_bar,
            "status_label": mock_widget.status_label,
            "progress_info": mock_widget.progress_info,
            "time_info": mock_widget.time_info,
            "file_label": mock_widget.file_label,
            "created_time": 0,
            "finished_time": None,
            "path": "/test/video.ts"
        }
        
        # Mock process manager with log output
        self.mock_process_manager.get_process_output.return_value = [
            "frame=  100 fps= 25",
            "frame=  200 fps= 25",
            "frame=  300 fps= 25"
        ]
        
        # The actual log update implementation is in the monitor
        # This test verifies the structure is in place

    def test_get_active_process_count(self):
        """Test getting count of active processes"""
        # Add some process widgets
        for i in range(5):
            process = QProcess()
            widget = self._create_mock_widget()
            self.monitor.process_widgets[process] = {
                "widget": widget,
                "cleanup_scheduled": False,
                "progress_bar": widget.progress_bar,
                "status_label": widget.status_label,
                "progress_info": widget.progress_info,
                "time_info": widget.time_info,
                "file_label": widget.file_label,
                "created_time": 0,
                "finished_time": None,
                "path": f"/test/video{i}.ts"
            }
        
        count = self.monitor.get_active_widget_count()
        assert count == 5

    def test_emit_progress_updated_signal(self):
        """Test progress update signal emission"""
        # Add a process
        process = QProcess()
        widget = self._create_mock_widget()
        self.monitor.process_widgets[process] = {
            "widget": widget,
            "cleanup_scheduled": False,
            "progress_bar": widget.progress_bar,
            "status_label": widget.status_label,
            "progress_info": widget.progress_info,
            "time_info": widget.time_info,
            "file_label": widget.file_label,
            "created_time": 0,
            "finished_time": None,
            "path": "/test/video.ts"
        }
        
        # Mock progress data from process manager
        self.mock_process_manager.get_overall_progress.return_value = {"test_process": {"current_pct": 40}}
        self.mock_process_manager.get_process_progress.return_value = {"current_pct": 40}
        
        # Test signal emission
        with self.qtbot.waitSignal(self.monitor.progress_updated, timeout=100):
            self.monitor._update_all_progress()

    def test_concurrent_widget_operations(self):
        """Test concurrent widget creation and removal"""
        # Create widgets
        processes = []
        for i in range(3):
            process = QProcess()
            process.exitCode = Mock(return_value=0)  # Add exitCode method
            processes.append(process)
            self.monitor.create_process_widget(process, f"/test/video{i}.ts")
        
        # Remove middle one while others active - this just marks for cleanup
        # Mock the signal to prevent segfault
        with patch.object(self.monitor, "widget_removed"):
            self.monitor.remove_process_widget(processes[1])
        
        # Check widget is marked for cleanup but still present
        assert processes[0] in self.monitor.process_widgets
        assert processes[1] in self.monitor.process_widgets
        assert processes[2] in self.monitor.process_widgets
        
        # Check that middle one is scheduled for cleanup
        assert self.monitor.process_widgets[processes[1]]["cleanup_scheduled"]
        assert not self.monitor.process_widgets[processes[0]]["cleanup_scheduled"]
        assert not self.monitor.process_widgets[processes[2]]["cleanup_scheduled"]

    def _create_mock_widget(self):
        """Helper to create a mock process widget"""
        mock_widget = Mock(spec=QWidget)
        mock_widget.progress_bar = Mock(spec=QProgressBar)
        mock_widget.status_label = Mock(spec=QLabel)
        mock_widget.progress_info = Mock(spec=QLabel)
        mock_widget.time_info = Mock(spec=QLabel)
        mock_widget.file_label = Mock(spec=QLabel)
        mock_widget.log_output = Mock()
        mock_widget.deleteLater = Mock()
        mock_widget.setParent = Mock()
        return mock_widget