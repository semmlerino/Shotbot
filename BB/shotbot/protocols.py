"""Protocol definitions for ShotBot application.

This module defines Protocol classes for better type safety and
interface design throughout the application.
"""

from pathlib import Path

# Import RefreshResult from shot_model where it's properly defined as NamedTuple
from typing import TYPE_CHECKING, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from shot_model import RefreshResult


@runtime_checkable
class CacheableProtocol(Protocol):
    """Protocol for objects that can be cached."""

    def to_dict(self) -> dict:
        """Convert object to dictionary for caching."""
        ...

    @classmethod
    def from_dict(cls, data: dict) -> "CacheableProtocol":
        """Create object from cached dictionary."""
        ...


@runtime_checkable
class RefreshableProtocol(Protocol):
    """Protocol for objects that support data refreshing."""

    def refresh_data(self) -> "RefreshResult":
        """Refresh data from source."""
        ...

    def is_stale(self) -> bool:
        """Check if data needs refreshing."""
        ...


@runtime_checkable
class ThumbnailProviderProtocol(Protocol):
    """Protocol for objects that can provide thumbnail paths."""

    def get_thumbnail_path(self) -> Optional[Path]:
        """Get thumbnail path for the object."""
        ...

    @property
    def thumbnail_dir(self) -> Path:
        """Get thumbnail directory path."""
        ...


@runtime_checkable
class LaunchableProtocol(Protocol):
    """Protocol for objects that can be launched."""

    def launch(self, **kwargs) -> bool:
        """Launch the object."""
        ...

    @property
    def is_available(self) -> bool:
        """Check if the object can be launched."""
        ...


@runtime_checkable
class ValidatableProtocol(Protocol):
    """Protocol for objects that can be validated."""

    def validate(self) -> List[str]:
        """Validate object and return list of errors."""
        ...

    @property
    def is_valid(self) -> bool:
        """Check if object is currently valid."""
        ...


@runtime_checkable
class DataModelProtocol(Protocol):
    """Protocol for data model classes."""

    def get_data(self) -> List[dict]:
        """Get all data items."""
        ...

    def refresh_data(self) -> "RefreshResult":
        """Refresh data from source."""
        ...

    def find_item_by_name(self, name: str) -> Optional[dict]:
        """Find item by name."""
        ...


@runtime_checkable
class WorkerProtocol(Protocol):
    """Protocol for background worker threads."""

    def start_work(self) -> None:
        """Start the worker."""
        ...

    def stop_work(self) -> None:
        """Stop the worker."""
        ...

    @property
    def is_running(self) -> bool:
        """Check if worker is currently running."""
        ...
