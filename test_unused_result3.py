"""Test file to verify reportUnusedCallResult detection."""

from typing import assert_type


def returns_dict() -> dict[str, int]:
    """Function that returns a dict."""
    return {}


def test_function() -> None:
    """Test function with unused call results that should trigger warnings."""
    # These SHOULD trigger reportUnusedCallResult
    {}.setdefault("key", "value")
    returns_dict()
    assert_type({}, dict)

    # This should be fine
    _ = returns_dict()
