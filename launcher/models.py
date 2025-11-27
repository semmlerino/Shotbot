"""Data models for launcher system.

This module contains all the data structures used by the launcher system,
including parameter validation and command building capabilities.
"""

from __future__ import annotations

# Standard library imports
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict


if TYPE_CHECKING:
    # Standard library imports
    import subprocess
    from typing import TextIO


class ProcessInfoDict(TypedDict):
    """Type definition for process information dictionary."""

    type: str
    key: str
    launcher_id: str
    launcher_name: str
    command: str
    pid: int
    running: bool
    start_time: float


class ParameterType(Enum):
    """Parameter types for launcher configuration."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    PATH = "path"
    CHOICE = "choice"
    FILE = "file"
    DIRECTORY = "directory"


@dataclass
class LauncherParameter:
    """Represents a configurable parameter for a launcher."""

    name: str
    param_type: ParameterType
    label: str
    description: str = ""
    default_value: str | int | float | bool | None = None
    required: bool = False
    choices: list[str] = field(default_factory=list)
    min_value: int | float | None = None
    max_value: int | float | None = None
    file_filter: str = ""  # For file/directory parameters
    placeholder: str = ""

    def __post_init__(self) -> None:
        """Validate parameter configuration."""
        if not self.name:
            raise ValueError("Parameter name cannot be empty")

        if not self.name.isidentifier():
            raise ValueError(
                f"Parameter name '{self.name}' must be a valid Python identifier"
            )

        if not self.label:
            raise ValueError("Parameter label cannot be empty")

        # Validate choices for CHOICE type
        if self.param_type == ParameterType.CHOICE:
            if not self.choices:
                raise ValueError("CHOICE parameter must have at least one choice")
            if self.default_value and self.default_value not in self.choices:
                raise ValueError(f"Default value '{self.default_value}' not in choices")

        # Validate numeric ranges
        if self.param_type in (ParameterType.INTEGER, ParameterType.FLOAT):
            if (
                self.min_value is not None
                and self.max_value is not None
                and self.min_value > self.max_value
            ):
                raise ValueError("min_value cannot be greater than max_value")

            if self.default_value is not None and isinstance(
                self.default_value, (int, float)
            ):
                if self.min_value is not None and self.default_value < self.min_value:
                    raise ValueError("Default value is below minimum")
                if self.max_value is not None and self.default_value > self.max_value:
                    raise ValueError("Default value is above maximum")

    def validate_value(self, value: str | int | float | bool | None) -> bool:
        """Validate a value against this parameter's constraints.

        Args:
            value: Value to validate

        Returns:
            True if value is valid, False otherwise
        """
        if value is None:
            return not self.required

        try:
            if self.param_type == ParameterType.STRING:
                return isinstance(value, str)

            if self.param_type == ParameterType.INTEGER:
                if not isinstance(value, int):
                    return False
                if self.min_value is not None and value < self.min_value:
                    return False
                return not (self.max_value is not None and value > self.max_value)

            if self.param_type == ParameterType.FLOAT:
                if not isinstance(value, int | float):
                    return False
                if self.min_value is not None and value < self.min_value:
                    return False
                return not (self.max_value is not None and value > self.max_value)

            if self.param_type == ParameterType.BOOLEAN:
                return isinstance(value, bool)

            if self.param_type == ParameterType.PATH:
                return isinstance(value, str)

            if self.param_type == ParameterType.CHOICE:
                return value in self.choices

            if self.param_type in (ParameterType.FILE, ParameterType.DIRECTORY):
                return isinstance(value, str)

            return False

        except Exception:
            return False

    def to_dict(self) -> dict[str, str | int | float | bool | list[str] | None]:
        """Convert parameter to dictionary for serialization."""
        data = asdict(self)
        # Convert enum to string
        data["param_type"] = self.param_type.value
        return data

    @classmethod
    def from_dict(
        cls, data: dict[str, str | int | float | bool | list[str] | None]
    ) -> LauncherParameter:
        """Create parameter from dictionary.

        Args:
            data: Dictionary containing parameter data

        Returns:
            LauncherParameter instance

        Raises:
            ValueError: If data is invalid
        """
        try:
            # Create a mutable copy for modification
            data_copy: dict[
                str, str | int | float | bool | list[str] | None | ParameterType
            ] = dict(data)

            # Convert param_type string back to enum
            if "param_type" in data_copy:
                param_type_value = data_copy["param_type"]
                if isinstance(param_type_value, str):
                    data_copy["param_type"] = ParameterType(param_type_value)

            return cls(**data_copy)  # pyright: ignore[reportArgumentType]

        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid parameter data: {e}") from e


@dataclass
class LauncherValidation:
    """Validation settings for a launcher."""

    check_executable: bool = True
    required_files: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(
        default_factory=lambda: [
            r";\s*rm\s",
            r";\s*sudo\s",
            r";\s*su\s",
            r"&&\s*rm\s",
            r"\|\s*rm\s",
            r"`rm\s",
            r"\$\(rm\s",
        ],
    )
    working_directory: str | None = None
    resolve_paths: bool = False


@dataclass
class LauncherTerminal:
    """Terminal settings for a launcher.

    Attributes:
        required: Whether a terminal is required for this launcher
        persist: Whether to keep terminal open after command exits
        background: Whether to background the process and close terminal immediately.
            When True, the app is launched with `& disown; exit` so the terminal
            closes immediately while the app continues running. Useful for GUI apps
            to avoid terminal clutter.
        title: Optional title for the terminal window
    """

    required: bool = False
    persist: bool = False
    background: bool = False
    title: str | None = None


@dataclass
class LauncherEnvironment:
    """Environment settings for a launcher.

    Attributes:
        type: Environment type ("bash" or "rez")
        packages: Rez packages to load (only used when type="rez")
        source_files: Shell scripts to source before command
        command_prefix: Command/env vars to prepend to the command
    """

    type: str = "bash"  # "bash" or "rez"
    packages: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    command_prefix: str | None = None


@dataclass
class CustomLauncher:
    """Represents a custom application launcher."""

    id: str
    name: str
    description: str
    command: str
    category: str = "custom"
    variables: dict[str, str] = field(default_factory=dict)
    environment: LauncherEnvironment = field(default_factory=LauncherEnvironment)
    terminal: LauncherTerminal = field(default_factory=LauncherTerminal)
    validation: LauncherValidation = field(default_factory=LauncherValidation)
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    def to_dict(
        self,
    ) -> dict[str, str | dict[str, str | bool | list[str] | None] | list[str]]:
        """Convert launcher to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, str | dict[str, str | bool | list[str] | None] | list[str]],
    ) -> CustomLauncher:
        """Create launcher from dictionary data."""
        # Create a mutable copy for modification
        data_copy: dict[
            str,
            str
            | dict[str, str | bool | list[str] | None]
            | list[str]
            | LauncherEnvironment
            | LauncherTerminal
            | LauncherValidation,
        ] = dict(data)

        # Handle nested objects
        if "environment" in data_copy:
            env_data = data_copy["environment"]
            if isinstance(env_data, dict):
                # Extract and validate packages list
                packages_value = env_data.get("packages", [])
                packages: list[str] = []
                if isinstance(packages_value, list):
                    packages = [str(item) for item in packages_value]

                # Extract and validate source_files list
                source_files_value = env_data.get("source_files", [])
                source_files: list[str] = []
                if isinstance(source_files_value, list):
                    source_files = [str(item) for item in source_files_value]

                data_copy["environment"] = LauncherEnvironment(
                    type=str(env_data.get("type", "bash")),
                    packages=packages,
                    source_files=source_files,
                    command_prefix=str(env_data["command_prefix"])
                    if env_data.get("command_prefix") is not None
                    else None,
                )

        if "terminal" in data_copy:
            term_data = data_copy["terminal"]
            if isinstance(term_data, dict):
                data_copy["terminal"] = LauncherTerminal(
                    required=bool(term_data.get("required", False)),
                    persist=bool(term_data.get("persist", False)),
                    background=bool(term_data.get("background", False)),
                    title=str(term_data["title"])
                    if term_data.get("title") is not None
                    else None,
                )

        if "validation" in data_copy:
            val_data = data_copy["validation"]
            if isinstance(val_data, dict):
                # Extract and validate required_files list
                required_files_value = val_data.get("required_files", [])
                required_files: list[str] = []
                if isinstance(required_files_value, list):
                    required_files = [str(item) for item in required_files_value]

                # Extract and validate forbidden_patterns list
                forbidden_patterns_value = val_data.get("forbidden_patterns", [])
                forbidden_patterns: list[str] = []
                if isinstance(forbidden_patterns_value, list):
                    forbidden_patterns = [
                        str(item) for item in forbidden_patterns_value
                    ]

                data_copy["validation"] = LauncherValidation(
                    check_executable=bool(val_data.get("check_executable", True)),
                    required_files=required_files,
                    forbidden_patterns=forbidden_patterns,
                    working_directory=str(val_data["working_directory"])
                    if val_data.get("working_directory") is not None
                    else None,
                    resolve_paths=bool(val_data.get("resolve_paths", False)),
                )

        return cls(**data_copy)  # pyright: ignore[reportArgumentType]


class ProcessInfo:
    """Information about an active process."""

    # Type annotations for instance attributes
    process: subprocess.Popen[bytes]
    launcher_id: str
    launcher_name: str
    command: str
    timestamp: float
    validated: bool
    log_file: Path | None
    stderr_handle: TextIO | None

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        process: subprocess.Popen[bytes],
        launcher_id: str,
        launcher_name: str,
        command: str,
        timestamp: float,
        log_file: Path | None = None,
        stderr_handle: TextIO | None = None,
    ) -> None:
        """Initialize ProcessInfo.

        Args:
            process: The subprocess.Popen object
            launcher_id: Unique identifier for the launcher
            launcher_name: Human-readable launcher name
            command: The command that was executed
            timestamp: Start timestamp
            log_file: Path to stderr log file for debugging launch failures
            stderr_handle: Open file handle for stderr (must be closed when process exits)
        """
        self.process = process
        self.launcher_id = launcher_id
        self.launcher_name = launcher_name
        self.command = command
        self.timestamp = timestamp
        self.validated = False  # Whether process startup was validated
        self.log_file = log_file  # Path to stderr log file
        self.stderr_handle = stderr_handle  # Open file handle (prevents GC race)
