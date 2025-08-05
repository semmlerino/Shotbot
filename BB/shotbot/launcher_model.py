"""Data models for custom launcher configuration.

This module provides the core data structures for defining and validating
custom application launchers in ShotBot. It includes:

- ParameterType: Enum defining supported parameter types
- LauncherParameter: Configurable parameter with validation
- Launcher: Complete launcher definition with command building
- Schema validation utilities

The models support serialization to/from JSON and comprehensive validation
to ensure launcher configurations are valid and safe to execute.

Example:
    # Create a simple launcher
    launcher = Launcher(
        id="my_app",
        name="My Application",
        command="myapp {input_file}",
        parameters=[
            LauncherParameter(
                name="input_file",
                param_type=ParameterType.FILE,
                label="Input File",
                required=True
            )
        ]
    )

    # Build command with parameters
    command_args = launcher.build_command({"input_file": "test.txt"})
"""

import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

# Set up logger for this module
logger = logging.getLogger(__name__)


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
    default_value: Optional[Union[str, int, float, bool]] = None
    required: bool = False
    choices: List[str] = field(default_factory=list)
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    file_filter: str = ""  # For file/directory parameters
    placeholder: str = ""

    def __post_init__(self):
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
            if self.min_value is not None and self.max_value is not None:
                if self.min_value > self.max_value:
                    raise ValueError("min_value cannot be greater than max_value")

            if self.default_value is not None:
                if self.min_value is not None and self.default_value < self.min_value:
                    raise ValueError("Default value is below minimum")
                if self.max_value is not None and self.default_value > self.max_value:
                    raise ValueError("Default value is above maximum")

    def validate_value(self, value: Any) -> bool:
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

            elif self.param_type == ParameterType.INTEGER:
                if not isinstance(value, int):
                    return False
                if self.min_value is not None and value < self.min_value:
                    return False
                if self.max_value is not None and value > self.max_value:
                    return False
                return True

            elif self.param_type == ParameterType.FLOAT:
                if not isinstance(value, (int, float)):
                    return False
                if self.min_value is not None and value < self.min_value:
                    return False
                if self.max_value is not None and value > self.max_value:
                    return False
                return True

            elif self.param_type == ParameterType.BOOLEAN:
                return isinstance(value, bool)

            elif self.param_type == ParameterType.PATH:
                if not isinstance(value, str):
                    return False
                # Optional: validate path exists
                return True

            elif self.param_type == ParameterType.CHOICE:
                return value in self.choices

            elif self.param_type in (ParameterType.FILE, ParameterType.DIRECTORY):
                if not isinstance(value, str):
                    return False
                # Optional: validate file/directory exists
                return True

            return False

        except Exception as e:
            logger.warning(f"Error validating parameter value: {e}")
            return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert parameter to dictionary for serialization."""
        data = asdict(self)
        # Convert enum to string
        data["param_type"] = self.param_type.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LauncherParameter":
        """Create parameter from dictionary.

        Args:
            data: Dictionary containing parameter data

        Returns:
            LauncherParameter instance

        Raises:
            ValueError: If data is invalid
        """
        try:
            # Convert param_type string back to enum
            if "param_type" in data:
                data["param_type"] = ParameterType(data["param_type"])

            return cls(**data)

        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid parameter data: {e}")


@dataclass
class Launcher:
    """Represents a custom application launcher."""

    # Required fields
    id: str  # Unique identifier
    name: str  # Display name
    command: str  # Command to execute

    # Optional fields
    description: str = ""
    icon_path: str = ""
    category: str = "Custom"
    enabled: bool = True
    show_in_context_menu: bool = True
    working_directory: str = ""
    environment_vars: Dict[str, str] = field(default_factory=dict)
    parameters: List[LauncherParameter] = field(default_factory=list)

    # Execution settings
    use_shell: bool = False
    capture_output: bool = False
    timeout_seconds: Optional[int] = None

    # UI settings
    sort_order: int = 0
    keyboard_shortcut: str = ""

    def __post_init__(self):
        """Validate launcher configuration."""
        if not self.id:
            raise ValueError("Launcher ID cannot be empty")

        if not self.id.isidentifier():
            raise ValueError(
                f"Launcher ID '{self.id}' must be a valid Python identifier"
            )

        if not self.name:
            raise ValueError("Launcher name cannot be empty")

        if not self.command:
            raise ValueError("Launcher command cannot be empty")

        # Validate parameter names are unique
        param_names = [p.name for p in self.parameters]
        if len(param_names) != len(set(param_names)):
            raise ValueError("Parameter names must be unique")

        # Validate timeout
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("Timeout must be positive")

    def validate_parameters(self, param_values: Dict[str, Any]) -> Dict[str, str]:
        """Validate parameter values against parameter definitions.

        Args:
            param_values: Dictionary of parameter values

        Returns:
            Dictionary of validation errors (empty if all valid)
        """
        errors = {}

        # Check all required parameters are provided
        for param in self.parameters:
            if param.required and param.name not in param_values:
                errors[param.name] = "Required parameter missing"
                continue

            # Validate value if provided
            if param.name in param_values:
                if not param.validate_value(param_values[param.name]):
                    errors[param.name] = (
                        f"Invalid value for {param.param_type.value} parameter"
                    )

        return errors

    def build_command(self, param_values: Dict[str, Any] = None) -> List[str]:
        """Build command line arguments from template and parameters.

        Args:
            param_values: Dictionary of parameter values

        Returns:
            List of command arguments

        Raises:
            ValueError: If parameter validation fails
        """
        param_values = param_values or {}

        # Validate parameters
        errors = self.validate_parameters(param_values)
        if errors:
            raise ValueError(f"Parameter validation failed: {errors}")

        # Fill in default values for missing optional parameters
        final_values = {}
        for param in self.parameters:
            if param.name in param_values:
                final_values[param.name] = param_values[param.name]
            elif param.default_value is not None:
                final_values[param.name] = param.default_value
            else:
                final_values[param.name] = ""

        # Build command by substituting parameters
        try:
            command_str = self.command.format(**final_values)

            # Split command into arguments, handling quoted strings
            import shlex

            return shlex.split(command_str)

        except KeyError as e:
            raise ValueError(f"Command template references undefined parameter: {e}")
        except Exception as e:
            raise ValueError(f"Error building command: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert launcher to dictionary for serialization."""
        data = asdict(self)
        # Convert parameters to dictionaries
        data["parameters"] = [param.to_dict() for param in self.parameters]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Launcher":
        """Create launcher from dictionary.

        Args:
            data: Dictionary containing launcher data

        Returns:
            Launcher instance

        Raises:
            ValueError: If data is invalid
        """
        try:
            # Convert parameters from dictionaries
            if "parameters" in data:
                data["parameters"] = [
                    LauncherParameter.from_dict(param_data)
                    for param_data in data["parameters"]
                ]

            return cls(**data)

        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid launcher data: {e}")

    def clone(self, new_id: str = None, new_name: str = None) -> "Launcher":
        """Create a copy of this launcher with optional new ID/name.

        Args:
            new_id: New ID for the cloned launcher
            new_name: New name for the cloned launcher

        Returns:
            Cloned launcher instance
        """
        data = self.to_dict()

        if new_id:
            data["id"] = new_id

        if new_name:
            data["name"] = new_name

        return self.from_dict(data)


