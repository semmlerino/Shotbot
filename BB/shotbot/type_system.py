"""Enhanced type system with Protocol classes, TypedDict, and runtime type guards.

This module provides a comprehensive type system for the ShotBot application,
including Protocol definitions for interfaces, TypedDict for structured data,
Generic patterns, and runtime type checking utilities.
"""

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Literal,
    Optional,
    Protocol,
    Tuple,
    Type,
    TypedDict,
    TypeGuard,
    TypeVar,
    runtime_checkable,
)

from PySide6.QtCore import Signal
from PySide6.QtGui import QPixmap

# Type variables for generics
T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)
T_contra = TypeVar("T_contra", contravariant=True)


# ============================================================================
# TypedDict Definitions for Structured Configuration
# ============================================================================


class ShotData(TypedDict):
    """Type-safe shot data structure."""

    name: str
    sequence: str
    show: str
    description: Optional[str]
    status: Literal["active", "omit", "final"]
    thumbnail_path: Optional[str]
    workspace_path: str
    version: int
    metadata: Dict[str, Any]


class LauncherConfig(TypedDict, total=False):
    """Type-safe launcher configuration."""

    id: str
    name: str
    command: str
    icon: Optional[str]
    working_directory: Optional[str]
    environment: Dict[str, str]
    arguments: List[str]
    terminal: bool
    detached: bool
    timeout_seconds: int


class CacheConfig(TypedDict):
    """Type-safe cache configuration."""

    ttl_seconds: int
    max_size: int
    max_memory_mb: float
    eviction_policy: Literal["lru", "lfu", "fifo"]
    persistent: bool
    compression: bool


class UIConfig(TypedDict, total=False):
    """Type-safe UI configuration."""

    window_width: int
    window_height: int
    thumbnail_size: int
    grid_columns: int
    theme: Literal["dark", "light", "auto"]
    font_size: int
    show_tooltips: bool
    animations_enabled: bool


