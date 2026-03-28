"""Unit tests for ResizableFrame widget."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QLabel, QWidget


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from ui.resizable_frame import ResizableFrame


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


@pytest.fixture(autouse=True)
def cleanup_qt_state(qtbot: QtBot) -> None:
    """Ensure Qt state is cleaned up after each test."""
    yield
    qtbot.wait(1)


class TestResizableFrameInitialization:
    """Tests for ResizableFrame initialization."""

    def test_creates_with_default_height(self, qtbot: QtBot) -> None:
        """Widget initializes with specified initial height."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            initial_height=150,
        )
        qtbot.addWidget(frame)

        assert child.height() == 150
        # Frame height = child height + 6px handle
        assert frame.height() == 156

    def test_clamps_initial_height_to_minimum(self, qtbot: QtBot) -> None:
        """Initial height is clamped to minimum if too small."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            min_height=60,
            initial_height=30,  # Below min
        )
        qtbot.addWidget(frame)

        assert child.height() == 60

    def test_clamps_initial_height_to_maximum(self, qtbot: QtBot) -> None:
        """Initial height is clamped to maximum if too large."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            max_height=400,
            initial_height=500,  # Above max
        )
        qtbot.addWidget(frame)

        assert child.height() == 400

    def test_accepts_parent_widget(self, qtbot: QtBot) -> None:
        """Parent widget is properly set."""
        parent = QWidget()
        qtbot.addWidget(parent)

        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            parent=parent,
        )

        assert frame.parent() is parent


class TestResizableFrameProperties:
    """Tests for ResizableFrame property access."""

    def test_content_height_returns_child_height(self, qtbot: QtBot) -> None:
        """content_height() returns the child widget's height."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            initial_height=180,
        )
        qtbot.addWidget(frame)

        assert frame.content_height() == 180

    def test_min_height_property(self, qtbot: QtBot) -> None:
        """min_height property returns configured minimum."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            min_height=80,
        )
        qtbot.addWidget(frame)

        assert frame.min_height == 80

    def test_max_height_property(self, qtbot: QtBot) -> None:
        """max_height property returns configured maximum."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            max_height=350,
        )
        qtbot.addWidget(frame)

        assert frame.max_height == 350


class TestResizableFrameSetHeight:
    """Tests for ResizableFrame.set_height()."""

    def test_set_height_updates_child(self, qtbot: QtBot) -> None:
        """set_height() updates child widget height."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            initial_height=120,
        )
        qtbot.addWidget(frame)

        frame.set_height(200)

        assert child.height() == 200
        assert frame.height() == 206

    def test_set_height_clamps_to_minimum(self, qtbot: QtBot) -> None:
        """set_height() clamps value to minimum."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            min_height=60,
            initial_height=120,
        )
        qtbot.addWidget(frame)

        frame.set_height(20)  # Below min

        assert child.height() == 60

    def test_set_height_clamps_to_maximum(self, qtbot: QtBot) -> None:
        """set_height() clamps value to maximum."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            max_height=400,
            initial_height=120,
        )
        qtbot.addWidget(frame)

        frame.set_height(600)  # Above max

        assert child.height() == 400


class TestResizableFrameSignals:
    """Tests for ResizableFrame signal emission."""

    def test_height_changed_signal_emitted_on_set_height(self, qtbot: QtBot) -> None:
        """height_changed signal is NOT emitted on set_height().

        The signal is only emitted when user drags the resize handle.
        Programmatic set_height() does not emit the signal.
        """
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            initial_height=120,
        )
        qtbot.addWidget(frame)

        # Signal should NOT emit on programmatic set_height
        signal_received = []
        frame.height_changed.connect(lambda h: signal_received.append(h))

        frame.set_height(200)
        qtbot.wait(1)

        # No signal expected from programmatic change
        assert len(signal_received) == 0

    def test_height_changed_signal_can_be_connected(self, qtbot: QtBot) -> None:
        """height_changed signal can be connected to a slot."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            initial_height=120,
        )
        qtbot.addWidget(frame)

        received_values: list[int] = []
        frame.height_changed.connect(received_values.append)

        # Manually emit to test connection
        frame.height_changed.emit(250)
        qtbot.waitUntil(lambda: 250 in received_values, timeout=5000)

        assert 250 in received_values


class TestResizableFrameLayout:
    """Tests for ResizableFrame layout behavior."""

    def test_child_is_parented_to_frame(self, qtbot: QtBot) -> None:
        """Child widget is reparented to the frame."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            initial_height=120,
        )
        qtbot.addWidget(frame)

        assert child.parent() is frame

    def test_frame_has_fixed_height(self, qtbot: QtBot) -> None:
        """Frame has fixed height (child + 6px handle)."""
        child = QLabel("Test")
        frame = ResizableFrame(
            child_widget=child,
            initial_height=100,
        )
        qtbot.addWidget(frame)

        # Frame should have fixed height policy
        assert frame.height() == 106
