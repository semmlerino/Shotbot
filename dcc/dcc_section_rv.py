"""DCC section for RV sequence playback and factory function.

Extends BaseDCCSection with an embedded DCCSequenceTable for browsing sequences,
and provides the create_dcc_section() factory for instantiating the appropriate
section type based on configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from typing_compat import override

from .dcc_section_base import BaseDCCSection
from .dcc_section_file import FileDCCSection
from .dcc_sequence_table import DCCSequenceTable


if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from managers.settings_manager import SettingsManager

    from .dcc_config import DCCConfig
    from .scene_file import ImageSequence


@final
class RVSection(BaseDCCSection):
    """DCC section for RV sequence playback.

    Adds an embedded DCCSequenceTable for browsing Maya playblasts
    and Nuke render sequences.

    """

    def __init__(
        self,
        config: DCCConfig,
        settings_manager: SettingsManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the RVSection.

        Args:
            config: Configuration for the RV DCC
            settings_manager: Settings manager for height persistence
            parent: Optional parent widget

        """
        self._dcc_sequence_table: DCCSequenceTable  # Will be set in _setup_ui
        super().__init__(config, settings_manager=settings_manager, parent=parent)

    @override
    def _setup_ui(self) -> None:
        """Set up UI, adding the sequence table after base chrome."""
        super()._setup_ui()

        self._dcc_sequence_table = DCCSequenceTable(
            dcc_name=self.config.name,
            settings_manager=self._settings_manager,
            parent=self,
        )
        _ = self._dcc_sequence_table.sequence_launch_requested.connect(
            self._on_sequence_launch_requested
        )
        self._content_layout.addWidget(self._dcc_sequence_table)

    # ========== Embedded Sequence Table Signal Handlers ==========

    def _on_sequence_launch_requested(self, sequence: ImageSequence) -> None:
        """Handle sequence_launch_requested from embedded DCCSequenceTable.

        Emits launch_requested with sequence_path in options.

        Args:
            sequence: The ImageSequence to launch.

        """
        options = self.get_options()
        options["sequence_path"] = str(sequence.path)
        self.launch_requested.emit(self.config.name, options)

    def set_playblast_sequences(self, sequences: list[ImageSequence]) -> None:
        """Set Maya playblast sequences for display.

        Args:
            sequences: List of ImageSequence objects.

        """
        self._dcc_sequence_table.set_playblast_sequences(sequences)

    def set_render_sequences(self, sequences: list[ImageSequence]) -> None:
        """Set Nuke render sequences for display.

        Args:
            sequences: List of ImageSequence objects.

        """
        self._dcc_sequence_table.set_render_sequences(sequences)

    def get_selected_sequence(self) -> ImageSequence | None:
        """Get currently selected sequence for RV launch.

        Returns:
            Selected ImageSequence or None.

        """
        return self._dcc_sequence_table.get_selected_sequence()


def create_dcc_section(
    config: DCCConfig,
    *,
    settings_manager: SettingsManager | None = None,
    parent: QWidget | None = None,
) -> BaseDCCSection:
    """Create the appropriate DCC section for the given config.

    Args:
        config: DCC configuration
        settings_manager: Optional settings manager for UI state persistence
        parent: Optional parent widget

    Returns:
        RVSection for RV config, FileDCCSection for all others.

    """
    if config.name == "rv":
        return RVSection(config, settings_manager=settings_manager, parent=parent)
    return FileDCCSection(config, settings_manager=settings_manager, parent=parent)