class ProcessResult(TypedDict):
    """Type-safe process execution result."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool
    error: Optional[str]


# ============================================================================
# Protocol Definitions for Interfaces
# ============================================================================


@runtime_checkable
class Cacheable(Protocol):
    """Protocol for cacheable objects."""

    def get_cache_key(self) -> str:
        """Get unique cache key for this object."""
        ...

    def serialize(self) -> bytes:
        """Serialize object for caching."""
        ...

    @classmethod
    def deserialize(cls, data: bytes) -> "Cacheable":
        """Deserialize object from cache."""
        ...


@runtime_checkable
class ThumbnailProvider(Protocol):
    """Protocol for thumbnail providers."""

    def get_thumbnail(self, path: Path, size: Tuple[int, int]) -> Optional[QPixmap]:
        """Get thumbnail for given path.

        Args:
            path: Path to file
            size: Desired thumbnail size

        Returns:
            QPixmap or None if unavailable
        """
        ...

    def has_thumbnail(self, path: Path) -> bool:
        """Check if thumbnail is available.

        Args:
            path: Path to check

        Returns:
            True if thumbnail available
        """
        ...


@runtime_checkable
class CommandExecutor(Protocol):
    """Protocol for command execution."""

    def execute(
        self,
        command: str,
        arguments: List[str],
        timeout: Optional[int] = None,
    ) -> ProcessResult:
        """Execute command with arguments.

        Args:
            command: Command to execute
            arguments: Command arguments
            timeout: Optional timeout in seconds

        Returns:
            ProcessResult with execution details
        """
        ...

    def execute_async(
        self,
        command: str,
        arguments: List[str],
        callback: Callable[[ProcessResult], None],
    ) -> None:
        """Execute command asynchronously.

        Args:
            command: Command to execute
            arguments: Command arguments
            callback: Callback for result
        """
        ...


@runtime_checkable
class ProgressReporter(Protocol):
    """Protocol for progress reporting."""

    def report_progress(
        self, current: int, total: int, message: Optional[str] = None
    ) -> None:
        """Report progress.

        Args:
            current: Current progress value
            total: Total progress value
            message: Optional status message
        """
        ...

    def is_cancelled(self) -> bool:
        """Check if operation was cancelled.

        Returns:
            True if cancelled
        """
        ...


@runtime_checkable
class ModelInterface(Protocol[T_co]):
    """Protocol for data models."""

    def get_items(self) -> List[T_co]:
        """Get all items from model."""
        ...

    def get_item(self, index: int) -> Optional[T_co]:
        """Get item at index."""
        ...

    def add_item(self, item: T_co) -> None:
        """Add item to model."""
        ...

    def remove_item(self, index: int) -> bool:
        """Remove item at index."""
        ...

    def clear(self) -> None:
        """Clear all items."""
        ...

    @property
    def count(self) -> int:
        """Get item count."""
        ...


@runtime_checkable
class ViewInterface(Protocol):
    """Protocol for view components."""

    def update_display(self) -> None:
        """Update view display."""
        ...

    def set_model(self, model: ModelInterface) -> None:
        """Set data model for view."""
        ...

    def get_selection(self) -> List[int]:
        """Get selected indices."""
        ...


# ============================================================================
# Generic Factory Patterns
# ============================================================================


class Factory(Generic[T]):
    """Generic factory for creating objects.

    Example:
        >>> factory = Factory[Widget]()
        >>> factory.register("button", ButtonWidget)
        >>> button = factory.create("button", text="Click")
    """

    def __init__(self):
        self._constructors: Dict[str, Type[T]] = {}

    def register(self, key: str, constructor: Type[T]) -> None:
        """Register a constructor.

        Args:
            key: Registration key
            constructor: Class constructor
        """
        self._constructors[key] = constructor

    def create(self, key: str, **kwargs) -> Optional[T]:
        """Create an instance.

        Args:
            key: Constructor key
            **kwargs: Constructor arguments

        Returns:
            Created instance or None
        """
        constructor = self._constructors.get(key)
        if constructor:
            try:
                return constructor(**kwargs)
            except Exception as e:
                print(f"Factory creation failed for {key}: {e}")
        return None

    def get_keys(self) -> List[str]:
        """Get registered keys.

        Returns:
            List of registered keys
        """
        return list(self._constructors.keys())


class Registry(Generic[T]):
    """Generic registry for managing instances.

    Example:
        >>> registry = Registry[Plugin]()
        >>> registry.register("my_plugin", plugin_instance)
        >>> plugin = registry.get("my_plugin")
    """

    def __init__(self):
        self._items: Dict[str, T] = {}

    def register(self, key: str, item: T) -> None:
        """Register an item.

        Args:
            key: Registration key
            item: Item to register
        """
        self._items[key] = item

    def unregister(self, key: str) -> Optional[T]:
        """Unregister an item.

        Args:
            key: Registration key

        Returns:
            Unregistered item or None
        """
        return self._items.pop(key, None)

    def get(self, key: str) -> Optional[T]:
        """Get registered item.

        Args:
            key: Registration key

        Returns:
            Registered item or None
        """
        return self._items.get(key)

    def get_all(self) -> Dict[str, T]:
        """Get all registered items.

        Returns:
            Dictionary of all items
        """
        return self._items.copy()

    def exists(self, key: str) -> bool:
        """Check if key exists.

        Args:
            key: Registration key

        Returns:
            True if key exists
        """
        return key in self._items


# ============================================================================
# Runtime Type Guards
# ============================================================================


def is_shot_data(obj: Any) -> TypeGuard[ShotData]:
    """Check if object is valid ShotData.

    Args:
        obj: Object to check

    Returns:
        True if object is valid ShotData
    """
    if not isinstance(obj, dict):
        return False

    required_keys = {"name", "sequence", "show", "workspace_path", "version"}
    if not required_keys.issubset(obj.keys()):
        return False

    # Check types
    if not isinstance(obj["name"], str):
        return False
    if not isinstance(obj["sequence"], str):
        return False
    if not isinstance(obj["show"], str):
        return False
    if not isinstance(obj["workspace_path"], str):
        return False
    if not isinstance(obj["version"], int):
        return False

    # Check optional fields if present
    if "status" in obj and obj["status"] not in ("active", "omit", "final"):
        return False

    return True


def is_launcher_config(obj: Any) -> TypeGuard[LauncherConfig]:
    """Check if object is valid LauncherConfig.

    Args:
        obj: Object to check

    Returns:
        True if object is valid LauncherConfig
    """
    if not isinstance(obj, dict):
        return False

    # Check required fields
    if "command" not in obj or not isinstance(obj["command"], str):
        return False

    # Check optional fields if present
    if "arguments" in obj and not isinstance(obj["arguments"], list):
        return False
    if "environment" in obj and not isinstance(obj["environment"], dict):
        return False
    if "terminal" in obj and not isinstance(obj["terminal"], bool):
        return False

    return True


def is_process_result(obj: Any) -> TypeGuard[ProcessResult]:
    """Check if object is valid ProcessResult.

    Args:
        obj: Object to check

    Returns:
        True if object is valid ProcessResult
    """
    if not isinstance(obj, dict):
        return False

    required_keys = {
        "command",
        "exit_code",
        "stdout",
        "stderr",
        "duration_ms",
        "timed_out",
    }
    if not required_keys.issubset(obj.keys()):
        return False

    # Type checks
    if not isinstance(obj["command"], str):
        return False
    if not isinstance(obj["exit_code"], int):
        return False
    if not isinstance(obj["stdout"], str):
        return False
    if not isinstance(obj["stderr"], str):
        return False
    if not isinstance(obj["duration_ms"], (int, float)):
        return False
    if not isinstance(obj["timed_out"], bool):
        return False

    return True


def validate_type(obj: Any, expected_type: Type[T]) -> T:
    """Validate and cast object to expected type.

    Args:
        obj: Object to validate
        expected_type: Expected type

    Returns:
        Validated object

    Raises:
        TypeError: If validation fails
    """
    if expected_type == ShotData:
        if not is_shot_data(obj):
            raise TypeError(f"Object is not valid ShotData: {obj}")
    elif expected_type == LauncherConfig:
        if not is_launcher_config(obj):
            raise TypeError(f"Object is not valid LauncherConfig: {obj}")
    elif expected_type == ProcessResult:
        if not is_process_result(obj):
            raise TypeError(f"Object is not valid ProcessResult: {obj}")
    else:
        if not isinstance(obj, expected_type):
            raise TypeError(f"Expected {expected_type}, got {type(obj)}")

    return obj


# ============================================================================
# Type-Safe Signal Patterns
# ============================================================================


class TypedSignal(Generic[T]):
    """Type-safe wrapper for Qt signals.

    Example:
        >>> class Model(QObject):
        ...     _data_changed = Signal(dict)
        ...     data_changed = TypedSignal[ShotData](_data_changed)
        >>> model.data_changed.connect(lambda data: print(data["name"]))
    """

    def __init__(
        self, signal: Signal, validator: Optional[Callable[[Any], bool]] = None
    ):
        """Initialize typed signal.

        Args:
            signal: Underlying Qt signal
            validator: Optional type validator
        """
        self._signal = signal
        self._validator = validator

    def connect(self, slot: Callable[[T], None]) -> None:
        """Connect to signal with type checking.

        Args:
            slot: Slot to connect
        """
        if self._validator:

            def validated_slot(data):
                if self._validator(data):
                    slot(data)
                else:
                    print(f"Signal data failed validation: {data}")

            self._signal.connect(validated_slot)
        else:
            self._signal.connect(slot)

    def disconnect(self, slot: Optional[Callable[[T], None]] = None) -> None:
        """Disconnect from signal.

        Args:
            slot: Specific slot to disconnect (all if None)
        """
        if slot:
            self._signal.disconnect(slot)
        else:
            self._signal.disconnect()

    def emit(self, data: T) -> None:
        """Emit signal with data.

        Args:
            data: Data to emit
        """
        if self._validator and not self._validator(data):
            raise TypeError(f"Signal data failed validation: {data}")
        self._signal.emit(data)


# ============================================================================
# Enum Types for Application
# ============================================================================


class ApplicationState(enum.Enum):
    """Application state enumeration."""

    INITIALIZING = "initializing"
    READY = "ready"
    LOADING = "loading"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


class FileType(enum.Enum):
    """File type enumeration."""

    SCENE_3DE = "3de"
    SCRIPT_NUKE = "nuke"
    SCENE_MAYA = "maya"
    IMAGE_SEQUENCE = "image_sequence"
    VIDEO = "video"
    UNKNOWN = "unknown"


class Priority(enum.IntEnum):
    """Priority levels."""

    CRITICAL = 1000
    HIGH = 750
    NORMAL = 500
    LOW = 250
    IDLE = 0


# ============================================================================
# Advanced Type Patterns
# ============================================================================


@dataclass
class Result(Generic[T]):
    """Type-safe result wrapper for operations.

    Example:
        >>> def divide(a: int, b: int) -> Result[float]:
        ...     if b == 0:
        ...         return Result.error("Division by zero")
        ...     return Result.success(a / b)
    """

    value: Optional[T] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None

    @classmethod
    def success(cls, value: T, **metadata) -> "Result[T]":
        """Create success result.

        Args:
            value: Success value
            **metadata: Additional metadata

        Returns:
            Success Result
        """
        return cls(value=value, metadata=metadata)

    @classmethod
    def error(cls, error: str, **metadata) -> "Result[T]":
        """Create error result.

        Args:
            error: Error message
            **metadata: Additional metadata

        Returns:
            Error Result
        """
        return cls(error=error, metadata=metadata)

    @property
    def is_success(self) -> bool:
        """Check if result is success."""
        return self.error is None

    @property
    def is_error(self) -> bool:
        """Check if result is error."""
        return self.error is not None

    def unwrap(self) -> T:
        """Unwrap value or raise.

        Returns:
            Success value

        Raises:
            ValueError: If result is error
        """
        if self.is_error:
            raise ValueError(f"Cannot unwrap error result: {self.error}")
        return self.value

    def unwrap_or(self, default: T) -> T:
        """Unwrap value or return default.

        Args:
            default: Default value

        Returns:
            Success value or default
        """
        return self.value if self.is_success else default

    def map(self, func: Callable[[T], "T"]) -> "Result[T]":
        """Map function over success value.

        Args:
            func: Mapping function

        Returns:
            Mapped Result
        """
        if self.is_success:
            try:
                return Result.success(func(self.value), **self.metadata)
            except Exception as e:
                return Result.error(str(e))
        return self


class Observable(Generic[T]):
    """Type-safe observable pattern.

    Example:
        >>> observable = Observable[int](initial_value=0)
        >>> observable.subscribe(lambda x: print(f"Value: {x}"))
        >>> observable.set(42)  # Prints: Value: 42
    """

    def __init__(self, initial_value: Optional[T] = None):
        """Initialize observable.

        Args:
            initial_value: Initial value
        """
        self._value = initial_value
        self._observers: List[Callable[[T], None]] = []

    def get(self) -> Optional[T]:
        """Get current value."""
        return self._value

    def set(self, value: T) -> None:
        """Set value and notify observers.

        Args:
            value: New value
        """
        self._value = value
        self._notify()

    def subscribe(self, observer: Callable[[T], None]) -> Callable[[], None]:
        """Subscribe to changes.

        Args:
            observer: Observer callback

        Returns:
            Unsubscribe function
        """
        self._observers.append(observer)

        def unsubscribe():
            if observer in self._observers:
                self._observers.remove(observer)

        return unsubscribe

    def _notify(self) -> None:
        """Notify all observers."""
        for observer in self._observers:
            try:
                observer(self._value)
            except Exception as e:
                print(f"Observer error: {e}")
