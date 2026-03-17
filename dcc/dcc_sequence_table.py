"""Embeddable RV sequence table widget for DCC sections.

Displays collapsible lists for Maya Playblasts and Nuke Renders,
each with its own expand/collapse state and double-click-to-launch behaviour.
Extracted from DCCSection to isolate sequence-list concerns.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from managers.settings_manager import get_stored_height
from ui.design_system import design_system
from ui.resizable_frame import ResizableFrame

from .scene_file import ImageSequence


if TYPE_CHECKING:
    from managers.settings_manager import SettingsManager


class DCCSequenceTable(QWidget):
    """Collapsible dual-list widget for Maya Playblasts and Nuke Renders.

    Signals:
        sequence_launch_requested: Emitted with the ImageSequence when the
            user double-clicks a sequence item.
    """

    sequence_launch_requested: ClassVar[Signal] = Signal(object)  # ImageSequence

    _DEFAULT_PANEL_HEIGHT: int = 120

    def __init__(
        self,
        *,
        dcc_name: str,
        settings_manager: SettingsManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the RV sequence subsections.

        Args:
            dcc_name: Internal DCC name (used for settings keys).
            settings_manager: Optional settings manager for height persistence.
            parent: Optional parent widget.

        """
        super().__init__(parent)
        self._dcc_name: str = dcc_name
        self._settings_manager: SettingsManager | None = settings_manager

        self._playblasts_section: dict[str, Any] | None = None
        self._renders_section: dict[str, Any] | None = None
        self._selected_sequence: ImageSequence | None = None

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the Maya Playblasts and Nuke Renders subsections."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        playblast_color = "#6b4d8a"  # Purple (Maya-like)
        render_color = "#8a6b2b"  # Gold (distinctive)

        self._playblasts_section = self._create_sequence_subsection(
            title="Maya Playblasts",
            color=playblast_color,
            content_layout=layout,
        )

        self._renders_section = self._create_sequence_subsection(
            title="Nuke Renders",
            color=render_color,
            content_layout=layout,
        )

    def _create_sequence_subsection(
        self,
        title: str,
        color: str,
        content_layout: QVBoxLayout,
    ) -> dict[str, Any]:
        """Create a collapsible sequence subsection.

        Args:
            title: Section title (e.g. "Maya Playblasts").
            color: Accent colour hex.
            content_layout: Parent layout to add section to.

        Returns:
            Dict containing section state and UI elements.

        """
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)

        # Header button
        header_btn = QPushButton(f"\u25b6  {title} (0)")
        header_btn.setFlat(True)
        header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-left: 3px solid {color};
                text-align: left;
                padding: 4px 8px;
                font-size: {design_system.typography.size_tiny}px;
                font-weight: bold;
                color: {color};
            }}
            QPushButton:hover {{
                background-color: #2a2a2a;
            }}
        """)
        layout.addWidget(header_btn)

        # Content container (hidden by default)
        content = QWidget()
        content.setVisible(False)
        content_inner_layout = QVBoxLayout(content)
        content_inner_layout.setContentsMargins(8, 4, 0, 0)
        content_inner_layout.setSpacing(4)

        # List widget for sequences
        list_widget = QListWidget()
        list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 3px;
                color: #ecf0f1;
                font-size: {design_system.typography.size_small}px;
            }}
            QListWidget::item {{
                padding: 4px 8px;
                border-bottom: 1px solid #2a2a2a;
            }}
            QListWidget::item:selected {{
                background-color: {color}40;
            }}
            QListWidget::item:hover {{
                background-color: #2a2a2a;
            }}
        """)

        # Resizable frame
        list_frame = ResizableFrame(
            child_widget=list_widget,
            min_height=60,
            max_height=400,
            initial_height=self._get_stored_sequence_height(title),
            accent_color=color,
            parent=self,
        )

        def make_height_handler(section_title: str) -> Callable[[int], None]:
            def on_height_changed(h: int) -> None:
                self._on_sequence_height_changed(section_title, h)
            return on_height_changed

        _ = list_frame.height_changed.connect(make_height_handler(title))
        content_inner_layout.addWidget(list_frame)

        layout.addWidget(content)
        content_layout.addWidget(section)

        result: dict[str, Any] = {
            "section": section,
            "header_btn": header_btn,
            "content": content,
            "list_widget": list_widget,
            "list_frame": list_frame,
            "expanded": False,
            "color": color,
            "title": title,
        }

        _ = header_btn.clicked.connect(lambda: self._toggle_sequence_section(result))
        _ = list_widget.itemDoubleClicked.connect(self._on_sequence_double_clicked)

        return result

    # ------------------------------------------------------------------
    # Expand / collapse
    # ------------------------------------------------------------------

    def _toggle_sequence_section(self, section_data: dict[str, Any]) -> None:
        """Toggle sequence subsection expanded state.

        Args:
            section_data: Dict containing section state and UI elements.

        """
        section_data["expanded"] = not section_data["expanded"]
        cast("QWidget", section_data["content"]).setVisible(section_data["expanded"])  # pyright: ignore[reportAny]
        indicator = "\u25bc" if section_data["expanded"] else "\u25b6"
        count = cast("QListWidget", section_data["list_widget"]).count()  # pyright: ignore[reportAny]
        cast("QPushButton", section_data["header_btn"]).setText(  # pyright: ignore[reportAny]
            f"{indicator}  {section_data['title']} ({count})"
        )

    # ------------------------------------------------------------------
    # Double-click launch
    # ------------------------------------------------------------------

    def _on_sequence_double_clicked(self, item: QListWidgetItem) -> None:
        """Handle sequence item double-click -- launch RV with sequence.

        Args:
            item: The double-clicked list item.

        """
        sequence = item.data(Qt.ItemDataRole.UserRole)  # pyright: ignore[reportAny]
        if isinstance(sequence, ImageSequence):
            self._selected_sequence = sequence
            self.sequence_launch_requested.emit(sequence)

    # ------------------------------------------------------------------
    # Public data API
    # ------------------------------------------------------------------

    def set_playblast_sequences(self, sequences: list[ImageSequence]) -> None:
        """Set Maya playblast sequences for display.

        Args:
            sequences: List of ImageSequence objects.

        """
        if self._playblasts_section:
            self._update_sequence_list(self._playblasts_section, sequences)

    def set_render_sequences(self, sequences: list[ImageSequence]) -> None:
        """Set Nuke render sequences for display.

        Args:
            sequences: List of ImageSequence objects.

        """
        if self._renders_section:
            self._update_sequence_list(self._renders_section, sequences)

    def _update_sequence_list(
        self, section_data: dict[str, Any], sequences: list[ImageSequence]
    ) -> None:
        """Update a sequence list widget with new data.

        Args:
            section_data: Dict containing section state and UI elements.
            sequences: List of ImageSequence objects to display.

        """
        list_widget: QListWidget = section_data["list_widget"]  # pyright: ignore[reportAny]
        list_widget.clear()

        for i, seq in enumerate(sequences):
            version_str = f"v{seq.version:03d}" if seq.version else "\u2014"
            latest_badge = "  LATEST" if i == 0 else ""
            item_text = (
                f"\u25b6  {seq.render_type}  |  {version_str}  |  "
                f"{seq.frame_range_str}  |  {seq.relative_age}{latest_badge}"
            )

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, seq)
            list_widget.addItem(item)

        indicator = "\u25bc" if section_data["expanded"] else "\u25b6"
        cast("QPushButton", section_data["header_btn"]).setText(  # pyright: ignore[reportAny]
            f"{indicator}  {section_data['title']} ({len(sequences)})"
        )

    def get_selected_sequence(self) -> ImageSequence | None:
        """Get currently selected sequence for RV launch.

        Returns:
            Selected ImageSequence or None.

        """
        return self._selected_sequence

    # ------------------------------------------------------------------
    # Height persistence
    # ------------------------------------------------------------------

    def _get_stored_sequence_height(self, title: str) -> int:
        """Get stored sequence list height from settings.

        Args:
            title: The sequence subsection title.

        Returns:
            Stored height or default.

        """
        if self._settings_manager is None:
            return self._DEFAULT_PANEL_HEIGHT
        return get_stored_height(
            self._settings_manager.settings,
            f"ui/table_height/{self._dcc_name}/{title}",
            self._DEFAULT_PANEL_HEIGHT,
        )

    def _on_sequence_height_changed(self, title: str, height: int) -> None:
        """Save new sequence list height to settings.

        Args:
            title: The sequence subsection title.
            height: The new height value.

        """
        if self._settings_manager is not None:
            self._settings_manager.settings.setValue(
                f"ui/table_height/{self._dcc_name}/{title}", height
            )
