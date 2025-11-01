"""Custom launcher management dialog for ShotBot."""

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from launcher_manager import (
    CustomLauncher,
    LauncherEnvironment,
    LauncherManager,
    LauncherTerminal,
)

logger = logging.getLogger(__name__)


class LauncherListWidget(QListWidget):
    """Custom list widget with drag-and-drop reordering support."""

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAlternatingRowColors(True)
        self.setObjectName("launcherList")


class LauncherPreviewPanel(QWidget):
    """Preview panel showing launcher details and action buttons."""

    # Signals
    launch_requested = Signal(str)  # launcher_id
    edit_requested = Signal(str)  # launcher_id
    delete_requested = Signal(str)  # launcher_id

    def __init__(self):
        super().__init__()
        self.setObjectName("previewPanel")
        self._current_launcher_id: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self):
        """Set up the preview panel UI."""
        layout = QVBoxLayout(self)

        # Name label
        self.name_label = QLabel("Select a launcher")
        self.name_label.setObjectName("launcherName")
        self.name_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.name_label)

        # Description label
        self.description_label = QLabel("")
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet("color: #aaa; margin-bottom: 10px;")
        layout.addWidget(self.description_label)

        # Command preview
        command_label = QLabel("Command:")
        command_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(command_label)

        self.command_preview = QTextEdit()
        self.command_preview.setObjectName("commandPreview")
        self.command_preview.setReadOnly(True)
        self.command_preview.setMaximumHeight(100)
        layout.addWidget(self.command_preview)

        # Action buttons
        button_layout = QHBoxLayout()

        self.launch_button = QPushButton("Launch")
        self.launch_button.setObjectName("launchButton")
        self.launch_button.clicked.connect(self._on_launch)
        self.launch_button.setEnabled(False)
        button_layout.addWidget(self.launch_button)

        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self._on_edit)
        self.edit_button.setEnabled(False)
        button_layout.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("deleteButton")
        self.delete_button.clicked.connect(self._on_delete)
        self.delete_button.setEnabled(False)
        button_layout.addWidget(self.delete_button)

        layout.addLayout(button_layout)
        layout.addStretch()

    def set_launcher(self, launcher: Optional[CustomLauncher]):
        """Update the preview with launcher details."""
        if not launcher:
            self._current_launcher_id = None
            self.name_label.setText("Select a launcher")
            self.description_label.setText("")
            self.command_preview.clear()
            self.launch_button.setEnabled(False)
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        self._current_launcher_id = launcher.id
        self.name_label.setText(launcher.name)
        self.description_label.setText(launcher.description or "No description")
        self.command_preview.setPlainText(launcher.command)
        self.launch_button.setEnabled(True)
        self.edit_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def _on_launch(self):
        """Handle launch button click."""
        if self._current_launcher_id:
            self.launch_requested.emit(self._current_launcher_id)

    def _on_edit(self):
        """Handle edit button click."""
        if self._current_launcher_id:
            self.edit_requested.emit(self._current_launcher_id)

    def _on_delete(self):
        """Handle delete button click."""
        if self._current_launcher_id:
            self.delete_requested.emit(self._current_launcher_id)


