#!/usr/bin/env python3
"""
File List Widget Module for PyMPEG
A custom QListWidget with drag & drop support for TS files
"""

import os
from PySide6.QtCore import Qt, QFileInfo, QSize
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QAbstractItemView, QMenu
from PySide6.QtGui import QCursor, QColor


class FileListWidget(QListWidget):
    """Drag & drop .ts files, reorder, context menu, and track per-file items.
    Enhanced with progress display and status indicators.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.path_items: dict[str, QListWidgetItem] = {}

        # Colors for different states
        self.color_pending = QColor(0, 0, 0)  # Default color
        self.color_processing = QColor(0, 0, 170)  # Blue
        self.color_completed = QColor(0, 170, 0)  # Green
        self.color_failed = QColor(170, 0, 0)  # Red

        # Set fixed height for items
        self.setIconSize(QSize(16, 16))
        self.setSpacing(2)

    def add_path(self, path: str):
        """Add a new file path to the list with pending status."""
        if path in self.path_items:
            return
        fname = QFileInfo(path).fileName()
        item = QListWidgetItem(fname)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, "pending")  # Store status
        item.setData(Qt.ItemDataRole.UserRole + 2, 0)  # Store progress percentage
        self.addItem(item)
        self.path_items[path] = item

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path.lower().endswith(".ts") and os.path.isfile(path):
                    self.add_path(path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        open_action = menu.addAction("Open Containing Folder")
        remove_action = menu.addAction("Remove Selected")
        chosen = menu.exec(QCursor.pos())
        if chosen == open_action:
            for item in self.selectedItems():
                folder = os.path.dirname(item.data(Qt.ItemDataRole.UserRole))
                if os.path.isdir(folder):
                    os.startfile(folder)
        elif chosen == remove_action:
            for item in self.selectedItems():
                path = item.data(Qt.ItemDataRole.UserRole)
                row = self.row(item)
                self.takeItem(row)
                self.path_items.pop(path, None)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if item:
            folder = os.path.dirname(item.data(Qt.ItemDataRole.UserRole))
            if os.path.isdir(folder):
                os.startfile(folder)
        super().mouseDoubleClickEvent(event)

    def update_progress(self, path: str, progress: int):
        """Update the progress percentage for a file.

        Args:
            path: The file path
            progress: Progress percentage (0-100)
        """
        if path not in self.path_items:
            return

        item = self.path_items[path]
        fname = QFileInfo(path).fileName()

        # Store the current progress
        item.setData(Qt.ItemDataRole.UserRole + 2, progress)

        # Update status if needed
        if progress > 0 and item.data(Qt.ItemDataRole.UserRole + 1) == "pending":
            item.setData(Qt.ItemDataRole.UserRole + 1, "processing")
            item.setForeground(self.color_processing)

        # Update the displayed text
        if progress < 100:
            item.setText(f"{fname} — {progress}%")

    def set_status(self, path: str, status: str):
        """Set the status of a file item.

        Args:
            path: The file path
            status: One of 'pending', 'processing', 'completed', 'failed'
        """
        if path not in self.path_items:
            return

        item = self.path_items[path]
        fname = QFileInfo(path).fileName()
        progress = item.data(Qt.ItemDataRole.UserRole + 2) or 0

        # Store the status
        item.setData(Qt.ItemDataRole.UserRole + 1, status)

        # Set color based on status
        if status == "pending":
            item.setForeground(self.color_pending)
            item.setText(fname)
        elif status == "processing":
            item.setForeground(self.color_processing)
            item.setText(f"{fname} — {progress}%")
        elif status == "completed":
            item.setForeground(self.color_completed)
            item.setText(f"{fname} — Completed")
            # Make the text bold
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        elif status == "failed":
            item.setForeground(self.color_failed)
            item.setText(f"{fname} — Failed")

    def get_item_status(self, path: str) -> str:
        """Get the current status of an item.

        Args:
            path: The file path

        Returns:
            Status string or empty string if path not found
        """
        if path not in self.path_items:
            return ""

        return self.path_items[path].data(Qt.ItemDataRole.UserRole + 1) or ""
    
    def add_files(self, file_paths: list) -> None:
        """Add multiple files to the list"""
        for path in file_paths:
            self.add_path(path)
    
    def remove_selected(self) -> int:
        """Remove selected items and return count of removed items"""
        selected_items = self.selectedItems()
        removed_count = 0
        
        for item in selected_items:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.path_items:
                del self.path_items[path]
                self.takeItem(self.row(item))
                removed_count += 1
        
        return removed_count
    
    def get_file_paths(self) -> list:
        """Get all file paths in the list"""
        return list(self.path_items.keys())
    
    def get_file_count(self) -> int:
        """Get the number of files in the list"""
        return len(self.path_items)
