#!/usr/bin/env python3
import base64
import io
import os
import platform
import sys
import tarfile

# Try PySide2 first, fall back to PySide6
try:
    from PySide2.QtCore import QMimeData, QSize, Qt, QThread, QTimer, Signal
    from PySide2.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QPalette
    from PySide2.QtWidgets import (
        QApplication,
        QCheckBox,
        QFileDialog,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QTabWidget,
        QTextEdit,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )

    PYSIDE_VERSION = "PySide2"
except ImportError:
    try:
        from PySide6.QtCore import QMimeData, QSize, Qt, QThread, QTimer, Signal
        from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QPalette
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QFileDialog,
            QFrame,
            QGridLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QMessageBox,
            QProgressBar,
            QPushButton,
            QScrollArea,
            QSizePolicy,
            QSpinBox,
            QTabWidget,
            QTextEdit,
            QToolButton,
            QVBoxLayout,
            QWidget,
        )

        PYSIDE_VERSION = "PySide6"
    except ImportError:
        print("Error: Neither PySide2 nor PySide6 is installed.")
        print("Please install one of them using:")
        print("  pip install PySide2")
        print("  or")
        print("  pip install PySide6")
        sys.exit(1)

# Compatibility layer for PySide2/PySide6 differences
if PYSIDE_VERSION == "PySide6":
    # PySide6 uses Qt.AlignmentFlag.AlignCenter
    AlignCenter = Qt.AlignmentFlag.AlignCenter
    AlignTop = Qt.AlignmentFlag.AlignTop
    AlignLeft = Qt.AlignmentFlag.AlignLeft
    # PySide6 uses Qt.MouseButton.LeftButton
    LeftButton = Qt.MouseButton.LeftButton
    # PySide6 uses Qt.CursorShape.PointingHandCursor
    PointingHandCursor = Qt.CursorShape.PointingHandCursor
    # PySide6 uses Qt.FocusPolicy.StrongFocus
    StrongFocus = Qt.FocusPolicy.StrongFocus
    # PySide6 uses exec() instead of exec_()
    exec_app = lambda app: app.exec()
else:
    # PySide2 uses Qt.AlignCenter directly
    AlignCenter = Qt.AlignCenter
    AlignTop = Qt.AlignTop
    AlignLeft = Qt.AlignLeft
    # PySide2 uses Qt.LeftButton
    LeftButton = Qt.LeftButton
    # PySide2 uses Qt.PointingHandCursor
    PointingHandCursor = Qt.PointingHandCursor
    # PySide2 uses Qt.StrongFocus
    StrongFocus = Qt.StrongFocus
    # PySide2 uses exec_()
    exec_app = lambda app: app.exec_()


class EncoderThread(QThread):
    progress = Signal(int)
    chunk_ready = Signal(str, int, int)
    finished = Signal()
    error = Signal(str)
    status = Signal(str)

    def __init__(self, folder_path, chunk_size):
        super().__init__()
        self.folder_path = folder_path
        # Don't adjust chunk size - use exact requested size
        self.chunk_size = chunk_size

    def run(self):
        try:
            # Create tar archive in memory
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
                tar.add(self.folder_path, arcname=os.path.basename(self.folder_path))

            # Encode to base64
            tar_buffer.seek(0)
            tar_bytes = tar_buffer.read()
            encoded = base64.b64encode(tar_bytes).decode("utf-8")

            # For chunk size calculation, we need to consider characters not bytes
            # Since base64 is ASCII, 1 character = 1 byte
            chunk_size_chars = self.chunk_size * 1024  # Convert KB to characters

            # Split into chunks
            total_chunks = (len(encoded) + chunk_size_chars - 1) // chunk_size_chars

            self.status.emit(
                f"Encoded size: {len(encoded)} chars, creating {total_chunks} chunks"
            )

            for i in range(total_chunks):
                start = i * chunk_size_chars
                end = min((i + 1) * chunk_size_chars, len(encoded))
                chunk = encoded[start:end]

                # Add header with chunk info
                chunk_data = f"FOLDER_TRANSFER_V1|{i + 1}|{total_chunks}|{os.path.basename(self.folder_path)}\n{chunk}"

                self.chunk_ready.emit(chunk_data, i + 1, total_chunks)
                self.progress.emit(int((i + 1) / total_chunks * 100))

            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))


class FileLoaderThread(QThread):
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)
    status = Signal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            # Get file size
            file_size = os.path.getsize(self.file_path)
            self.status.emit(
                f"Loading file: {os.path.basename(self.file_path)} ({file_size / 1024 / 1024:.1f} MB)"
            )

            # Read file in chunks for large files
            chunk_size = 1024 * 1024  # 1MB chunks
            bytes_read = 0
            content_parts = []

            with open(self.file_path, "r", encoding="utf-8") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    content_parts.append(chunk)
                    bytes_read += len(chunk.encode("utf-8"))
                    progress = int(bytes_read / file_size * 100)
                    self.progress.emit(progress)

            # Combine all parts
            content = "".join(content_parts)
            self.finished.emit(content)

        except Exception as e:
            self.error.emit(str(e))


