"""Test file to verify reportUnusedCallResult detection."""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QWidget


class TestWidget(QWidget):
    """Test widget for unused call results."""

    my_signal = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize test widget."""
        super().__init__(parent)

        # This should trigger reportUnusedCallResult
        self.my_signal.connect(self.slot_method)

        # This should also trigger reportUnusedCallResult
        QTimer.singleShot(100, self.slot_method)

    def slot_method(self) -> None:
        """Slot method."""
