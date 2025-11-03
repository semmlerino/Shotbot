"""Test file to verify reportUnusedCallResult detection - statement level."""


def returns_int() -> int:
    """Function that returns an int."""
    return 42


def returns_none() -> None:
    """Function that returns None."""


# At module level - these are CALL STATEMENTS
returns_int()  # Should trigger reportUnusedCallResult
returns_none()  # Should NOT trigger (returns None)


def test_function() -> None:
    """Test function with unused call results."""
    # These are CALL STATEMENTS - should trigger
    returns_int()
    {}.setdefault("key", "value")

    # This is fine - assigned to _
    _ = returns_int()

    # This is fine - assigned to variable
    result = returns_int()
    print(result)

    # This should NOT trigger - returns None
    returns_none()
