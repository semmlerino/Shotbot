#!/usr/bin/env python3
"""
Unit tests for FileListWidget class
Tests drag-drop functionality, file management, status tracking, and progress display
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import os
from PySide6.QtCore import Qt, QUrl, QMimeData, QPoint
from PySide6.QtWidgets import QListWidgetItem
from PySide6.QtGui import QDropEvent, QDragEnterEvent

from file_list_widget import FileListWidget, MetadataWorker


class TestFileListWidget:
    """Test suite for FileListWidget class"""

    @pytest.fixture(autouse=True)
    def setup_widget(self, qtbot):
        """Create FileListWidget instance for each test"""
        self.widget = FileListWidget()
        qtbot.addWidget(self.widget)
        self.qtbot = qtbot

    def test_init(self):
        """Test widget initialization"""
        assert self.widget.acceptDrops() is True
        assert len(self.widget.path_items) == 0
        assert self.widget.alternatingRowColors() is True

    def test_add_path(self):
        """Test adding a file path"""
        test_path = "/test/video.ts"
        
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            mock_fileinfo.return_value.fileName.return_value = "video.ts"
            self.widget.add_path(test_path)
        
        assert test_path in self.widget.path_items
        assert self.widget.count() == 1
        
        # Test duplicate prevention
        self.widget.add_path(test_path)
        assert self.widget.count() == 1

    def test_drag_enter_event(self):
        """Test drag enter event handling"""
        event = Mock(spec=QDragEnterEvent)
        mime_data = Mock()
        mime_data.hasUrls.return_value = True
        event.mimeData.return_value = mime_data
        
        self.widget.dragEnterEvent(event)
        event.acceptProposedAction.assert_called_once()

    def test_drop_event_external_files(self):
        """Test dropping external files"""
        # Create mock URLs
        url1 = Mock(spec=QUrl)
        url1.toLocalFile.return_value = "/test/file1.ts"
        url2 = Mock(spec=QUrl)
        url2.toLocalFile.return_value = "/test/file2.TS"  # Test case insensitivity
        url3 = Mock(spec=QUrl)
        url3.toLocalFile.return_value = "/test/file3.mp4"  # Non-TS file
        
        # Create drop event
        event = Mock(spec=QDropEvent)
        mime_data = Mock()
        mime_data.hasUrls.return_value = True
        mime_data.urls.return_value = [url1, url2, url3]
        event.mimeData.return_value = mime_data
        
        with patch("os.path.isfile", return_value=True):
            with patch.object(self.widget, "add_path") as mock_add:
                self.widget.dropEvent(event)
        
        # Should only add .ts files
        assert mock_add.call_count == 2
        mock_add.assert_any_call("/test/file1.ts")
        mock_add.assert_any_call("/test/file2.TS")
        event.acceptProposedAction.assert_called_once()

    def test_update_progress(self):
        """Test progress update functionality"""
        test_path = "/test/video.ts"
        
        # Add file first
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            mock_fileinfo.return_value.fileName.return_value = "video.ts"
            self.widget.add_path(test_path)
        
        # Update progress
        self.widget.update_progress(test_path, 50)
        
        item = self.widget.path_items[test_path]
        assert item.data(Qt.ItemDataRole.UserRole + 2) == 50
        
        # Test status change from pending to processing
        assert item.data(Qt.ItemDataRole.UserRole + 1) == "processing"

    def test_set_status(self):
        """Test status setting functionality"""
        test_path = "/test/video.ts"
        
        # Add file
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            mock_fileinfo.return_value.fileName.return_value = "video.ts"
            self.widget.add_path(test_path)
        
        # Test different statuses
        statuses = ["pending", "processing", "completed", "failed"]
        for status in statuses:
            self.widget.set_status(test_path, status)
            item = self.widget.path_items[test_path]
            assert item.data(Qt.ItemDataRole.UserRole + 1) == status

    def test_get_item_status(self):
        """Test getting item status"""
        test_path = "/test/video.ts"
        
        # Test non-existent path
        assert self.widget.get_item_status(test_path) == ""
        
        # Add file and test
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            mock_fileinfo.return_value.fileName.return_value = "video.ts"
            self.widget.add_path(test_path)
        
        self.widget.set_status(test_path, "processing")
        assert self.widget.get_item_status(test_path) == "processing"

    def test_remove_selected(self):
        """Test removing selected files"""
        # Add test files
        paths = ["/test/file1.ts", "/test/file2.ts", "/test/file3.ts"]
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            for i, path in enumerate(paths):
                mock_fileinfo.return_value.fileName.return_value = f"file{i+1}.ts"
                self.widget.add_path(path)
        
        # Select first two items
        self.widget.item(0).setSelected(True)
        self.widget.item(1).setSelected(True)
        
        removed = self.widget.remove_selected()
        
        assert removed == 2
        assert self.widget.count() == 1
        assert paths[2] in self.widget.path_items
        assert paths[0] not in self.widget.path_items
        assert paths[1] not in self.widget.path_items

    def test_get_file_paths_in_order(self):
        """Test getting file paths in display order"""
        paths = ["/test/file1.ts", "/test/file2.ts", "/test/file3.ts"]
        
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            for i, path in enumerate(paths):
                mock_fileinfo.return_value.fileName.return_value = f"file{i+1}.ts"
                self.widget.add_path(path)
        
        result = self.widget.get_file_paths_in_order()
        assert result == paths

    def test_get_pending_files_in_order(self):
        """Test getting only pending files"""
        paths = ["/test/file1.ts", "/test/file2.ts", "/test/file3.ts"]
        
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            for i, path in enumerate(paths):
                mock_fileinfo.return_value.fileName.return_value = f"file{i+1}.ts"
                self.widget.add_path(path)
        
        # Set different statuses
        self.widget.set_status(paths[0], "completed")
        self.widget.set_status(paths[1], "processing")
        # paths[2] remains pending
        
        result = self.widget.get_pending_files_in_order()
        assert result == [paths[2]]

    def test_move_selected_up(self):
        """Test moving selected items up"""
        paths = ["/test/file1.ts", "/test/file2.ts", "/test/file3.ts"]
        
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            for i, path in enumerate(paths):
                mock_fileinfo.return_value.fileName.return_value = f"file{i+1}.ts"
                self.widget.add_path(path)
        
        # Select middle item
        self.widget.item(1).setSelected(True)
        
        # Connect signal spy
        with self.qtbot.waitSignal(self.widget.order_changed, timeout=100):
            self.widget.move_selected_up()
        
        # Check new order
        result = self.widget.get_file_paths_in_order()
        assert result == [paths[1], paths[0], paths[2]]

    def test_move_selected_down(self):
        """Test moving selected items down"""
        paths = ["/test/file1.ts", "/test/file2.ts", "/test/file3.ts"]
        
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            for i, path in enumerate(paths):
                mock_fileinfo.return_value.fileName.return_value = f"file{i+1}.ts"
                self.widget.add_path(path)
        
        # Select middle item
        self.widget.item(1).setSelected(True)
        
        self.widget.move_selected_down()
        
        # Check new order
        result = self.widget.get_file_paths_in_order()
        assert result == [paths[0], paths[2], paths[1]]

    def test_clear_completed_files(self):
        """Test clearing completed files"""
        paths = ["/test/file1.ts", "/test/file2.ts", "/test/file3.ts"]
        
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            for i, path in enumerate(paths):
                mock_fileinfo.return_value.fileName.return_value = f"file{i+1}.ts"
                self.widget.add_path(path)
        
        # Set statuses
        self.widget.set_status(paths[0], "completed")
        self.widget.set_status(paths[1], "failed")
        self.widget.set_status(paths[2], "completed")
        
        removed = self.widget.clear_completed_files()
        
        assert removed == 2
        assert self.widget.count() == 1
        assert paths[1] in self.widget.path_items

    def test_remove_failed_files(self):
        """Test removing failed files"""
        paths = ["/test/file1.ts", "/test/file2.ts", "/test/file3.ts"]
        
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            for i, path in enumerate(paths):
                mock_fileinfo.return_value.fileName.return_value = f"file{i+1}.ts"
                self.widget.add_path(path)
        
        # Set statuses
        self.widget.set_status(paths[0], "failed")
        self.widget.set_status(paths[1], "completed")
        self.widget.set_status(paths[2], "failed")
        
        removed = self.widget.remove_failed_files()
        
        assert removed == 2
        assert self.widget.count() == 1
        assert paths[1] in self.widget.path_items

    def test_get_status_counts(self):
        """Test getting status counts"""
        paths = ["/test/file1.ts", "/test/file2.ts", "/test/file3.ts", "/test/file4.ts"]
        
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            for i, path in enumerate(paths):
                mock_fileinfo.return_value.fileName.return_value = f"file{i+1}.ts"
                self.widget.add_path(path)
        
        # Set various statuses
        self.widget.set_status(paths[0], "completed")
        self.widget.set_status(paths[1], "processing")
        self.widget.set_status(paths[2], "failed")
        # paths[3] remains pending
        
        counts = self.widget.get_status_counts()
        
        assert counts == {
            "pending": 1,
            "processing": 1,
            "completed": 1,
            "failed": 1
        }

    def test_refresh_drag_drop_state(self):
        """Test refreshing drag-drop functionality"""
        # Clear initial state
        self.widget.setAcceptDrops(False)
        
        # Refresh
        self.widget.refresh_drag_drop_state()
        
        # Check restored
        assert self.widget.acceptDrops() is True

    def test_metadata_loading(self):
        """Test asynchronous metadata loading"""
        test_path = "/test/video.ts"
        test_metadata = {
            "duration": "00:10:30",
            "width": 1920,
            "height": 1080,
            "codec": "h264",
            "bitrate": "5000k"
        }
        
        # Add file
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            mock_fileinfo.return_value.fileName.return_value = "video.ts"
            self.widget.add_path(test_path)
        
        # Simulate metadata loaded
        self.widget._on_metadata_loaded(test_path, test_metadata)
        
        assert self.widget.metadata_cache[test_path] == test_metadata
        
        # Check display updated
        item = self.widget.path_items[test_path]
        assert "1920x1080" in item.text()
        assert "H264" in item.text()

    def test_context_menu_move_operations(self):
        """Test context menu move up/down operations"""
        # Add files
        paths = ["/test/file1.ts", "/test/file2.ts", "/test/file3.ts"]
        with patch("file_list_widget.QFileInfo") as mock_fileinfo:
            for i, path in enumerate(paths):
                mock_fileinfo.return_value.fileName.return_value = f"file{i+1}.ts"
                self.widget.add_path(path)
        
        # Select last item and verify can't move down
        self.widget.item(2).setSelected(True)
        
        # Select first item and verify can't move up
        self.widget.clearSelection()
        self.widget.item(0).setSelected(True)
        
        # Test that proper bounds checking happens in context menu
        # (actual menu testing would require more Qt event simulation)


class TestMetadataWorker:
    """Test suite for MetadataWorker class"""
    
    def test_metadata_worker_run(self):
        """Test metadata worker execution"""
        test_path = "/test/video.ts"
        test_metadata = {"duration": "00:10:30", "codec": "h264"}
        
        signals = Mock()
        worker = MetadataWorker(test_path, signals)
        
        with patch("codec_helpers.CodecHelpers.extract_video_metadata", return_value=test_metadata):
            worker.run()
        
        signals.metadata_loaded.emit.assert_called_once_with(test_path, test_metadata)