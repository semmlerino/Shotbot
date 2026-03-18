"""Protocol definitions for ShotBot application.

This module defines Protocol classes for better type safety and
interface design throughout the application.
"""

from __future__ import annotations

# Standard library imports
from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable
    from pathlib import Path

    # Local application imports


@runtime_checkable
class SceneDataProtocol(Protocol):
    """Common interface for Shot and ThreeDEScene data objects.

    This protocol defines the shared interface between Shot and ThreeDEScene,
    allowing ItemModels to work with either type through a common interface.
    """

    show: str
    sequence: str
    shot: str
    workspace_path: str

    @property
    def full_name(self) -> str:
        """Get full name of the scene/shot."""
        ...

    def get_thumbnail_path(self) -> Path | None:
        """Get path to thumbnail image."""
        ...


@runtime_checkable
class ProcessPoolInterface(Protocol):
    """Protocol for process pool implementations.

    Both ProcessPoolManager and MockWorkspacePool must implement this interface.
    """

    def execute_workspace_command(
        self,
        command: str,
        cache_ttl: int = 30,
        timeout: int | None = None,
        use_login_shell: bool = False,
        cancel_flag: Callable[[], bool] | None = None,
    ) -> str:
        """Execute workspace command."""
        ...

    def invalidate_cache(self, pattern: str | None = None) -> None:
        """Invalidate command cache."""
        ...

    def shutdown(self) -> None:
        """Shutdown the process pool."""
        ...
