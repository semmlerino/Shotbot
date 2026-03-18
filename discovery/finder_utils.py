"""Common utilities for all finder implementations.

This module provides reusable utility functions that are shared across
multiple finder classes, eliminating code duplication and providing
a single source of truth for common operations.
"""

from __future__ import annotations

# Standard library imports
import re


# Compiled regex patterns for performance
USERNAME_VALIDATION_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
PATH_TRAVERSAL_PATTERN = re.compile(r"[./\\]")


def sanitize_username(raw_username: str) -> str:
    """Sanitize username to prevent security issues.

    Removes path traversal characters and validates the username
    contains only alphanumeric characters, dashes, and underscores.

    Args:
        raw_username: Raw username input

    Returns:
        Sanitized username

    Raises:
        ValueError: If username is invalid after sanitization

    """
    # Remove any path traversal characters (., /, \) but keep hyphens
    username = PATH_TRAVERSAL_PATTERN.sub("", raw_username)

    # Validate that username is not empty after sanitization
    if not username:
        msg = f"Invalid username after sanitization: '{raw_username}'"
        raise ValueError(msg)

    # Additional validation: username should only contain alphanumeric, dash, and underscore
    if not USERNAME_VALIDATION_PATTERN.match(username):
        msg = f"Username contains invalid characters: '{username}'"
        raise ValueError(msg)

    return username