def validate_launcher_schema(data: Dict[str, Any]) -> List[str]:
    """Validate launcher data against expected schema.

    Args:
        data: Dictionary to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Required fields
    required_fields = ["id", "name", "command"]
    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(data[field], str):
            errors.append(f"Field '{field}' must be a string")
        elif not data[field].strip():
            errors.append(f"Field '{field}' cannot be empty")

    # Optional fields with type validation
    optional_fields = {
        "description": str,
        "icon_path": str,
        "category": str,
        "enabled": bool,
        "show_in_context_menu": bool,
        "working_directory": str,
        "environment_vars": dict,
        "use_shell": bool,
        "capture_output": bool,
        "timeout_seconds": (int, type(None)),
        "sort_order": int,
        "keyboard_shortcut": str,
    }

    for field, expected_type in optional_fields.items():
        if field in data:
            if not isinstance(data[field], expected_type):
                errors.append(f"Field '{field}' must be of type {expected_type}")

    # Validate parameters list
    if "parameters" in data:
        if not isinstance(data["parameters"], list):
            errors.append("Field 'parameters' must be a list")
        else:
            for i, param_data in enumerate(data["parameters"]):
                if not isinstance(param_data, dict):
                    errors.append(f"Parameter {i} must be a dictionary")
                    continue

                # Validate parameter fields
                param_required = ["name", "param_type", "label"]
                for field in param_required:
                    if field not in param_data:
                        errors.append(f"Parameter {i} missing required field: {field}")

    return errors