class DecoderThread(QThread):
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)
    status = Signal(str)

    def __init__(self, chunks, output_dir):
        super().__init__()
        self.chunks = chunks
        self.output_dir = output_dir

    def run(self):
        try:
            # Combine chunks
            self.status.emit("Combining chunks...")
            encoded_data = "".join(self.chunks)
            self.progress.emit(25)

            # Validate base64 data
            self.status.emit(f"Validating data ({len(encoded_data)} bytes)...")
            # Don't filter - trust the data as is
            # Any filtering can corrupt the base64 encoding

            # Decode from base64
            self.status.emit("Decoding base64...")
            try:
                # Ensure proper padding for base64
                padding = len(encoded_data) % 4
                if padding:
                    encoded_data += "=" * (4 - padding)

                tar_data = base64.b64decode(encoded_data)
                self.progress.emit(50)
                self.status.emit(f"Decoded to {len(tar_data)} bytes")
            except Exception as e:
                self.error.emit(
                    f"Base64 decode error: {str(e)}\nData length: {len(encoded_data)}"
                )
                return

            # Extract tar archive
            self.status.emit(f"Extracting archive ({len(tar_data)} bytes)...")
            tar_buffer = io.BytesIO(tar_data)

            try:
                with tarfile.open(fileobj=tar_buffer, mode="r:gz") as tar:
                    # List contents first
                    members = tar.getmembers()
                    self.status.emit(f"Found {len(members)} items in archive")
                    self.progress.emit(75)

                    # Extract
                    tar.extractall(path=self.output_dir)
                    self.progress.emit(100)

            except tarfile.TarError as e:
                # Try without gzip compression
                self.status.emit("Trying uncompressed tar...")
                tar_buffer.seek(0)
                try:
                    with tarfile.open(fileobj=tar_buffer, mode="r:") as tar:
                        tar.extractall(path=self.output_dir)
                        self.progress.emit(100)
                except Exception as e2:
                    self.error.emit(f"Archive extraction failed: {str(e)} / {str(e2)}")
                    return

            self.finished.emit(self.output_dir)

        except Exception as e:
            self.error.emit(f"Unexpected error: {str(e)}")


class DropAreaLabel(QLabel):
    folder_dropped = Signal(str)

    def __init__(self, text):
        super().__init__(text)
        self.setAcceptDrops(True)
        self.default_style = """
            QLabel {
                border: 2px dashed #444;
                border-radius: 10px;
                padding: 40px;
                font-size: 16px;
                background-color: #1e1e1e;
            }
        """
        self.hover_style = """
            QLabel {
                border: 2px dashed #14ffec;
                border-radius: 10px;
                padding: 40px;
                font-size: 16px;
                background-color: #0d7377;
                color: #ffffff;
            }
        """
        self.setStyleSheet(self.default_style)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            # Check if any URL is a directory
            for url in event.mimeData().urls():
                if os.path.isdir(url.toLocalFile()):
                    event.acceptProposedAction()
                    self.setStyleSheet(self.hover_style)
                    self.setText("Drop folder here!")
                    return
            event.ignore()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self.default_style)
        self.setText("Drag and drop a folder here or click Browse")

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self.default_style)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                self.folder_dropped.emit(path)
                break
        self.setText("Drag and drop a folder here or click Browse")


class FileDropAreaLabel(QLabel):
    file_dropped = Signal(str)

    def __init__(self, text):
        super().__init__(text)
        self.setAcceptDrops(True)
        self.default_style = """
            QLabel {
                border: 2px dashed #444;
                border-radius: 10px;
                padding: 30px;
                font-size: 14px;
                background-color: #1e1e1e;
                min-height: 100px;
            }
        """
        self.hover_style = """
            QLabel {
                border: 2px dashed #14ffec;
                border-radius: 10px;
                padding: 30px;
                font-size: 14px;
                background-color: #0d7377;
                color: #ffffff;
                min-height: 100px;
            }
        """
        self.setStyleSheet(self.default_style)
        self.setAlignment(AlignCenter)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            # Check if any URL is a file (not directory)
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if os.path.isfile(path) and path.lower().endswith(
                    (".txt", ".base64", ".b64")
                ):
                    event.acceptProposedAction()
                    self.setStyleSheet(self.hover_style)
                    self.setText("Drop file here!")
                    return
            event.ignore()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self.default_style)
        self.setText("Drag and drop a base64 file here\n(.txt, .base64, .b64)")

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self.default_style)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path) and path.lower().endswith(
                (".txt", ".base64", ".b64")
            ):
                self.file_dropped.emit(path)
                break
        self.setText("Drag and drop a base64 file here\n(.txt, .base64, .b64)")


class DragDropWidget(QWidget):
    folder_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                self.folder_dropped.emit(path)
                break


