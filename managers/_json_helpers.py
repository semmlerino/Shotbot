"""Shared JSON loading and validation utilities for persistence managers.

This module provides a reusable helper for loading JSON files with type
validation and error handling, avoiding duplication across managers.
"""

from __future__ import annotations

import json
from logging import Logger
from pathlib import Path
from typing import TypeVar


T = TypeVar("T")


def load_validated_json(
    path: Path, expected_type: type[T], default: T, logger: Logger
) -> T:
    """Load JSON file with type validation and error handling.

    Returns `default` if file doesn't exist, can't be parsed, or loaded data
    doesn't match `expected_type`.

    Args:
        path: Path to the JSON file to load
        expected_type: The expected Python type of the loaded data
        default: Default value to return on any error
        logger: Logger instance for error reporting

    Returns:
        Loaded and validated data, or `default` if any validation step fails
    """
    if not path.exists():
        return default

    try:
        with path.open() as f:
            data: object = json.load(f)  # pyright: ignore[reportAny]
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load %s: %s", path, e)
        return default

    if not isinstance(data, expected_type):
        logger.error(
            "Expected %s in %s, got %s",
            expected_type.__name__,
            path,
            type(data).__name__,
        )
        return default

    return data  # pyright: ignore[reportReturnType]