class LauncherEditDialog(QDialog):
    """Dialog for creating/editing launchers."""

    def __init__(
        self,
        launcher_manager: LauncherManager,
        launcher: Optional[CustomLauncher] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.launcher_manager = launcher_manager
        self.launcher = launcher
        self.is_editing = launcher is not None
        self._setup_ui()
        self._populate_fields()
        self._connect_signals()

    def _setup_ui(self):
        """Set up the edit dialog UI."""
        self.setWindowTitle("Edit Launcher" if self.is_editing else "New Launcher")
        self.setModal(True)
        self.setMinimumWidth(600)

        layout = QVBoxLayout(self)

        # Form layout
        form_layout = QFormLayout()

        # Name field
        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText("e.g., Launch Nuke Debug")
        form_layout.addRow("Name:", self.name_field)

        # Command field
        self.command_field = QTextEdit()
        self.command_field.setPlaceholderText(
            "e.g., nuke --nc {workspace_path}/nuke/{shot}_v001.nk\n"
            "Available variables: {show}, {sequence}, {shot}, {full_name}, {workspace_path}"
        )
        self.command_field.setMaximumHeight(100)
        form_layout.addRow("Command:", self.command_field)

        # Description field
        self.description_field = QLineEdit()
        self.description_field.setPlaceholderText("Optional description")
        form_layout.addRow("Description:", self.description_field)

        # Category field
        self.category_field = QLineEdit()
        self.category_field.setPlaceholderText("e.g., Applications, Scripts, Debug")
        form_layout.addRow("Category:", self.category_field)

        layout.addLayout(form_layout)

        # Environment settings
        env_group = QGroupBox("Environment Settings")
        env_layout = QFormLayout()

        self.env_type_combo = QComboBox()
        self.env_type_combo.addItems(["none", "bash", "rez", "conda"])
        env_layout.addRow("Environment:", self.env_type_combo)

        self.env_spec_field = QLineEdit()
        self.env_spec_field.setPlaceholderText("e.g., PySide6_Essentials pillow")
        env_layout.addRow("Packages/Env:", self.env_spec_field)

        env_group.setLayout(env_layout)
        layout.addWidget(env_group)

        # Terminal settings
        terminal_group = QGroupBox("Terminal Settings")
        terminal_layout = QFormLayout()

        self.persist_terminal = QCheckBox("Keep terminal open after command exits")
        terminal_layout.addRow(self.persist_terminal)

        terminal_group.setLayout(terminal_layout)
        layout.addWidget(terminal_group)

        # Test section
        test_layout = QHBoxLayout()
        self.test_button = QPushButton("Test Command")
        self.test_button.clicked.connect(self._test_command)
        test_layout.addWidget(self.test_button)

        self.test_output = QLabel("")
        self.test_output.setStyleSheet("color: #888; font-style: italic;")
        test_layout.addWidget(self.test_output, 1)

        layout.addLayout(test_layout)

        # Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self._save)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _populate_fields(self):
        """Populate fields with existing launcher data."""
        if not self.launcher:
            return

        self.name_field.setText(self.launcher.name)
        self.command_field.setPlainText(self.launcher.command)
        self.description_field.setText(self.launcher.description or "")
        self.category_field.setText(self.launcher.category or "")

        if self.launcher.environment:
            self.env_type_combo.setCurrentText(self.launcher.environment.type)
            if self.launcher.environment.type == "rez":
                self.env_spec_field.setText(
                    " ".join(self.launcher.environment.packages or [])
                )
            elif self.launcher.environment.type == "conda":
                # Conda environments use command_prefix for environment name
                self.env_spec_field.setText(
                    self.launcher.environment.command_prefix or ""
                )

        if self.launcher.terminal:
            self.persist_terminal.setChecked(self.launcher.terminal.persist)

    def _connect_signals(self):
        """Connect signals for validation."""
        self.name_field.textChanged.connect(self._validate_name)
        self.command_field.textChanged.connect(self._validate_command)

    def _validate_name(self):
        """Validate launcher name."""
        name = self.name_field.text().strip()
        if not name:
            self.name_field.setStyleSheet("border: 1px solid #f44336;")
            return False

        # Check uniqueness
        if not self.is_editing or (self.launcher and name != self.launcher.name):
            if self.launcher_manager.get_launcher_by_name(name):
                self.name_field.setStyleSheet("border: 1px solid #f44336;")
                return False

        self.name_field.setStyleSheet("border: 1px solid #4caf50;")
        return True

    def _validate_command(self):
        """Validate command syntax."""
        command = self.command_field.toPlainText().strip()
        if not command:
            self.command_field.setStyleSheet("border: 1px solid #f44336;")
            return False

        is_valid, error = self.launcher_manager.validate_command_syntax(command)
        if not is_valid:
            self.command_field.setStyleSheet("border: 1px solid #f44336;")
            return False

        self.command_field.setStyleSheet("border: 1px solid #4caf50;")
        return True

    def _test_command(self):
        """Test the command with dry run."""
        command = self.command_field.toPlainText().strip()
        if not command:
            self.test_output.setText("No command to test")
            return

        # Create temporary launcher
        test_launcher = CustomLauncher(
            id="test",
            name="Test",
            description="Test launcher",
            command=command,
        )

        # Test with dummy variables
        variables = {
            "show": "test_show",
            "sequence": "seq001",
            "shot": "0010",
            "full_name": "seq001_0010",
            "workspace_path": "/shows/test_show/shots/seq001/seq001_0010",
        }

        try:
            self.launcher_manager.execute_launcher(
                test_launcher.id, variables, dry_run=True
            )
            self.test_output.setText("✓ Command validated successfully")
            self.test_output.setStyleSheet("color: #4caf50; font-style: italic;")
        except Exception as e:
            self.test_output.setText(f"✗ {str(e)}")
            self.test_output.setStyleSheet("color: #f44336; font-style: italic;")

    def _save(self):
        """Save the launcher."""
        if not self._validate_name() or not self._validate_command():
            QMessageBox.warning(
                self, "Validation Error", "Please fix the highlighted fields."
            )
            return

        # Gather data
        name = self.name_field.text().strip()
        command = self.command_field.toPlainText().strip()
        description = self.description_field.text().strip()
        category = self.category_field.text().strip()

        # Environment
        env_type = self.env_type_combo.currentText()
        env_spec = self.env_spec_field.text().strip()
        environment = None

        if env_type != "none" and env_spec:
            if env_type == "rez":
                environment = LauncherEnvironment(type="rez", packages=env_spec.split())
            elif env_type == "conda":
                environment = LauncherEnvironment(type="conda", command_prefix=env_spec)

        # Create terminal settings
        terminal = LauncherTerminal(persist=self.persist_terminal.isChecked())

        try:
            if self.is_editing and self.launcher:
                # Update existing
                success = self.launcher_manager.update_launcher(
                    self.launcher.id,
                    name=name,
                    command=command,
                    description=description or "",
                    category=category or "custom",
                    environment=environment,
                    terminal=terminal,
                )
                if success:
                    self.accept()
                else:
                    QMessageBox.critical(self, "Error", "Failed to update launcher.")
            else:
                # Create new
                launcher_id = self.launcher_manager.create_launcher(
                    name=name,
                    command=command,
                    description=description or "",
                    category=category or "custom",
                    environment=environment,
                    terminal=terminal,
                )
                if launcher_id:
                    self.accept()
                else:
                    QMessageBox.critical(self, "Error", "Failed to create launcher.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error saving launcher: {str(e)}")


class LauncherManagerDialog(QDialog):
    """Main launcher management dialog."""

    def __init__(self, launcher_manager: LauncherManager, parent=None):
        super().__init__(parent)
        self.launcher_manager = launcher_manager
        self._launchers_cache = {}
        self._setup_ui()
        self._setup_shortcuts()
        self._connect_signals()
        self._load_launchers()
        self._apply_styles()

    def _setup_ui(self):
        """Set up the main dialog UI."""
        self.setWindowTitle("Custom Launchers")
        self.setModal(False)
        self.resize(900, 600)

        layout = QVBoxLayout(self)

        # Header
        header_layout = QHBoxLayout()

        title_label = QLabel("Custom Launchers")
        title_label.setObjectName("titleLabel")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        self.search_field = QLineEdit()
        self.search_field.setObjectName("searchField")
        self.search_field.setPlaceholderText("Search launchers...")
        self.search_field.setMaximumWidth(300)
        header_layout.addWidget(self.search_field)

        layout.addLayout(header_layout)

        # Content splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # Launcher list
        self.launcher_list = LauncherListWidget()
        self.launcher_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.launcher_list.itemDoubleClicked.connect(self._on_double_click)
        self.splitter.addWidget(self.launcher_list)

        # Preview panel
        self.preview_panel = LauncherPreviewPanel()
        self.preview_panel.launch_requested.connect(self._launch_launcher)
        self.preview_panel.edit_requested.connect(self._edit_launcher)
        self.preview_panel.delete_requested.connect(self._delete_launcher)
        self.splitter.addWidget(self.preview_panel)

        self.splitter.setSizes([400, 500])
        layout.addWidget(self.splitter)

        # Bottom buttons
        button_layout = QHBoxLayout()

        self.add_button = QPushButton("Add New Launcher")
        self.add_button.clicked.connect(self._add_launcher)
        button_layout.addWidget(self.add_button)

        button_layout.addStretch()

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def _setup_shortcuts(self):
        """Set up keyboard shortcuts."""
        # Enter - Launch
        QShortcut(Qt.Key.Key_Return, self, self._launch_selected)

        # F2 - Edit
        QShortcut(Qt.Key.Key_F2, self, self._edit_selected)

        # Delete - Delete
        QShortcut(Qt.Key.Key_Delete, self, self._delete_selected)

        # Ctrl+N - New
        QShortcut("Ctrl+N", self, self._add_launcher)

        # Ctrl+F - Search
        QShortcut("Ctrl+F", self, lambda: self.search_field.setFocus())

        # Escape - Close
        QShortcut(Qt.Key.Key_Escape, self, self.close)

    def _connect_signals(self):
        """Connect signals to slots."""
        # Search
        self.search_field.textChanged.connect(self._filter_launchers)

        # Manager signals
        self.launcher_manager.launchers_changed.connect(self._load_launchers)
        self.launcher_manager.execution_started.connect(self._on_execution_started)
        self.launcher_manager.execution_finished.connect(self._on_execution_finished)

    def _apply_styles(self):
        """Apply custom styles."""
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
            }
            
            QLabel#titleLabel {
                color: #14ffec;
                font-size: 16px;
                font-weight: bold;
                padding: 10px;
            }
            
            QLineEdit#searchField {
                background-color: #3c3c3c;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px;
                color: #ddd;
                font-size: 13px;
            }
            
            QLineEdit#searchField:focus {
                border-color: #14ffec;
            }
            
            QListWidget {
                background-color: #333;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 5px;
                outline: none;
            }
            
            QListWidget::item {
                background-color: #3c3c3c;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 8px;
                margin: 2px 0;
                color: #ddd;
            }
            
            QListWidget::item:hover {
                background-color: #444;
                border-color: #555;
            }
            
            QListWidget::item:selected {
                background-color: #14ffec20;
                border-color: #14ffec;
                color: #fff;
            }
            
            QWidget#previewPanel {
                background-color: #333;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 15px;
            }
            
            QTextEdit#commandPreview {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px;
                color: #aaa;
                font-family: monospace;
                font-size: 12px;
            }
            
            QPushButton {
                background-color: #3c3c3c;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px 15px;
                color: #ddd;
                font-weight: bold;
            }
            
            QPushButton:hover {
                background-color: #444;
                border-color: #666;
            }
            
            QPushButton:pressed {
                background-color: #2b2b2b;
            }
            
            QPushButton#launchButton {
                background-color: #14ffec30;
                border-color: #14ffec;
            }
            
            QPushButton#launchButton:hover {
                background-color: #14ffec40;
            }
            
            QPushButton#deleteButton:hover {
                background-color: #ff444440;
                border-color: #ff6666;
            }
        """)

    def _load_launchers(self):
        """Load launchers into the list."""
        self.launcher_list.clear()
        self._launchers_cache.clear()

        launchers = self.launcher_manager.list_launchers()
        for launcher in launchers:
            # Create list item
            item = QListWidgetItem()
            item.setText(launcher.name)

            # Store launcher data
            item.setData(Qt.ItemDataRole.UserRole, launcher.id)
            self._launchers_cache[launcher.id] = launcher

            # Add to list
            self.launcher_list.addItem(item)

        # Update preview
        if self.launcher_list.count() > 0:
            self.launcher_list.setCurrentRow(0)
        else:
            self.preview_panel.set_launcher(None)

    def _filter_launchers(self, text: str):
        """Filter launchers based on search text."""
        search_text = text.lower()

        for i in range(self.launcher_list.count()):
            item = self.launcher_list.item(i)
            launcher_id = item.data(Qt.ItemDataRole.UserRole)
            launcher = self._launchers_cache.get(launcher_id)

            if launcher:
                # Search in name and command
                visible = (
                    search_text in launcher.name.lower()
                    or search_text in launcher.command.lower()
                )
                item.setHidden(not visible)

    def _on_selection_changed(self):
        """Handle launcher selection change."""
        current_item = self.launcher_list.currentItem()
        if current_item:
            launcher_id = current_item.data(Qt.ItemDataRole.UserRole)
            launcher = self._launchers_cache.get(launcher_id)
            self.preview_panel.set_launcher(launcher)
        else:
            self.preview_panel.set_launcher(None)

    def _on_double_click(self, item: QListWidgetItem):
        """Handle double-click to launch."""
        launcher_id = item.data(Qt.ItemDataRole.UserRole)
        self._launch_launcher(launcher_id)

    def _add_launcher(self):
        """Show dialog to add new launcher."""
        dialog = LauncherEditDialog(self.launcher_manager, parent=self)
        dialog.exec()

    def _edit_launcher(self, launcher_id: str):
        """Show dialog to edit launcher."""
        launcher = self._launchers_cache.get(launcher_id)
        if launcher:
            dialog = LauncherEditDialog(self.launcher_manager, launcher, parent=self)
            dialog.exec()

    def _delete_launcher(self, launcher_id: str):
        """Delete launcher with confirmation."""
        launcher = self._launchers_cache.get(launcher_id)
        if not launcher:
            return

        reply = QMessageBox.question(
            self,
            "Delete Launcher",
            f"Are you sure you want to delete '{launcher.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.launcher_manager.delete_launcher(launcher_id):
                self._load_launchers()
            else:
                QMessageBox.critical(self, "Error", "Failed to delete launcher.")

    def _launch_launcher(self, launcher_id: str):
        """Launch the specified launcher."""
        launcher = self._launchers_cache.get(launcher_id)
        if not launcher:
            return

        try:
            # For now, launch without shot context
            # In real usage, this would get shot context from main window
            self.launcher_manager.execute_launcher(launcher_id)
        except Exception as e:
            QMessageBox.critical(self, "Launch Error", f"Failed to launch: {str(e)}")

    def _launch_selected(self):
        """Launch the selected launcher."""
        current_item = self.launcher_list.currentItem()
        if current_item:
            launcher_id = current_item.data(Qt.ItemDataRole.UserRole)
            self._launch_launcher(launcher_id)

    def _edit_selected(self):
        """Edit the selected launcher."""
        current_item = self.launcher_list.currentItem()
        if current_item:
            launcher_id = current_item.data(Qt.ItemDataRole.UserRole)
            self._edit_launcher(launcher_id)

    def _delete_selected(self):
        """Delete the selected launcher."""
        current_item = self.launcher_list.currentItem()
        if current_item:
            launcher_id = current_item.data(Qt.ItemDataRole.UserRole)
            self._delete_launcher(launcher_id)

    def _on_execution_started(self, launcher_id: str):
        """Handle launcher execution start."""
        launcher = self._launchers_cache.get(launcher_id)
        if launcher:
            logger.info(f"Launching: {launcher.name}")

    def _on_execution_finished(self, launcher_id: str, success: bool):
        """Handle launcher execution finish."""
        launcher = self._launchers_cache.get(launcher_id)
        if launcher:
            if success:
                logger.info(f"Successfully launched: {launcher.name}")
            else:
                logger.error(f"Failed to launch: {launcher.name}")
