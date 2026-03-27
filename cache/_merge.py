"""Merge helper for cache operations.

Provides shared merge logic used by ShotDataCache and SceneDiskCache.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# TypeVars for build_merge_lookups generic helper
_D = TypeVar("_D")
_S = TypeVar("_S")


def build_merge_lookups(
    cached: Sequence[_S] | None,
    fresh: Sequence[_S],
    to_dict_fn: Callable[[_S], _D],
    get_key_fn: Callable[[_D], tuple[str, str, str]],
) -> tuple[
    list[_D], list[_D], dict[tuple[str, str, str], _D], set[tuple[str, str, str]]
]:
    """Build lookup structures shared by cache merge operations.

    Lock acquisition is NOT done here — callers are responsible for holding
    the lock and passing already-copied sequences. This helper operates
    purely on local data.

    Args:
        cached: Previously cached items (objects or dicts), or None
        fresh: Fresh items from discovery
        to_dict_fn: Converts each item to its dict representation
        get_key_fn: Extracts the composite (show, sequence, shot) key

    Returns:
        Tuple of (cached_dicts, fresh_dicts, cached_by_key, fresh_keys)

    """
    cached_dicts = [to_dict_fn(s) for s in (cached or [])]
    fresh_dicts = [to_dict_fn(s) for s in fresh]
    cached_by_key: dict[tuple[str, str, str], _D] = {
        get_key_fn(item): item for item in cached_dicts
    }
    fresh_keys = {get_key_fn(item) for item in fresh_dicts}
    return cached_dicts, fresh_dicts, cached_by_key, fresh_keys
