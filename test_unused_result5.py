"""Test file - exact example from GitHub issue #330."""


class Foo:
    """Test class."""

    def __init__(self, x: int) -> None:
        """Initialize with x."""
        self.x = x


# This should trigger reportUnusedCallResult
Foo(1)
