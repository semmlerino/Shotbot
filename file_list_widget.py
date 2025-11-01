#!/usr/bin/env python3
"""
File List Widget Module for PyMPEG
A custom QListWidget with drag & drop support for TS files
"""

import os
import sys
import subprocess
from typing import Dict, Optional
from PySide6.QtCore import Qt, QFileInfo, QSize, Signal, QThreadPool, QRunnable, QObject
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QAbstractItemView, QMenu
from PySide6.QtGui import QCursor, QColor
from codec_helpers import CodecHelpers


class MetadataSignals(QObject):
    """Signals for metadata loading worker"""

    metadata_loaded = Signal(str, object)  # file_path, metadata_dict


class MetadataWorker(QRunnable):
    """Worker thread for loading video metadata without blocking UI"""

    def __init__(self, file_path: str, signals: MetadataSignals):
        super().__init__()
        self.file_path = file_path
        self.signals = signals

    def run(self):
        """Extract metadata and emit signal"""
        metadata = CodecHelpers.extract_video_metadata(self.file_path)
        self.signals.metadata_loaded.emit(self.file_path, metadata)


class FileListWidget(QListWidget):
    """Drag & drop .ts files, reorder, context menu, and track per-file items.
    Enhanced with progress display and status indicators.
    """

    # Signal emitted when file order changes
    order_changed = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.path_items: dict[str, QListWidgetItem] = {}

        # Enhanced colors for different states with better contrast
        self.color_pending = QColor(64, 64, 64)  # Dark gray - neutral
        self.color_processing = QColor(0, 122, 204)  # Professional blue
        self.color_completed = QColor(34, 139, 34)  # Forest green - success
        self.color_failed = QColor(220, 53, 69)  # Bootstrap red - error

        # Set fixed height for items
        self.setIconSize(QSize(16, 16))
        self.setSpacing(2)

        # Metadata support
        self.metadata_cache: Dict[str, Optional[Dict]] = {}
        self.thread_pool = QThreadPool()
        self.metadata_signals = MetadataSignals()
        self.metadata_signals.metadata_loaded.connect(self._on_metadata_loaded)

    def add_path(self, path: str):
        """Add a new file path to the list with pending status."""
        if path in self.path_items:
            return
        fname = QFileInfo(path).fileName()

        # Create item with initial display (metadata will be loaded asynchronously)
        item = QListWidgetItem(f"{fname} • Loading...")
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, "pending")  # Store status
        item.setData(Qt.ItemDataRole.UserRole + 2, 0)  # Store progress percentage
        item.setData(Qt.ItemDataRole.UserRole + 3, None)  # Store metadata

        # Set font for better readability
        font = item.font()
        font.setPointSize(font.pointSize() + 1)
        item.setFont(font)

        # Set tooltip with file path
        item.setToolTip(f"Path: {path}")

        self.addItem(item)
        self.path_items[path] = item

        # Start metadata loading in background
        self._load_metadata_async(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            # External file drop - add new files
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path.lower().endswith(".ts") and os.path.isfile(path):
                    self.add_path(path)
            event.acceptProposedAction()
        else:
            # Internal move - handle reordering
            super().dropEvent(event)

            # Update our path_items mapping after internal move
            self._rebuild_path_items_mapping()

            # Emit signal when order changed
            self.order_changed.emit()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        selected_items = self.selectedItems()

        if selected_items:
            # Reordering options
            move_up_action = menu.addAction("Move Up")
            move_down_action = menu.addAction("Move Down")
            menu.addSeparator()

            # File operations
            open_action = menu.addAction("Open Containing Folder")
            remove_action = menu.addAction("Remove Selected")

            # Enable/disable move actions based on selection position
            if selected_items:
                first_row = min(self.row(item) for item in selected_items)
                last_row = max(self.row(item) for item in selected_items)
                move_up_action.setEnabled(first_row > 0)
                move_down_action.setEnabled(last_row < self.count() - 1)
        else:
            # No selection - limited options
            open_action = None
            remove_action = None
            move_up_action = None
            move_down_action = None

        chosen = menu.exec(QCursor.pos())

        if chosen == move_up_action:
            self.move_selected_up()
        elif chosen == move_down_action:
            self.move_selected_down()
        elif chosen == open_action:
            for item in selected_items:
                folder = os.path.dirname(item.data(Qt.ItemDataRole.UserRole))
                if os.path.isdir(folder):
                    self._open_folder(folder)
        elif chosen == remove_action:
            for item in selected_items:
                path = item.data(Qt.ItemDataRole.UserRole)
                row = self.row(item)
                self.takeItem(row)
                self.path_items.pop(path, None)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if item:
            folder = os.path.dirname(item.data(Qt.ItemDataRole.UserRole))
            if os.path.isdir(folder):
                self._open_folder(folder)
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for reordering"""
        # Ctrl+Up - Move selected items up
        if (
            event.modifiers() == Qt.KeyboardModifier.ControlModifier
            and event.key() == Qt.Key.Key_Up
        ):
            self.move_selected_up()
            event.accept()
            return
        # Ctrl+Down - Move selected items down
        elif (
            event.modifiers() == Qt.KeyboardModifier.ControlModifier
            and event.key() == Qt.Key.Key_Down
        ):
            self.move_selected_down()
            event.accept()
            return
        # Delete - Remove selected items
        elif event.key() == Qt.Key.Key_Delete:
            self.remove_selected()
            event.accept()
            return

        # Pass other events to parent
        super().keyPressEvent(event)

    def _open_folder(self, folder: str):
        """Open folder in file manager - cross-platform"""
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                # Linux/Unix - try different file managers
                try:
                    subprocess.Popen(["xdg-open", folder])
                except FileNotFoundError:
                    # Try other common file managers
                    for manager in [
                        "gnome-open",
                        "kde-open",
                        "dolphin",
                        "nautilus",
                        "nemo",
                    ]:
                        try:
                            subprocess.Popen([manager, folder])
                            break
                        except FileNotFoundError:
                            continue
        except Exception:
            # Silently fail if we can't open the folder
            pass

    def _rebuild_path_items_mapping(self):
        """Rebuild the path_items mapping after internal reordering"""
        self.path_items.clear()

        # Rebuild mapping based on current order
        for i in range(self.count()):
            item = self.item(i)
            if item:
                path = item.data(Qt.ItemDataRole.UserRole)
                if path:
                    self.path_items[path] = item

    def update_progress(self, path: str, progress: int):
        """Update the progress percentage for a file.

        Args:
            path: The file path
            progress: Progress percentage (0-100)
        """
        if path not in self.path_items:
            return

        item = self.path_items[path]

        # Store the current progress
        item.setData(Qt.ItemDataRole.UserRole + 2, progress)

        # Update status if needed
        if progress > 0 and item.data(Qt.ItemDataRole.UserRole + 1) == "pending":
            item.setData(Qt.ItemDataRole.UserRole + 1, "processing")
            item.setForeground(self.color_processing)

        # Update the displayed text using the unified method
        self._update_item_display(path)

    def set_status(self, path: str, status: str):
        """Set the status of a file item.

        Args:
            path: The file path
            status: One of 'pending', 'processing', 'completed', 'failed'
        """
        if path not in self.path_items:
            return

        item = self.path_items[path]

        # Store the status
        item.setData(Qt.ItemDataRole.UserRole + 1, status)

        # Set color based on status
        if status == "pending":
            item.setForeground(self.color_pending)
        elif status == "processing":
            item.setForeground(self.color_processing)
        elif status == "completed":
            item.setForeground(self.color_completed)
            # Make the text bold
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        elif status == "failed":
            item.setForeground(self.color_failed)

        # Update the displayed text using the unified method
        self._update_item_display(path)

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

    def get_file_paths_in_order(self) -> list[str]:
        """Get all file paths in current display order"""
        paths = []
        for i in range(self.count()):
            item = self.item(i)
            if item:
                path = item.data(Qt.ItemDataRole.UserRole)
                if path:
                    paths.append(path)
        return paths

    def get_pending_files_in_order(self) -> list[str]:
        """Get only pending file paths in current display order"""
        paths = []
        for i in range(self.count()):
            item = self.item(i)
            if item:
                path = item.data(Qt.ItemDataRole.UserRole)
                status = item.data(Qt.ItemDataRole.UserRole + 1)
                if path and status == "pending":
                    paths.append(path)
        return paths

    def move_selected_up(self):
        """Move selected items up in the list"""
        selected_items = self.selectedItems()
        if not selected_items:
            return

        # Get row indices and sort them
        rows = [self.row(item) for item in selected_items]
        rows.sort()

        # Can't move up if first item is selected
        if rows[0] == 0:
            return

        # Move each item up
        for row in rows:
            item = self.takeItem(row)
            self.insertItem(row - 1, item)

        # Update selection
        self.clearSelection()
        for row in rows:
            self.item(row - 1).setSelected(True)

        # Rebuild mapping
        self._rebuild_path_items_mapping()

        # Emit order changed signal
        self.order_changed.emit()

    def move_selected_down(self):
        """Move selected items down in the list"""
        selected_items = self.selectedItems()
        if not selected_items:
            return

        # Get row indices and sort them in reverse
        rows = [self.row(item) for item in selected_items]
        rows.sort(reverse=True)

        # Can't move down if last item is selected
        if rows[0] == self.count() - 1:
            return

        # Move each item down
        for row in rows:
            item = self.takeItem(row)
            self.insertItem(row + 1, item)

        # Update selection
        self.clearSelection()
        for row in reversed(rows):
            self.item(row + 1).setSelected(True)

        # Rebuild mapping
        self._rebuild_path_items_mapping()

        # Emit order changed signal
        self.order_changed.emit()

    def get_file_paths(self) -> list:
        """Get all file paths in the list"""
        return list(self.path_items.keys())

    def get_file_count(self) -> int:
        """Get the number of files in the list"""
        return len(self.path_items)

    def _load_metadata_async(self, path: str):
        """Load metadata for a file asynchronously"""
        if path in self.metadata_cache:
            # Already loaded or loading
            return

        # Mark as loading
        self.metadata_cache[path] = None

        # Create worker and submit to thread pool
        worker = MetadataWorker(path, self.metadata_signals)
        self.thread_pool.start(worker)

    def _on_metadata_loaded(self, file_path: str, metadata: Optional[Dict]):
        """Handle metadata loading completion"""
        # Store metadata in cache
        self.metadata_cache[file_path] = metadata

        # Update the display for this file
        self._update_item_display(file_path)

    def _update_item_display(self, path: str):
        """Update the display text for a file item based on its current state"""
        if path not in self.path_items:
            return

        item = self.path_items[path]
        fname = QFileInfo(path).fileName()
        status = item.data(Qt.ItemDataRole.UserRole + 1) or "pending"
        progress = item.data(Qt.ItemDataRole.UserRole + 2) or 0
        metadata = self.metadata_cache.get(path)

        # Build display text based on status with visual indicators
        if status == "pending":
            if metadata:
                # Show metadata for pending files
                display_text = f"⏳ {self._format_file_with_metadata(fname, metadata)}"
            else:
                # Still loading metadata
                display_text = f"🔄 {fname} • Loading..."
        elif status == "processing":
            # Show progress for processing files with progress indicator and metadata
            if metadata:
                display_text = f"🚀 {self._format_file_with_metadata(fname, metadata)} — {progress}%"
            else:
                display_text = f"🚀 {fname} — {progress}%"
        elif status == "completed":
            # Show completed status
            display_text = f"✅ {fname} — Completed"
        elif status == "failed":
            # Show failed status
            display_text = f"❌ {fname} — Failed"
        else:
            display_text = fname

        item.setText(display_text)

        # Store metadata in item for easy access
        item.setData(Qt.ItemDataRole.UserRole + 3, metadata)

        # Update tooltip with rich information
        tooltip_lines = [f"Path: {path}"]

        if metadata:
            if metadata.get("duration") != "Unknown":
                tooltip_lines.append(f"Duration: {metadata['duration']}")
            if metadata.get("width", 0) > 0 and metadata.get("height", 0) > 0:
                tooltip_lines.append(
                    f"Resolution: {metadata['width']}x{metadata['height']}"
                )
            if metadata.get("codec", "").upper() not in ["", "UNKNOWN"]:
                tooltip_lines.append(f"Codec: {metadata['codec']}")
            if metadata.get("bitrate", "") not in ["", "Unknown"]:
                tooltip_lines.append(f"Bitrate: {metadata['bitrate']}")
            if metadata.get("format_name", "") not in ["", "Unknown"]:
                tooltip_lines.append(f"Format: {metadata['format_name']}")

        tooltip_lines.append(f"Status: {status.title()}")
        if status == "processing" and progress > 0:
            tooltip_lines.append(f"Progress: {progress}%")

        item.setToolTip("\n".join(tooltip_lines))

    def _format_file_with_metadata(self, filename: str, metadata: Dict) -> str:
        """Format filename with metadata for display"""
        parts = [filename]

        # Add duration
        if metadata.get("duration") != "Unknown":
            parts.append(metadata["duration"])

        # Add resolution
        width = metadata.get("width", 0)
        height = metadata.get("height", 0)
        if width > 0 and height > 0:
            parts.append(f"{width}x{height}")

        # Add codec
        codec = metadata.get("codec", "").upper()
        if codec and codec != "UNKNOWN":
            parts.append(codec)

        # Add bitrate
        bitrate = metadata.get("bitrate", "")
        if bitrate and bitrate != "Unknown":
            parts.append(bitrate)

        return " • ".join(parts)

    def get_file_metadata(self, path: str) -> Optional[Dict]:
        """Get cached metadata for a file"""
        return self.metadata_cache.get(path)

    def update_all_display_with_settings(self, codec_idx: int, crf_value: int):
        """Update all file displays with estimated output sizes"""
        for path in self.path_items:
            metadata = self.metadata_cache.get(path)
            if metadata:
                # Add estimated size to metadata display
                estimated_size = CodecHelpers.estimate_output_size(
                    metadata, codec_idx, crf_value
                )
                if estimated_size:
                    item = self.path_items[path]
                    current_text = item.text()
                    # Remove old size estimate if present
                    if " • Est:" in current_text:
                        current_text = current_text.split(" • Est:")[0]
                    item.setText(f"{current_text} • Est: {estimated_size}")

    def get_total_estimated_size(self, codec_idx: int, crf_value: int) -> str:
        """Calculate total estimated output size for all files"""
        total_bytes = 0
        count = 0

        for path in self.path_items:
            metadata = self.metadata_cache.get(path)
            if metadata and metadata.get("duration_seconds", 0) > 0:
                estimated_size = CodecHelpers.estimate_output_size(
                    metadata, codec_idx, crf_value
                )
                if estimated_size:
                    # Parse size back to bytes for summation
                    size_bytes = self._parse_size_to_bytes(estimated_size)
                    if size_bytes > 0:
                        total_bytes += size_bytes
                        count += 1

        if count == 0:
            return "Calculating..."

        return CodecHelpers._format_file_size(total_bytes)

    def _parse_size_to_bytes(self, size_str: str) -> float:
        """Parse a size string back to bytes"""
        size_str = size_str.strip()
        if size_str.endswith(" GB"):
            return float(size_str[:-3]) * 1024 * 1024 * 1024
        elif size_str.endswith(" MB"):
            return float(size_str[:-3]) * 1024 * 1024
        elif size_str.endswith(" KB"):
            return float(size_str[:-3]) * 1024
        elif size_str.endswith(" B"):
            return float(size_str[:-2])
        return 0

    # Batch Operations
    def select_all_files(self):
        """Select all files in the list"""
        self.selectAll()

    def clear_completed_files(self) -> int:
        """Remove all completed files from the list"""
        completed_paths = []

        for path, item in self.path_items.items():
            status = item.data(Qt.ItemDataRole.UserRole + 1)
            if status == "completed":
                completed_paths.append(path)

        # Remove completed files
        for path in completed_paths:
            if path in self.path_items:
                item = self.path_items[path]
                row = self.row(item)
                self.takeItem(row)
                del self.path_items[path]
                # Also remove from metadata cache
                self.metadata_cache.pop(path, None)

        return len(completed_paths)

    def remove_failed_files(self) -> int:
        """Remove all failed files from the list"""
        failed_paths = []

        for path, item in self.path_items.items():
            status = item.data(Qt.ItemDataRole.UserRole + 1)
            if status == "failed":
                failed_paths.append(path)

        # Remove failed files
        for path in failed_paths:
            if path in self.path_items:
                item = self.path_items[path]
                row = self.row(item)
                self.takeItem(row)
                del self.path_items[path]
                # Also remove from metadata cache
                self.metadata_cache.pop(path, None)

        return len(failed_paths)

    def get_files_by_status(self, status: str) -> list[str]:
        """Get all file paths with the specified status"""
        files = []
        for path, item in self.path_items.items():
            item_status = item.data(Qt.ItemDataRole.UserRole + 1)
            if item_status == status:
                files.append(path)
        return files

    def get_status_counts(self) -> Dict[str, int]:
        """Get count of files by status"""
        counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}

        for item in self.path_items.values():
            status = item.data(Qt.ItemDataRole.UserRole + 1) or "pending"
            if status in counts:
                counts[status] += 1

        return counts

    def refresh_drag_drop_state(self):
        """Refresh drag-and-drop functionality - useful after conversions complete"""
        # Ensure drag-and-drop settings are properly enabled
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        
        # Clear any potential focus issues that might interfere with drag-and-drop
        self.clearFocus()
        self.setFocus()
