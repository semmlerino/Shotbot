"""Typing compatibility shim for Python 3.11+.

This module provides typing features that may not be available in older Python versions.
Specifically, it provides the `override` decorator which was added to typing in Python 3.12.
"""

import sys


if sys.version_info >= (3, 12):
    from typing import override
else:  # pragma: no cover
    from typing_extensions import override


__all__ = ["override"]
