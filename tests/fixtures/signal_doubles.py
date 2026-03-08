"""Signal test doubles.

Classes:
    SignalDouble: Lightweight signal test double for non-Qt objects
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Callable


class SignalDouble:
    """Lightweight signal test double for non-Qt objects.

    Use this instead of trying to use QSignalSpy on Mock objects,
    which will crash. This provides a simple interface for testing
    signal emissions and connections.

    Example:
        signal = SignalDouble()
        results = []
        signal.connect(lambda *args: results.append(args))
        signal.emit("test", 123)
        assert signal.was_emitted
        assert results == [("test", 123)]

    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize the test signal."""
        self.emissions: list[tuple[Any, ...]] = []
        self.callbacks: list[Callable[..., Any]] = []

    def emit(self, *args: Any) -> None:
        """Emit the signal with arguments."""
        self.emissions.append(args)
        for callback in self.callbacks:
            try:
                callback(*args)
            except Exception as e:  # noqa: BLE001
                print(f"SignalDouble callback error: {e}")

    def connect(self, callback: Callable[..., Any], connection_type: Any = None) -> None:
        """Connect a callback to the signal.

        Args:
            callback: Callable to invoke on emit.
            connection_type: Ignored; accepted for Qt API compatibility.
        """
        self.callbacks.append(callback)

    def disconnect(self, callback: Callable[..., Any] | None = None) -> None:
        """Disconnect a callback or all callbacks."""
        if callback is None:
            self.callbacks.clear()
        elif callback in self.callbacks:
            self.callbacks.remove(callback)

    @property
    def was_emitted(self) -> bool:
        """Check if the signal was emitted at least once."""
        return len(self.emissions) > 0

    @property
    def emit_count(self) -> int:
        """Get the number of times the signal was emitted."""
        return len(self.emissions)

    def get_last_emission(self) -> tuple[Any, ...] | None:
        """Get the arguments from the last emission."""
        if self.emissions:
            return self.emissions[-1]
        return None

    def clear(self) -> None:
        """Clear emission history and callbacks."""
        self.emissions.clear()
        self.callbacks.clear()

    def reset(self) -> None:
        """Reset emission history (keeps callbacks)."""
        self.emissions.clear()