class FolderIconWidget(QFrame):
    removed = Signal(str)
    selected = Signal(str)

    def __init__(self, folder_path):
        super().__init__()
        self.folder_path = folder_path
        self.folder_name = os.path.basename(folder_path)
        self.folder_size = self.get_folder_size()
        self.is_selected = False
        self.init_ui()

    def init_ui(self):
        self.setFixedSize(120, 140)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setCursor(PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)

        # Folder icon (using Unicode emoji)
        icon_label = QLabel("📁")
        icon_label.setAlignment(AlignCenter)
        icon_label.setStyleSheet("font-size: 48px;")
        layout.addWidget(icon_label)

        # Folder name
        name_label = QLabel(
            self.folder_name[:15] + "..."
            if len(self.folder_name) > 15
            else self.folder_name
        )
        name_label.setAlignment(AlignCenter)
        name_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        # Size label
        size_mb = self.folder_size / (1024 * 1024)
        size_label = QLabel(f"{size_mb:.1f} MB")
        size_label.setAlignment(AlignCenter)
        size_label.setStyleSheet("font-size: 10px; color: #888;")
        layout.addWidget(size_label)

        # Remove button
        remove_btn = QToolButton()
        remove_btn.setText("✕")
        remove_btn.setStyleSheet("""
            QToolButton {
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 12px;
                font-weight: bold;
                width: 20px;
                height: 20px;
            }
            QToolButton:hover {
                background-color: #ff4444;
            }
        """)
        remove_btn.clicked.connect(lambda: self.removed.emit(self.folder_path))

        # Position remove button in top-right corner
        remove_btn.setParent(self)
        remove_btn.move(95, 5)
        remove_btn.raise_()

        self.update_style()

    def get_folder_size(self):
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(self.folder_path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.exists(fp):
                        total_size += os.path.getsize(fp)
        except:
            pass
        return total_size

    def mousePressEvent(self, event):
        if event.button() == LeftButton:
            self.is_selected = not self.is_selected
            self.update_style()
            self.selected.emit(self.folder_path)

    def update_style(self):
        if self.is_selected:
            self.setStyleSheet("""
                QFrame {
                    background-color: #0d7377;
                    border: 2px solid #14ffec;
                    border-radius: 10px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #3d3d3d;
                    border: 1px solid #555;
                    border-radius: 10px;
                }
                QFrame:hover {
                    background-color: #4d4d4d;
                    border: 1px solid #14ffec;
                }
            """)

    def set_selected(self, selected):
        self.is_selected = selected
        self.update_style()


class FolderGridWidget(QWidget):
    folders_changed = Signal(list)

    def __init__(self):
        super().__init__()
        self.folder_widgets = {}
        self.selected_folders = set()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #2d2d2d;
            }
            QScrollBar:vertical {
                background-color: #2d2d2d;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666;
            }
        """)

        # Container widget
        self.container = QWidget()
        self.grid_layout = QGridLayout(self.container)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setAlignment(AlignTop | AlignLeft)

        scroll.setWidget(self.container)
        layout.addWidget(scroll)

    def add_folder(self, folder_path):
        if folder_path in self.folder_widgets:
            return  # Already added

        # Create folder widget
        folder_widget = FolderIconWidget(folder_path)
        folder_widget.removed.connect(self.remove_folder)
        folder_widget.selected.connect(self.toggle_folder_selection)

        # Add to grid
        count = len(self.folder_widgets)
        row = count // 5  # 5 columns
        col = count % 5

        self.grid_layout.addWidget(folder_widget, row, col)
        self.folder_widgets[folder_path] = folder_widget

        # Auto-select the newly added folder
        self.selected_folders.add(folder_path)
        folder_widget.set_selected(True)

        self.folders_changed.emit(self.get_selected_folders())

    def remove_folder(self, folder_path):
        if folder_path not in self.folder_widgets:
            return

        # Remove widget
        widget = self.folder_widgets[folder_path]
        self.grid_layout.removeWidget(widget)
        widget.deleteLater()

        del self.folder_widgets[folder_path]
        self.selected_folders.discard(folder_path)

        # Reorganize grid
        self.reorganize_grid()
        self.folders_changed.emit(self.get_selected_folders())

    def toggle_folder_selection(self, folder_path):
        if folder_path in self.selected_folders:
            self.selected_folders.remove(folder_path)
        else:
            self.selected_folders.add(folder_path)

        self.folders_changed.emit(self.get_selected_folders())

    def get_selected_folders(self):
        return list(self.selected_folders)

    def clear_all(self):
        for widget in self.folder_widgets.values():
            widget.deleteLater()
        self.folder_widgets.clear()
        self.selected_folders.clear()
        self.folders_changed.emit([])

    def reorganize_grid(self):
        # Remove all widgets from grid
        for widget in self.folder_widgets.values():
            self.grid_layout.removeWidget(widget)

        # Re-add in order
        for i, (path, widget) in enumerate(self.folder_widgets.items()):
            row = i // 5
            col = i % 5
            self.grid_layout.addWidget(widget, row, col)


class FolderTransferApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.chunks_data = {}
        self.current_chunks = []
        self.selected_folders = []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(f"Folder Transfer Tool ({PYSIDE_VERSION})")
        self.setGeometry(100, 100, 900, 700)

        # Set modern dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QPushButton {
                background-color: #0d7377;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #14ffec;
                color: #1e1e1e;
            }
            QPushButton:pressed {
                background-color: #0a5d61;
            }
            QTextEdit {
                background-color: #1e1e1e;
                border: 1px solid #444;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }
            QTabWidget::pane {
                border: 1px solid #444;
                background-color: #2d2d2d;
            }
            QTabBar::tab {
                background-color: #1e1e1e;
                padding: 10px 20px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #0d7377;
            }
            QGroupBox {
                border: 1px solid #444;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                padding: 0 10px;
                background-color: #2d2d2d;
            }
            QProgressBar {
                border: 1px solid #444;
                border-radius: 5px;
                text-align: center;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #0d7377;
                border-radius: 5px;
            }
            QLabel {
                font-size: 14px;
            }
            QSpinBox {
                background-color: #1e1e1e;
                border: 1px solid #444;
                padding: 5px;
                border-radius: 3px;
            }
        """)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Title
        title = QLabel("Folder Transfer Tool")
        title.setAlignment(AlignCenter)
        title.setStyleSheet(
            "font-size: 24px; font-weight: bold; padding: 20px; color: #14ffec;"
        )
        main_layout.addWidget(title)

        # Tab widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Encode tab
        self.encode_tab = self.create_encode_tab()
        self.tabs.addTab(self.encode_tab, "Encode Folder")

        # Decode tab
        self.decode_tab = self.create_decode_tab()
        self.tabs.addTab(self.decode_tab, "Decode Folder")

        # Status bar
        self.statusBar().showMessage("Ready")
        self.statusBar().setStyleSheet("background-color: #1e1e1e; color: #14ffec;")

    def create_encode_tab(self):
        widget = DragDropWidget()
        layout = QVBoxLayout(widget)

        # Drag and drop area
        drop_group = QGroupBox("Select Folder")
        drop_layout = QVBoxLayout(drop_group)

        self.drop_label = DropAreaLabel("Drag and drop a folder here or click Browse")
        self.drop_label.setAlignment(AlignCenter)
        self.drop_label.folder_dropped.connect(self.folder_dropped)
        drop_layout.addWidget(self.drop_label)

        browse_btn = QPushButton("Browse Folder")
        browse_btn.clicked.connect(self.browse_folder)
        drop_layout.addWidget(browse_btn)

        layout.addWidget(drop_group)

        # Folder grid
        folders_group = QGroupBox("Selected Folders")
        folders_layout = QVBoxLayout(folders_group)

        self.folder_grid = FolderGridWidget()
        self.folder_grid.folders_changed.connect(self.on_folders_changed)
        self.folder_grid.setMinimumHeight(200)
        folders_layout.addWidget(self.folder_grid)

        # Folder count label
        self.folder_count_label = QLabel("No folders selected")
        self.folder_count_label.setStyleSheet(
            "color: #14ffec; padding: 10px; font-weight: bold;"
        )
        self.folder_count_label.setAlignment(AlignCenter)
        folders_layout.addWidget(self.folder_count_label)

        layout.addWidget(folders_group)

        # Settings
        settings_group = QGroupBox("Settings")
        settings_layout = QVBoxLayout(settings_group)

        # Chunk size controls
        chunk_layout = QHBoxLayout()
        chunk_layout.addWidget(QLabel("Chunk size:"))

        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(10, 50000)  # Up to 50MB
        self.chunk_size_spin.setValue(100)
        self.chunk_size_spin.setSuffix(" KB")
        self.chunk_size_spin.setStyleSheet("""
            QSpinBox {
                min-width: 100px;
            }
        """)
        chunk_layout.addWidget(self.chunk_size_spin)

        # Preset buttons
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Presets:"))

        # Create preset buttons with lambda to capture value
        presets = [
            ("100 KB", 100),
            ("500 KB", 500),
            ("1 MB", 1024),
            ("5 MB", 5120),
            ("10 MB", 10240),
            ("25 MB", 25600),
        ]

        for label, size in presets:
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.clicked.connect(
                lambda checked=False, s=size: self.chunk_size_spin.setValue(s)
            )
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #444;
                    border: 1px solid #555;
                    padding: 5px 10px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #555;
                    border: 1px solid #14ffec;
                }
            """)
            preset_layout.addWidget(btn)

        preset_layout.addStretch()

        chunk_layout.addStretch()
        settings_layout.addLayout(chunk_layout)
        settings_layout.addLayout(preset_layout)

        # Other settings
        other_layout = QHBoxLayout()
        self.auto_copy_check = QCheckBox("Auto-copy chunks to clipboard")
        self.auto_copy_check.setChecked(True)
        other_layout.addWidget(self.auto_copy_check)

        # Add size display
        self.chunk_size_label = QLabel()
        self.update_chunk_size_label()
        self.chunk_size_spin.valueChanged.connect(self.update_chunk_size_label)
        other_layout.addStretch()
        other_layout.addWidget(self.chunk_size_label)

        settings_layout.addLayout(other_layout)

        layout.addWidget(settings_group)

        # Action buttons
        button_layout = QHBoxLayout()

        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self.clear_folders)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #ff4444;
            }
        """)
        button_layout.addWidget(clear_btn)

        button_layout.addStretch()

        self.encode_btn = QPushButton("Encode Selected Folders")
        self.encode_btn.clicked.connect(self.encode_folders)
        self.encode_btn.setEnabled(False)
        button_layout.addWidget(self.encode_btn)

        layout.addLayout(button_layout)

        # Progress
        self.encode_progress = QProgressBar()
        self.encode_progress.setVisible(False)
        layout.addWidget(self.encode_progress)

        # Output
        output_group = QGroupBox("Encoded Output")
        output_layout = QVBoxLayout(output_group)

        self.encode_output = QTextEdit()
        self.encode_output.setReadOnly(True)
        output_layout.addWidget(self.encode_output)

        # Chunk navigation
        chunk_nav_layout = QHBoxLayout()
        self.prev_chunk_btn = QPushButton("← Previous Chunk")
        self.prev_chunk_btn.clicked.connect(self.prev_chunk)
        self.prev_chunk_btn.setEnabled(False)
        chunk_nav_layout.addWidget(self.prev_chunk_btn)

        self.chunk_label = QLabel("Chunk 0/0")
        self.chunk_label.setAlignment(AlignCenter)
        self.chunk_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        chunk_nav_layout.addWidget(self.chunk_label)

        self.next_chunk_btn = QPushButton("Next Chunk →")
        self.next_chunk_btn.clicked.connect(self.next_chunk)
        self.next_chunk_btn.setEnabled(False)
        chunk_nav_layout.addWidget(self.next_chunk_btn)

        self.copy_chunk_btn = QPushButton("Copy Current Chunk")
        self.copy_chunk_btn.clicked.connect(self.copy_current_chunk)
        self.copy_chunk_btn.setEnabled(False)
        chunk_nav_layout.addWidget(self.copy_chunk_btn)

        output_layout.addLayout(chunk_nav_layout)

        layout.addWidget(output_group)

        # Connect drag and drop
        widget.folder_dropped.connect(self.folder_dropped)

        return widget

    def create_decode_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # File drop area
        file_drop_group = QGroupBox("Load from File")
        file_drop_layout = QVBoxLayout(file_drop_group)

        self.file_drop_label = FileDropAreaLabel(
            "Drag and drop a base64 file here\n(.txt, .base64, .b64)"
        )
        self.file_drop_label.file_dropped.connect(self.load_chunk_from_file)
        file_drop_layout.addWidget(self.file_drop_label)

        file_browse_btn = QPushButton("Browse for File")
        file_browse_btn.clicked.connect(self.browse_chunk_file)
        file_drop_layout.addWidget(file_browse_btn)

        layout.addWidget(file_drop_group)

        # Input area
        input_group = QGroupBox("Or Paste Encoded Chunks")
        input_layout = QVBoxLayout(input_group)

        info_label = QLabel(
            "Paste each chunk here and click 'Add Chunk'. The tool will automatically detect chunk order."
        )
        info_label.setWordWrap(True)
        input_layout.addWidget(info_label)

        self.decode_input = QTextEdit()
        self.decode_input.setPlaceholderText("Paste encoded chunk here...")
        self.decode_input.setMaximumHeight(150)
        input_layout.addWidget(self.decode_input)

        chunk_buttons_layout = QHBoxLayout()

        add_chunk_btn = QPushButton("Add Chunk")
        add_chunk_btn.clicked.connect(self.add_chunk)
        chunk_buttons_layout.addWidget(add_chunk_btn)

        clear_chunks_btn = QPushButton("Clear All Chunks")
        clear_chunks_btn.clicked.connect(self.clear_decode_chunks)
        clear_chunks_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #ff4444;
            }
        """)
        chunk_buttons_layout.addWidget(clear_chunks_btn)

        input_layout.addLayout(chunk_buttons_layout)

        layout.addWidget(input_group)

        # Chunks status
        status_group = QGroupBox("Chunks Status")
        status_layout = QVBoxLayout(status_group)

        self.chunks_status_label = QLabel("No chunks added")
        self.chunks_status_label.setStyleSheet("font-size: 16px; padding: 10px;")
        status_layout.addWidget(self.chunks_status_label)

        self.chunks_list = QTextEdit()
        self.chunks_list.setReadOnly(True)
        self.chunks_list.setMaximumHeight(100)
        status_layout.addWidget(self.chunks_list)

        layout.addWidget(status_group)

        # Output directory
        output_dir_layout = QHBoxLayout()
        output_dir_layout.addWidget(QLabel("Output Directory:"))

        self.output_dir_label = QLabel(os.path.expanduser("~/Desktop"))
        self.output_dir_label.setStyleSheet("color: #14ffec;")
        output_dir_layout.addWidget(self.output_dir_label)

        browse_output_btn = QPushButton("Browse")
        browse_output_btn.clicked.connect(self.browse_output_dir)
        output_dir_layout.addWidget(browse_output_btn)

        layout.addLayout(output_dir_layout)

        # Decode button - use different approach for Linux PySide2
        if platform.system() == "Linux" and PYSIDE_VERSION == "PySide2":
            # Create a container widget for better control
            button_container = QWidget()
            button_layout = QVBoxLayout(button_container)
            button_layout.setContentsMargins(0, 0, 0, 0)

            self.decode_btn = QPushButton("Decode Folder")
            self.decode_btn.setMinimumHeight(40)
            self.decode_btn.setEnabled(True)  # Start enabled to avoid issues
            self.decode_btn.setVisible(False)  # But hidden
            self.decode_btn.clicked.connect(self.decode_folder)

            # Alternative clickable label for Linux PySide2
            self.decode_label = QLabel("Decode Folder")
            self.decode_label.setAlignment(AlignCenter)
            self.decode_label.setMinimumHeight(40)
            self.decode_label.setStyleSheet("""
                QLabel {
                    background-color: #444;
                    color: #888;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 14px;
                }
            """)
            self.decode_label.mousePressEvent = self._decode_label_click

            button_layout.addWidget(self.decode_label)
            button_layout.addWidget(self.decode_btn)
            layout.addWidget(button_container)

            # Track decode state
            self._can_decode = False
        else:
            # Normal button for other platforms
            self.decode_btn = QPushButton("Decode Folder")
            self.decode_btn.clicked.connect(self.decode_folder)
            self.decode_btn.setEnabled(False)
            self.decode_btn.setMinimumHeight(40)
            self.decode_btn.setStyleSheet("""
                QPushButton:disabled {
                    background-color: #444;
                    color: #888;
                }
            """)
            layout.addWidget(self.decode_btn)
            self.decode_label = None

        print(f"Platform: {platform.system()}, PySide: {PYSIDE_VERSION}")
        print(f"Using alternative label: {self.decode_label is not None}")

        # Progress
        self.decode_progress = QProgressBar()
        self.decode_progress.setVisible(False)
        layout.addWidget(self.decode_progress)

        layout.addStretch()

        return widget

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Encode")
        if folder:
            self.folder_dropped(folder)

    def get_folder_size(self, folder_path):
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total_size += os.path.getsize(fp)
        return total_size

    def reset_drop_label(self):
        self.drop_label.setText("Drag and drop a folder here or click Browse")
        self.drop_label.setStyleSheet(self.drop_label.default_style)

    def folder_dropped(self, folder_path):
        # Add folder to grid
        self.folder_grid.add_folder(folder_path)

        folder_name = os.path.basename(folder_path)

        # Update drop area to show success
        self.drop_label.setText(f"✓ Added {folder_name}")
        self.drop_label.setStyleSheet("""
            QLabel {
                border: 2px solid #14ffec;
                border-radius: 10px;
                padding: 40px;
                font-size: 16px;
                background-color: #0a5d61;
                color: #14ffec;
                font-weight: bold;
            }
        """)

        # Reset drop label after 1 second
        QTimer.singleShot(1000, self.reset_drop_label)

        self.statusBar().showMessage(f"Added folder: {folder_path}")

    def on_folders_changed(self, selected_folders):
        self.selected_folders = selected_folders
        count = len(selected_folders)

        if count == 0:
            self.folder_count_label.setText("No folders selected")
            self.encode_btn.setEnabled(False)
            self.encode_btn.setStyleSheet("")
        elif count == 1:
            self.folder_count_label.setText("1 folder selected")
            self.encode_btn.setEnabled(True)
            self.encode_btn.setStyleSheet("""
                QPushButton {
                    background-color: #14ffec;
                    color: #1e1e1e;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 14px;
                }
            """)
        else:
            self.folder_count_label.setText(f"{count} folders selected")
            self.encode_btn.setEnabled(True)
            self.encode_btn.setStyleSheet("""
                QPushButton {
                    background-color: #14ffec;
                    color: #1e1e1e;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 14px;
                }
            """)

    def clear_folders(self):
        self.folder_grid.clear_all()
        self.statusBar().showMessage("Cleared all folders")

    def update_chunk_size_label(self):
        size_kb = self.chunk_size_spin.value()
        if size_kb >= 1024:
            size_mb = size_kb / 1024
            text = f"({size_mb:.1f} MB per chunk)"
            if size_mb > 10:
                text += " ⚠️ Large chunks may exceed clipboard limits"
                self.chunk_size_label.setStyleSheet(
                    "color: #ff9900; font-size: 12px; font-weight: bold;"
                )
            else:
                self.chunk_size_label.setStyleSheet("color: #888; font-size: 12px;")
            self.chunk_size_label.setText(text)
        else:
            self.chunk_size_label.setText(f"({size_kb} KB per chunk)")
            self.chunk_size_label.setStyleSheet("color: #888; font-size: 12px;")

    def encode_folders(self):
        if not self.selected_folders:
            return

        # Disconnect any existing thread signals first
        if hasattr(self, "encoder_thread"):
            try:
                self.encoder_thread.finished.disconnect()
                self.encoder_thread.progress.disconnect()
                self.encoder_thread.chunk_ready.disconnect()
                self.encoder_thread.error.disconnect()
            except:
                pass

        # For now, encode the first selected folder
        # TODO: Add batch encoding support for multiple folders
        folder_to_encode = self.selected_folders[0]

        # Reset UI
        self.encode_btn.setEnabled(False)
        self.encode_progress.setVisible(True)
        self.encode_output.clear()
        self.chunks_data.clear()
        self.current_chunk_index = 0

        # Start encoding thread
        chunk_size_kb = self.chunk_size_spin.value()

        self.encoder_thread = EncoderThread(folder_to_encode, chunk_size_kb)
        self.encoder_thread.progress.connect(self.encode_progress.setValue)
        self.encoder_thread.chunk_ready.connect(self.on_chunk_ready)
        self.encoder_thread.finished.connect(self.on_encode_finished)
        self.encoder_thread.error.connect(self.on_encode_error)
        self.encoder_thread.status.connect(
            lambda msg: self.statusBar().showMessage(msg)
        )
        self.encoder_thread.start()

        folder_name = os.path.basename(folder_to_encode)
        self.statusBar().showMessage(f"Encoding folder: {folder_name}...")

    def on_chunk_ready(self, chunk_data, chunk_num, total_chunks):
        self.chunks_data[chunk_num] = chunk_data

        if chunk_num == 1:
            self.encode_output.setText(chunk_data)
            self.current_chunk_index = 1
            if self.auto_copy_check.isChecked():
                QApplication.clipboard().setText(chunk_data)

        self.update_chunk_navigation()

    def on_encode_finished(self):
        # Disconnect signals to prevent duplicate calls
        if hasattr(self, "encoder_thread"):
            try:
                self.encoder_thread.finished.disconnect()
                self.encoder_thread.progress.disconnect()
                self.encoder_thread.chunk_ready.disconnect()
                self.encoder_thread.error.disconnect()
            except:
                pass  # Already disconnected

        self.encode_progress.setVisible(False)
        self.encode_btn.setEnabled(True)
        self.encode_btn.setStyleSheet("")  # Reset to default style
        self.statusBar().showMessage(
            f"Encoding complete! {len(self.chunks_data)} chunks created."
        )

        # Show success in drop area
        self.drop_label.setText(f"✓ Encoded {len(self.chunks_data)} chunks!")
        self.drop_label.setStyleSheet("""
            QLabel {
                border: 2px solid #14ffec;
                border-radius: 10px;
                padding: 40px;
                font-size: 16px;
                background-color: #0a5d61;
                color: #14ffec;
                font-weight: bold;
            }
        """)
        QTimer.singleShot(3000, self.reset_drop_label)

        if self.auto_copy_check.isChecked():
            QMessageBox.information(
                self,
                "Success",
                f"Folder encoded into {len(self.chunks_data)} chunks.\n"
                "First chunk copied to clipboard automatically.",
            )

    def on_encode_error(self, error_msg):
        self.encode_progress.setVisible(False)
        self.encode_btn.setEnabled(True)
        self.encode_btn.setStyleSheet("")  # Reset to default style
        QMessageBox.critical(
            self, "Encoding Error", f"Failed to encode folder: {error_msg}"
        )
        self.statusBar().showMessage("Encoding failed")

    def update_chunk_navigation(self):
        if not self.chunks_data:
            return

        total_chunks = len(self.chunks_data)
        self.chunk_label.setText(f"Chunk {self.current_chunk_index}/{total_chunks}")

        self.prev_chunk_btn.setEnabled(self.current_chunk_index > 1)
        self.next_chunk_btn.setEnabled(self.current_chunk_index < total_chunks)
        self.copy_chunk_btn.setEnabled(True)

    def prev_chunk(self):
        if self.current_chunk_index > 1:
            self.current_chunk_index -= 1
            self.encode_output.setText(self.chunks_data[self.current_chunk_index])
            self.update_chunk_navigation()

    def next_chunk(self):
        if self.current_chunk_index < len(self.chunks_data):
            self.current_chunk_index += 1
            self.encode_output.setText(self.chunks_data[self.current_chunk_index])
            self.update_chunk_navigation()

    def copy_current_chunk(self):
        if self.current_chunk_index in self.chunks_data:
            QApplication.clipboard().setText(self.chunks_data[self.current_chunk_index])
            self.statusBar().showMessage(
                f"Chunk {self.current_chunk_index} copied to clipboard"
            )

    def add_chunk(self):
        chunk_text = self.decode_input.toPlainText()
        if not chunk_text.strip():  # Check if empty but don't strip the actual text
            return

        try:
            # Parse chunk header - find the first newline after the header
            if not chunk_text.startswith("FOLDER_TRANSFER_V1"):
                QMessageBox.warning(
                    self, "Invalid Chunk", "This doesn't appear to be a valid chunk."
                )
                return

            # Find the end of the header line
            header_end = chunk_text.find("\n")
            if header_end == -1:
                QMessageBox.warning(
                    self, "Invalid Chunk", "No data found after header."
                )
                return

            header_line = chunk_text[:header_end]
            chunk_data = chunk_text[
                header_end + 1 :
            ]  # Everything after the first newline, INCLUDING whitespace

            header_parts = header_line.split("|")
            if len(header_parts) < 4:
                QMessageBox.warning(
                    self, "Invalid Chunk", "Invalid chunk header format."
                )
                return

            chunk_num = int(header_parts[1])
            total_chunks = int(header_parts[2])
            folder_name = header_parts[3]

            # Validate base64 data
            if not chunk_data:
                QMessageBox.warning(self, "Invalid Chunk", "Chunk contains no data.")
                return

            # Store chunk
            if not hasattr(self, "decode_chunks_info"):
                self.decode_chunks_info = {
                    "total": total_chunks,
                    "folder_name": folder_name,
                    "chunks": {},
                    "chunk_sizes": {},  # Track sizes for debugging
                }

            self.decode_chunks_info["chunks"][chunk_num] = chunk_data
            self.decode_chunks_info["chunk_sizes"][chunk_num] = len(chunk_data)

            # Update UI
            self.decode_input.clear()
            self.update_decode_status()

            received = len(self.decode_chunks_info["chunks"])
            self.statusBar().showMessage(
                f"Added chunk {chunk_num}/{total_chunks} ({len(chunk_data)} bytes)"
            )

            # Debug print
            print(
                f"Added chunk {chunk_num}/{total_chunks}, received so far: {received}"
            )
            print(f"Decode button enabled: {self.decode_btn.isEnabled()}")

            if received == total_chunks:
                # Verify total size
                total_size = sum(self.decode_chunks_info["chunk_sizes"].values())

                # Force enable the decode button before showing dialog
                self.decode_btn.setEnabled(True)
                self.decode_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #14ffec;
                        color: #1e1e1e;
                        border: none;
                        padding: 10px 20px;
                        border-radius: 5px;
                        font-weight: bold;
                        font-size: 14px;
                    }
                """)
                self.decode_btn.setText("✓ Decode Folder (Ready)")
                self.decode_btn.update()
                self.decode_btn.repaint()

                # Process events to ensure UI updates
                QApplication.processEvents()

                # Use QTimer to show message after UI updates
                QTimer.singleShot(
                    100,
                    lambda: QMessageBox.information(
                        self,
                        "Ready to Decode",
                        f"All {total_chunks} chunks received! Total size: {total_size} bytes\n"
                        f"Click 'Decode Folder' to extract.",
                    ),
                )

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to process chunk: {str(e)}")

    def update_decode_status(self):
        if not hasattr(self, "decode_chunks_info"):
            self.chunks_status_label.setText("No chunks added")
            self.decode_btn.setEnabled(False)
            return

        info = self.decode_chunks_info
        received = len(info["chunks"])
        total = info["total"]

        self.chunks_status_label.setText(
            f"Folder: {info['folder_name']}\nChunks: {received}/{total}"
        )

        # Show which chunks we have
        chunks_list = []
        for i in range(1, total + 1):
            if i in info["chunks"]:
                chunks_list.append(f"✓ Chunk {i}")
            else:
                chunks_list.append(f"✗ Chunk {i}")

        self.chunks_list.setText("\n".join(chunks_list))

        # Enable decode button if all chunks received
        can_decode = received == total

        # Update button/label based on platform
        if (
            platform.system() == "Linux"
            and PYSIDE_VERSION == "PySide2"
            and self.decode_label
        ):
            # Use label approach for Linux PySide2
            self._can_decode = can_decode

            if can_decode:
                self.decode_label.setText("✓ Decode Folder (Ready)")
                self.decode_label.setStyleSheet("""
                    QLabel {
                        background-color: #14ffec;
                        color: #1e1e1e;
                        border: none;
                        padding: 10px 20px;
                        border-radius: 5px;
                        font-weight: bold;
                        font-size: 14px;
                        cursor: pointer;
                    }
                    QLabel:hover {
                        background-color: #0d7377;
                        color: #ffffff;
                    }
                """)
                self.decode_label.setCursor(PointingHandCursor)
            else:
                self.decode_label.setText("Decode Folder")
                self.decode_label.setStyleSheet("""
                    QLabel {
                        background-color: #444;
                        color: #888;
                        border: none;
                        padding: 10px 20px;
                        border-radius: 5px;
                        font-weight: bold;
                        font-size: 14px;
                    }
                """)
                self.decode_label.unsetCursor()

            # Force updates
            self.decode_label.update()
            self.decode_label.repaint()
            QApplication.processEvents()
        else:
            # Normal button approach for other platforms
            self.decode_btn.setEnabled(can_decode)

            if can_decode:
                self.decode_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #14ffec;
                        color: #1e1e1e;
                        border: none;
                        padding: 10px 20px;
                        border-radius: 5px;
                        font-weight: bold;
                        font-size: 14px;
                    }
                    QPushButton:hover {
                        background-color: #0d7377;
                        color: #ffffff;
                    }
                    QPushButton:pressed {
                        background-color: #0a5d61;
                    }
                """)
                self.decode_btn.setText("✓ Decode Folder (Ready)")
            else:
                self.decode_btn.setText("Decode Folder")

            # Debug output
            print(
                f"[update_decode_status] Button should be enabled now: {self.decode_btn.isEnabled()}"
            )
            print(
                f"[update_decode_status] Button is disabled: {self.decode_btn.isDisabled() if hasattr(self.decode_btn, 'isDisabled') else 'N/A'}"
            )

    def browse_output_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.output_dir_label.setText(folder)

    def test_decode_button_click(self):
        """Test method to verify button is actually clickable"""
        print(f"Test click - Button enabled: {self.decode_btn.isEnabled()}")
        print(f"Test click - Button visible: {self.decode_btn.isVisible()}")
        print(f"Test click - Button text: {self.decode_btn.text()}")

    def _decode_label_click(self, event):
        """Handle clicks on the decode label for Linux PySide2"""
        if hasattr(self, "_can_decode") and self._can_decode:
            print("Decode label clicked, triggering decode...")
            self.decode_folder()
        else:
            print("Decode label clicked but cannot decode yet")

    def decode_folder(self):
        print("Decode folder called!")  # Debug
        print(f"Button state at decode: enabled={self.decode_btn.isEnabled()}")

        # Linux workaround - double check button state
        if platform.system() == "Linux" and not self.decode_btn.isEnabled():
            print("WARNING: Button was not enabled on Linux, forcing enable")
            self.decode_btn.setEnabled(True)
            QApplication.processEvents()

        if not hasattr(self, "decode_chunks_info"):
            QMessageBox.warning(self, "No Chunks", "No chunks have been added yet.")
            return

        # Prepare chunks in order
        chunks = []
        missing_chunks = []
        for i in range(1, self.decode_chunks_info["total"] + 1):
            if i in self.decode_chunks_info["chunks"]:
                chunks.append(self.decode_chunks_info["chunks"][i])
            else:
                missing_chunks.append(i)

        if missing_chunks:
            QMessageBox.critical(
                self,
                "Missing Chunks",
                f"Missing chunks: {', '.join(map(str, missing_chunks))}",
            )
            return

        # Start decoding
        self.decode_btn.setEnabled(False)
        self.decode_progress.setVisible(True)

        output_dir = self.output_dir_label.text()

        self.decoder_thread = DecoderThread(chunks, output_dir)
        self.decoder_thread.progress.connect(self.decode_progress.setValue)
        self.decoder_thread.finished.connect(self.on_decode_finished)
        self.decoder_thread.error.connect(self.on_decode_error)
        self.decoder_thread.status.connect(
            lambda msg: self.statusBar().showMessage(msg)
        )
        self.decoder_thread.start()

        self.statusBar().showMessage("Decoding folder...")

    def on_decode_finished(self, output_path):
        self.decode_progress.setVisible(False)
        self.decode_btn.setEnabled(True)

        QMessageBox.information(
            self, "Success", f"Folder successfully decoded to:\n{output_path}"
        )

        self.statusBar().showMessage("Decoding complete!")

        # Clear chunks
        if hasattr(self, "decode_chunks_info"):
            del self.decode_chunks_info
        self.chunks_status_label.setText("No chunks added")
        self.chunks_list.clear()
        self.decode_btn.setEnabled(False)
        self.decode_btn.setText("Decode Folder")
        self.decode_btn.setStyleSheet("")  # Reset style

    def on_decode_error(self, error_msg):
        self.decode_progress.setVisible(False)
        self.decode_btn.setEnabled(True)
        QMessageBox.critical(
            self, "Decoding Error", f"Failed to decode folder: {error_msg}"
        )
        self.statusBar().showMessage("Decoding failed")

    def clear_decode_chunks(self):
        if hasattr(self, "decode_chunks_info"):
            del self.decode_chunks_info
        self.chunks_status_label.setText("No chunks added")
        self.chunks_list.clear()
        self.decode_btn.setEnabled(False)
        self.decode_btn.setText("Decode Folder")
        self.decode_btn.setStyleSheet("")  # Reset to default style
        self.statusBar().showMessage("Cleared all chunks")

    def browse_chunk_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Base64 Chunk File",
            "",
            "Text Files (*.txt *.base64 *.b64);;All Files (*.*)",
        )
        if file_path:
            self.load_chunk_from_file(file_path)

    def load_chunk_from_file(self, file_path):
        try:
            # Check file size
            file_size = os.path.getsize(file_path)

            # Use thread for files larger than 5MB
            if file_size > 5 * 1024 * 1024:  # 5MB
                # Create progress dialog
                progress_dialog = QProgressBar(self)
                progress_dialog.setWindowTitle("Loading File")
                progress_dialog.setMinimum(0)
                progress_dialog.setMaximum(100)
                progress_dialog.setTextVisible(True)

                # Create a dialog to hold the progress bar
                dialog = QMessageBox(self)
                dialog.setWindowTitle("Loading File")
                dialog.setText(f"Loading {os.path.basename(file_path)}...")
                dialog.setStandardButtons(QMessageBox.NoButton)
                dialog.show()

                # Start file loader thread
                self.file_loader_thread = FileLoaderThread(file_path)
                self.file_loader_thread.progress.connect(
                    lambda p: dialog.setText(
                        f"Loading {os.path.basename(file_path)}...\nProgress: {p}%"
                    )
                )
                self.file_loader_thread.finished.connect(
                    lambda content: self.on_file_loaded(content, dialog)
                )
                self.file_loader_thread.error.connect(
                    lambda err: self.on_file_load_error(err, dialog)
                )
                self.file_loader_thread.status.connect(
                    lambda msg: self.statusBar().showMessage(msg)
                )
                self.file_loader_thread.start()
            else:
                # For smaller files, load directly
                self.statusBar().showMessage(
                    f"Loading file: {os.path.basename(file_path)}..."
                )

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        chunk_text = f.read()
                except Exception as e:
                    QMessageBox.critical(
                        self, "File Error", f"Failed to read file: {str(e)}"
                    )
                    return

                if not chunk_text.strip():
                    QMessageBox.warning(
                        self, "Empty File", "The selected file is empty."
                    )
                    return

                # Process the chunk text
                self.decode_input.setText(chunk_text)
                self.add_chunk()

                # Update file drop label to show success
                self.file_drop_label.setText(f"✓ Loaded: {os.path.basename(file_path)}")
                self.file_drop_label.setStyleSheet("""
                    QLabel {
                        border: 2px solid #14ffec;
                        border-radius: 10px;
                        padding: 30px;
                        font-size: 14px;
                        background-color: #0a5d61;
                        color: #14ffec;
                        font-weight: bold;
                        min-height: 100px;
                    }
                """)

                # Reset file drop label after 2 seconds
                QTimer.singleShot(2000, self.reset_file_drop_label)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load file: {str(e)}")
            self.statusBar().showMessage("File loading failed")

    def on_file_loaded(self, content, dialog):
        dialog.close()

        if not content.strip():
            QMessageBox.warning(self, "Empty File", "The selected file is empty.")
            return

        # Process the chunk text
        self.decode_input.setText(content)
        self.add_chunk()

        # Update file drop label to show success
        self.file_drop_label.setText("✓ File loaded successfully!")
        self.file_drop_label.setStyleSheet("""
            QLabel {
                border: 2px solid #14ffec;
                border-radius: 10px;
                padding: 30px;
                font-size: 14px;
                background-color: #0a5d61;
                color: #14ffec;
                font-weight: bold;
                min-height: 100px;
            }
        """)

        # Reset file drop label after 2 seconds
        QTimer.singleShot(2000, self.reset_file_drop_label)

    def on_file_load_error(self, error_msg, dialog):
        dialog.close()
        QMessageBox.critical(self, "File Error", f"Failed to read file: {error_msg}")
        self.statusBar().showMessage("File loading failed")

    def reset_file_drop_label(self):
        self.file_drop_label.setText(
            "Drag and drop a base64 file here\n(.txt, .base64, .b64)"
        )
        self.file_drop_label.setStyleSheet(self.file_drop_label.default_style)


def main():
    app = QApplication(sys.argv)
    window = FolderTransferApp()
    window.show()
    sys.exit(exec_app(app))


if __name__ == "__main__":
    main()
