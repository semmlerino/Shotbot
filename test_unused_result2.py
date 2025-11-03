"""Test file to verify reportUnusedCallResult detection with known types."""


def returns_int() -> int:
    """Function that returns an int."""
    return 42


def test_function() -> None:
    """Test function with unused call result."""
    # This SHOULD trigger reportUnusedCallResult
    returns_int()

    # This should be fine
    _ = returns_int()

    # This should also be fine
    result = returns_int()
    print(result)
