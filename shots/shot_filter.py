"""Functional shot filtering utilities.

This module provides composable filter functions for shot collections.
All functions are pure (no side effects) for easy testing and reuse.

Benefits of functional approach:
- Pure functions with no side effects
- Easily testable in isolation
- Works with any sequence of shot-like objects
- No object allocation overhead
- Immutable operations prevent state bugs
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar


if TYPE_CHECKING:
    from collections.abc import Sequence


class Filterable(Protocol):
    """Protocol for filterable shot-like objects.

    Any object with `show` and `full_name` attributes can be filtered.
    This uses structural typing (duck typing) for maximum flexibility.

    Note: full_name can be a property or attribute - both work.
    """

    show: str

    @property
    def full_name(self) -> str:
        """Full name property for filtering."""
        ...


# TypeVar for preserving input type through filtering
T = TypeVar("T", bound=Filterable)


def filter_by_show(
    items: Sequence[T],
    show: str | None,
) -> list[T]:
    """Filter items by show name.

    Args:
        items: Sequence of filterable items
        show: Show name to filter by, or None to include all shows

    Returns:
        List of items matching the show filter

    Examples:
        >>> shots = [
        ...     Shot("show1", "seq1", "shot1", "/path1"),
        ...     Shot("show2", "seq1", "shot2", "/path2"),
        ... ]
        >>> filtered = filter_by_show(shots, "show1")
        >>> len(filtered)
        1

    """
    if show is None:
        return list(items)
    return [item for item in items if item.show == show]


def filter_by_text(
    items: Sequence[T],
    text: str | None,
) -> list[T]:
    """Filter items by text substring (case-insensitive).

    Args:
        items: Sequence of filterable items
        text: Text to search for in full_name, or None for no filtering

    Returns:
        List of items matching the text filter

    Examples:
        >>> shots = [
        ...     Shot("show1", "seq1", "shot1", "/path1"),
        ...     Shot("show1", "seq2", "shot2", "/path2"),
        ... ]
        >>> filtered = filter_by_text(shots, "shot1")
        >>> len(filtered)
        1

    """
    if not text:
        return list(items)

    text_lower = text.strip().lower()
    return [item for item in items if text_lower in item.full_name.lower()]


def compose_filters(
    items: Sequence[T],
    show: str | None = None,
    text: str | None = None,
) -> list[T]:
    """Apply multiple filters in sequence (AND logic).

    Filters are applied in order: show filter, then text filter.

    Args:
        items: Sequence of filterable items
        show: Show name to filter by, or None
        text: Text to search for, or None

    Returns:
        List of items passing all filters

    Examples:
        >>> shots = [
        ...     Shot("show1", "seq1", "shot1", "/path1"),
        ...     Shot("show1", "seq2", "shot2", "/path2"),
        ...     Shot("show2", "seq1", "shot3", "/path3"),
        ... ]
        >>> filtered = compose_filters(shots, show="show1", text="shot1")
        >>> len(filtered)
        1

    """
    result = list(items)

    # Apply show filter if specified
    if show is not None:
        result = filter_by_show(result, show)

    # Apply text filter if specified
    if text is not None:
        result = filter_by_text(result, text)

    return result


def get_available_shows(items: Sequence[T]) -> set[str]:
    """Extract unique show names from items.

    Args:
        items: Sequence of filterable items

    Returns:
        Set of unique show names

    Examples:
        >>> shots = [
        ...     Shot("show1", "seq1", "shot1", "/path1"),
        ...     Shot("show2", "seq1", "shot2", "/path2"),
        ...     Shot("show1", "seq2", "shot3", "/path3"),
        ... ]
        >>> shows = get_available_shows(shots)
        >>> len(shows)
        2
        >>> "show1" in shows and "show2" in shows
        True

    """
    return {item.show for item in items}
