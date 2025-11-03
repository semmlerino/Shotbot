"""Comprehensive unit tests for launcher/models.py.

Testing data models, validation, and serialization for the launcher system.
Following UNIFIED_TESTING_GUIDE best practices:
- Test behavior, not implementation
- Cover all dataclass fields and validation rules
- Test serialization/deserialization round-trips
- Test edge cases and error conditions
- Minimal mocking (models are pure data structures)
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from launcher.models import (
    CustomLauncher,
    LauncherEnvironment,
    LauncherParameter,
    LauncherTerminal,
    LauncherValidation,
    ParameterType,
    ProcessInfo,
    ProcessInfoDict,
)


if TYPE_CHECKING:
    from unittest.mock import Mock

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ============================================================================
# Test ParameterType Enum
# ============================================================================


class TestParameterType:
    """Test ParameterType enum."""

    def test_all_parameter_types_exist(self) -> None:
        """Test that all expected parameter types are defined."""
        assert ParameterType.STRING.value == "string"
        assert ParameterType.INTEGER.value == "integer"
        assert ParameterType.FLOAT.value == "float"
        assert ParameterType.BOOLEAN.value == "boolean"
        assert ParameterType.PATH.value == "path"
        assert ParameterType.CHOICE.value == "choice"
        assert ParameterType.FILE.value == "file"
        assert ParameterType.DIRECTORY.value == "directory"

    def test_enum_from_value(self) -> None:
        """Test creating enum from string value."""
        assert ParameterType("string") == ParameterType.STRING
        assert ParameterType("integer") == ParameterType.INTEGER
        assert ParameterType("choice") == ParameterType.CHOICE

    def test_enum_invalid_value_raises_error(self) -> None:
        """Test that invalid enum value raises ValueError."""
        with pytest.raises(ValueError):
            ParameterType("invalid_type")


# ============================================================================
# Test LauncherParameter - Initialization and Validation
# ============================================================================


class TestLauncherParameterInitialization:
    """Test LauncherParameter dataclass initialization and validation."""

    def test_minimal_valid_parameter(self) -> None:
        """Test creating parameter with minimal required fields."""
        param = LauncherParameter(
            name="test_param",
            param_type=ParameterType.STRING,
            label="Test Parameter",
        )
        assert param.name == "test_param"
        assert param.param_type == ParameterType.STRING
        assert param.label == "Test Parameter"
        assert param.description == ""
        assert param.default_value is None
        assert param.required is False
        assert param.choices == []
        assert param.min_value is None
        assert param.max_value is None
        assert param.file_filter == ""
        assert param.placeholder == ""

    def test_full_parameter_with_all_fields(self) -> None:
        """Test creating parameter with all fields populated."""
        param = LauncherParameter(
            name="frame_range",
            param_type=ParameterType.INTEGER,
            label="Frame Range",
            description="Render frame range",
            default_value=100,
            required=True,
            choices=[],
            min_value=1,
            max_value=1000,
            file_filter="*.exr",
            placeholder="Enter frame number",
        )
        assert param.name == "frame_range"
        assert param.description == "Render frame range"
        assert param.default_value == 100
        assert param.required is True
        assert param.min_value == 1
        assert param.max_value == 1000
        assert param.file_filter == "*.exr"
        assert param.placeholder == "Enter frame number"

    def test_empty_name_raises_error(self) -> None:
        """Test that empty parameter name raises ValueError."""
        with pytest.raises(ValueError, match="Parameter name cannot be empty"):
            LauncherParameter(
                name="",
                param_type=ParameterType.STRING,
                label="Test",
            )

    def test_invalid_identifier_name_raises_error(self) -> None:
        """Test that invalid Python identifier name raises ValueError."""
        with pytest.raises(ValueError, match="must be a valid Python identifier"):
            LauncherParameter(
                name="invalid-name",  # Hyphen not allowed
                param_type=ParameterType.STRING,
                label="Test",
            )

    def test_empty_label_raises_error(self) -> None:
        """Test that empty label raises ValueError."""
        with pytest.raises(ValueError, match="Parameter label cannot be empty"):
            LauncherParameter(
                name="test",
                param_type=ParameterType.STRING,
                label="",
            )

    def test_choice_type_requires_choices(self) -> None:
        """Test that CHOICE parameter type requires at least one choice."""
        with pytest.raises(ValueError, match="CHOICE parameter must have at least one choice"):
            LauncherParameter(
                name="quality",
                param_type=ParameterType.CHOICE,
                label="Quality",
                choices=[],  # Empty choices list
            )

    def test_choice_default_must_be_in_choices(self) -> None:
        """Test that default value for CHOICE must be in choices list."""
        with pytest.raises(ValueError, match=r"Default value .* not in choices"):
            LauncherParameter(
                name="quality",
                param_type=ParameterType.CHOICE,
                label="Quality",
                choices=["low", "medium", "high"],
                default_value="ultra",  # Not in choices
            )

    def test_min_greater_than_max_raises_error(self) -> None:
        """Test that min_value > max_value raises ValueError."""
        with pytest.raises(ValueError, match="min_value cannot be greater than max_value"):
            LauncherParameter(
                name="count",
                param_type=ParameterType.INTEGER,
                label="Count",
                min_value=100,
                max_value=50,  # Invalid range
            )

    def test_default_below_minimum_raises_error(self) -> None:
        """Test that default value below minimum raises ValueError."""
        with pytest.raises(ValueError, match="Default value is below minimum"):
            LauncherParameter(
                name="count",
                param_type=ParameterType.INTEGER,
                label="Count",
                min_value=10,
                max_value=100,
                default_value=5,  # Below minimum
            )

    def test_default_above_maximum_raises_error(self) -> None:
        """Test that default value above maximum raises ValueError."""
        with pytest.raises(ValueError, match="Default value is above maximum"):
            LauncherParameter(
                name="count",
                param_type=ParameterType.INTEGER,
                label="Count",
                min_value=10,
                max_value=100,
                default_value=150,  # Above maximum
            )


# ============================================================================
# Test LauncherParameter - Value Validation
# ============================================================================


class TestLauncherParameterValidation:
    """Test LauncherParameter.validate_value() method."""

    def test_validate_none_with_required_false(self) -> None:
        """Test that None is valid for non-required parameters."""
        param = LauncherParameter(
            name="optional",
            param_type=ParameterType.STRING,
            label="Optional",
            required=False,
        )
        assert param.validate_value(None) is True

    def test_validate_none_with_required_true(self) -> None:
        """Test that None is invalid for required parameters."""
        param = LauncherParameter(
            name="required",
            param_type=ParameterType.STRING,
            label="Required",
            required=True,
        )
        assert param.validate_value(None) is False

    def test_validate_string_type(self) -> None:
        """Test STRING parameter type validation."""
        param = LauncherParameter(
            name="name",
            param_type=ParameterType.STRING,
            label="Name",
        )
        assert param.validate_value("valid_string") is True
        assert param.validate_value(123) is False
        assert param.validate_value(True) is False

    def test_validate_integer_type(self) -> None:
        """Test INTEGER parameter type validation."""
        param = LauncherParameter(
            name="count",
            param_type=ParameterType.INTEGER,
            label="Count",
        )
        assert param.validate_value(42) is True
        assert param.validate_value("42") is False
        assert param.validate_value(3.14) is False

    def test_validate_integer_with_min_max(self) -> None:
        """Test INTEGER parameter validation with min/max bounds."""
        param = LauncherParameter(
            name="count",
            param_type=ParameterType.INTEGER,
            label="Count",
            min_value=10,
            max_value=100,
        )
        assert param.validate_value(50) is True
        assert param.validate_value(10) is True  # Boundary
        assert param.validate_value(100) is True  # Boundary
        assert param.validate_value(5) is False  # Below min
        assert param.validate_value(150) is False  # Above max

    def test_validate_float_type(self) -> None:
        """Test FLOAT parameter type validation."""
        param = LauncherParameter(
            name="scale",
            param_type=ParameterType.FLOAT,
            label="Scale",
        )
        assert param.validate_value(3.14) is True
        assert param.validate_value(42) is True  # Integer accepted
        assert param.validate_value("3.14") is False

    def test_validate_float_with_min_max(self) -> None:
        """Test FLOAT parameter validation with min/max bounds."""
        param = LauncherParameter(
            name="scale",
            param_type=ParameterType.FLOAT,
            label="Scale",
            min_value=0.0,
            max_value=1.0,
        )
        assert param.validate_value(0.5) is True
        assert param.validate_value(0.0) is True  # Boundary
        assert param.validate_value(1.0) is True  # Boundary
        assert param.validate_value(-0.1) is False  # Below min
        assert param.validate_value(1.5) is False  # Above max

    def test_validate_boolean_type(self) -> None:
        """Test BOOLEAN parameter type validation."""
        param = LauncherParameter(
            name="enabled",
            param_type=ParameterType.BOOLEAN,
            label="Enabled",
        )
        assert param.validate_value(True) is True
        assert param.validate_value(False) is True
        assert param.validate_value(1) is False
        assert param.validate_value("true") is False

    def test_validate_path_type(self) -> None:
        """Test PATH parameter type validation."""
        param = LauncherParameter(
            name="output_path",
            param_type=ParameterType.PATH,
            label="Output Path",
        )
        assert param.validate_value("/path/to/file") is True
        assert param.validate_value("relative/path") is True
        assert param.validate_value(123) is False

    def test_validate_choice_type(self) -> None:
        """Test CHOICE parameter type validation."""
        param = LauncherParameter(
            name="quality",
            param_type=ParameterType.CHOICE,
            label="Quality",
            choices=["low", "medium", "high"],
        )
        assert param.validate_value("low") is True
        assert param.validate_value("medium") is True
        assert param.validate_value("high") is True
        assert param.validate_value("ultra") is False

    def test_validate_file_type(self) -> None:
        """Test FILE parameter type validation."""
        param = LauncherParameter(
            name="input_file",
            param_type=ParameterType.FILE,
            label="Input File",
        )
        assert param.validate_value("/path/to/file.txt") is True
        assert param.validate_value(123) is False

    def test_validate_directory_type(self) -> None:
        """Test DIRECTORY parameter type validation."""
        param = LauncherParameter(
            name="output_dir",
            param_type=ParameterType.DIRECTORY,
            label="Output Directory",
        )
        assert param.validate_value("/path/to/directory") is True
        assert param.validate_value(123) is False

    def test_validate_with_exception_handling(self) -> None:
        """Test that validate_value handles exceptions gracefully."""

        # Create a parameter
        param = LauncherParameter(
            name="test",
            param_type=ParameterType.STRING,
            label="Test",
        )

        # Create a mock object that raises exception when used in isinstance()
        class BadValue:
            def __class__(self):
                raise RuntimeError("Simulated error")

        bad_value = BadValue()

        # Should return False instead of raising exception
        # Note: This is hard to trigger in practice, but the code handles it
        # The exception handler is defensive programming
        assert param.validate_value(bad_value) is False


# ============================================================================
# Test LauncherParameter - Serialization
# ============================================================================


class TestLauncherParameterSerialization:
    """Test LauncherParameter serialization and deserialization."""

    def test_to_dict_basic(self) -> None:
        """Test converting parameter to dictionary."""
        param = LauncherParameter(
            name="test",
            param_type=ParameterType.STRING,
            label="Test Parameter",
            description="Test description",
        )
        data = param.to_dict()

        assert data["name"] == "test"
        assert data["param_type"] == "string"  # Enum converted to string
        assert data["label"] == "Test Parameter"
        assert data["description"] == "Test description"
        assert data["default_value"] is None

    def test_to_dict_with_all_fields(self) -> None:
        """Test to_dict with all fields populated."""
        param = LauncherParameter(
            name="count",
            param_type=ParameterType.INTEGER,
            label="Count",
            description="Item count",
            default_value=42,
            required=True,
            choices=[],
            min_value=1,
            max_value=100,
            file_filter="*.txt",
            placeholder="Enter count",
        )
        data = param.to_dict()

        assert data["name"] == "count"
        assert data["param_type"] == "integer"
        assert data["default_value"] == 42
        assert data["required"] is True
        assert data["min_value"] == 1
        assert data["max_value"] == 100
        assert data["file_filter"] == "*.txt"
        assert data["placeholder"] == "Enter count"

    def test_from_dict_basic(self) -> None:
        """Test creating parameter from dictionary."""
        data = {
            "name": "test",
            "param_type": "string",
            "label": "Test Parameter",
            "description": "Test description",
        }
        param = LauncherParameter.from_dict(data)

        assert param.name == "test"
        assert param.param_type == ParameterType.STRING
        assert param.label == "Test Parameter"
        assert param.description == "Test description"

    def test_from_dict_with_all_fields(self) -> None:
        """Test from_dict with all fields populated."""
        data = {
            "name": "quality",
            "param_type": "choice",
            "label": "Quality",
            "description": "Render quality",
            "default_value": "medium",
            "required": True,
            "choices": ["low", "medium", "high"],
            "min_value": None,
            "max_value": None,
            "file_filter": "",
            "placeholder": "Select quality",
        }
        param = LauncherParameter.from_dict(data)

        assert param.name == "quality"
        assert param.param_type == ParameterType.CHOICE
        assert param.default_value == "medium"
        assert param.required is True
        assert param.choices == ["low", "medium", "high"]

    def test_roundtrip_serialization(self) -> None:
        """Test that to_dict -> from_dict preserves all data."""
        original = LauncherParameter(
            name="scale",
            param_type=ParameterType.FLOAT,
            label="Scale Factor",
            description="Scaling factor for output",
            default_value=1.5,
            required=False,
            min_value=0.1,
            max_value=10.0,
            placeholder="1.0",
        )

        # Round-trip
        data = original.to_dict()
        restored = LauncherParameter.from_dict(data)

        assert restored.name == original.name
        assert restored.param_type == original.param_type
        assert restored.label == original.label
        assert restored.description == original.description
        assert restored.default_value == original.default_value
        assert restored.required == original.required
        assert restored.min_value == original.min_value
        assert restored.max_value == original.max_value
        assert restored.placeholder == original.placeholder

    def test_from_dict_invalid_data_raises_error(self) -> None:
        """Test that invalid dictionary data raises ValueError."""
        data = {
            "name": "test",
            # Missing required fields
        }
        with pytest.raises(ValueError, match="Invalid parameter data"):
            LauncherParameter.from_dict(data)

    def test_from_dict_invalid_enum_raises_error(self) -> None:
        """Test that invalid param_type string raises ValueError."""
        data = {
            "name": "test",
            "param_type": "invalid_type",
            "label": "Test",
        }
        with pytest.raises(ValueError, match="Invalid parameter data"):
            LauncherParameter.from_dict(data)


# ============================================================================
# Test LauncherValidation
# ============================================================================


class TestLauncherValidation:
    """Test LauncherValidation dataclass."""

    def test_default_initialization(self) -> None:
        """Test LauncherValidation with default values."""
        validation = LauncherValidation()

        assert validation.check_executable is True
        assert validation.required_files == []
        assert len(validation.forbidden_patterns) > 0  # Has default patterns
        assert validation.working_directory is None
        assert validation.resolve_paths is False

    def test_default_forbidden_patterns(self) -> None:
        """Test that default forbidden patterns are present."""
        validation = LauncherValidation()

        # Should have dangerous command patterns
        assert any("rm" in pattern for pattern in validation.forbidden_patterns)
        assert any("sudo" in pattern for pattern in validation.forbidden_patterns)

    def test_custom_initialization(self) -> None:
        """Test LauncherValidation with custom values."""
        validation = LauncherValidation(
            check_executable=False,
            required_files=["config.json", "license.txt"],
            forbidden_patterns=[r"rm -rf", r"sudo"],
            working_directory="/tmp/workspace",
            resolve_paths=True,
        )

        assert validation.check_executable is False
        assert validation.required_files == ["config.json", "license.txt"]
        assert validation.forbidden_patterns == [r"rm -rf", r"sudo"]
        assert validation.working_directory == "/tmp/workspace"
        assert validation.resolve_paths is True


# ============================================================================
# Test LauncherTerminal
# ============================================================================


class TestLauncherTerminal:
    """Test LauncherTerminal dataclass."""

    def test_default_initialization(self) -> None:
        """Test LauncherTerminal with default values."""
        terminal = LauncherTerminal()

        assert terminal.required is False
        assert terminal.persist is False
        assert terminal.title is None

    def test_custom_initialization(self) -> None:
        """Test LauncherTerminal with custom values."""
        terminal = LauncherTerminal(
            required=True,
            persist=True,
            title="Custom Terminal",
        )

        assert terminal.required is True
        assert terminal.persist is True
        assert terminal.title == "Custom Terminal"


# ============================================================================
# Test LauncherEnvironment
# ============================================================================


class TestLauncherEnvironment:
    """Test LauncherEnvironment dataclass."""

    def test_default_initialization(self) -> None:
        """Test LauncherEnvironment with default values."""
        env = LauncherEnvironment()

        assert env.type == "bash"
        assert env.packages == []
        assert env.source_files == []
        assert env.command_prefix is None

    def test_custom_initialization(self) -> None:
        """Test LauncherEnvironment with custom values."""
        env = LauncherEnvironment(
            type="rez",
            packages=["maya", "nuke"],
            source_files=["/etc/profile", "~/.bashrc"],
            command_prefix="rez-env",
        )

        assert env.type == "rez"
        assert env.packages == ["maya", "nuke"]
        assert env.source_files == ["/etc/profile", "~/.bashrc"]
        assert env.command_prefix == "rez-env"


# ============================================================================
# Test CustomLauncher - Initialization
# ============================================================================


class TestCustomLauncherInitialization:
    """Test CustomLauncher dataclass initialization."""

    def test_minimal_initialization(self) -> None:
        """Test CustomLauncher with minimal required fields."""
        launcher = CustomLauncher(
            id="test_001",
            name="Test Launcher",
            description="Test description",
            command="echo test",
        )

        assert launcher.id == "test_001"
        assert launcher.name == "Test Launcher"
        assert launcher.description == "Test description"
        assert launcher.command == "echo test"
        assert launcher.category == "custom"
        assert launcher.variables == {}
        assert isinstance(launcher.environment, LauncherEnvironment)
        assert isinstance(launcher.terminal, LauncherTerminal)
        assert isinstance(launcher.validation, LauncherValidation)
        assert launcher.created_at is not None
        assert launcher.updated_at is not None

    def test_full_initialization(self) -> None:
        """Test CustomLauncher with all fields populated."""
        env = LauncherEnvironment(type="rez", packages=["maya"])
        term = LauncherTerminal(required=True, title="Maya")
        val = LauncherValidation(check_executable=False)

        launcher = CustomLauncher(
            id="maya_001",
            name="Maya 2024",
            description="Maya launcher",
            command="maya -proj $project",
            category="dcc",
            variables={"project": "/mnt/projects/default"},
            environment=env,
            terminal=term,
            validation=val,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-02T00:00:00",
        )

        assert launcher.id == "maya_001"
        assert launcher.category == "dcc"
        assert launcher.variables == {"project": "/mnt/projects/default"}
        assert launcher.environment.type == "rez"
        assert launcher.terminal.required is True
        assert launcher.validation.check_executable is False

    def test_timestamps_are_iso_format(self) -> None:
        """Test that created_at and updated_at are valid ISO format."""
        launcher = CustomLauncher(
            id="test_001",
            name="Test",
            description="Test",
            command="test",
        )

        # Should be parseable as ISO datetime
        datetime.fromisoformat(launcher.created_at)
        datetime.fromisoformat(launcher.updated_at)


# ============================================================================
# Test CustomLauncher - Serialization
# ============================================================================


class TestCustomLauncherSerialization:
    """Test CustomLauncher serialization and deserialization."""

    def test_to_dict_basic(self) -> None:
        """Test converting launcher to dictionary."""
        launcher = CustomLauncher(
            id="test_001",
            name="Test Launcher",
            description="Test description",
            command="echo test",
        )
        data = launcher.to_dict()

        assert data["id"] == "test_001"
        assert data["name"] == "Test Launcher"
        assert data["description"] == "Test description"
        assert data["command"] == "echo test"
        assert data["category"] == "custom"
        assert data["variables"] == {}

    def test_to_dict_with_nested_objects(self) -> None:
        """Test to_dict includes nested dataclass objects."""
        env = LauncherEnvironment(type="rez", packages=["maya"])
        launcher = CustomLauncher(
            id="test_001",
            name="Test",
            description="Test",
            command="test",
            environment=env,
        )
        data = launcher.to_dict()

        assert isinstance(data["environment"], dict)
        assert data["environment"]["type"] == "rez"
        assert data["environment"]["packages"] == ["maya"]

    def test_from_dict_basic(self) -> None:
        """Test creating launcher from dictionary."""
        data = {
            "id": "test_001",
            "name": "Test Launcher",
            "description": "Test description",
            "command": "echo test",
            "category": "custom",
            "variables": {},
            "environment": {"type": "bash", "packages": [], "source_files": [], "command_prefix": None},
            "terminal": {"required": False, "persist": False, "title": None},
            "validation": {
                "check_executable": True,
                "required_files": [],
                "forbidden_patterns": [],
                "working_directory": None,
                "resolve_paths": False,
            },
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        launcher = CustomLauncher.from_dict(data)

        assert launcher.id == "test_001"
        assert launcher.name == "Test Launcher"
        assert launcher.description == "Test description"
        assert launcher.command == "echo test"

    def test_from_dict_reconstructs_nested_objects(self) -> None:
        """Test from_dict properly reconstructs nested dataclass objects."""
        data = {
            "id": "test_001",
            "name": "Test",
            "description": "Test",
            "command": "test",
            "category": "custom",
            "variables": {},
            "environment": {
                "type": "rez",
                "packages": ["maya", "nuke"],
                "source_files": ["/etc/profile"],
                "command_prefix": "rez-env",
            },
            "terminal": {
                "required": True,
                "persist": True,
                "title": "Custom Terminal",
            },
            "validation": {
                "check_executable": False,
                "required_files": ["config.json"],
                "forbidden_patterns": [r"rm"],
                "working_directory": "/tmp",
                "resolve_paths": True,
            },
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        launcher = CustomLauncher.from_dict(data)

        # Check environment
        assert isinstance(launcher.environment, LauncherEnvironment)
        assert launcher.environment.type == "rez"
        assert launcher.environment.packages == ["maya", "nuke"]
        assert launcher.environment.source_files == ["/etc/profile"]
        assert launcher.environment.command_prefix == "rez-env"

        # Check terminal
        assert isinstance(launcher.terminal, LauncherTerminal)
        assert launcher.terminal.required is True
        assert launcher.terminal.persist is True
        assert launcher.terminal.title == "Custom Terminal"

        # Check validation
        assert isinstance(launcher.validation, LauncherValidation)
        assert launcher.validation.check_executable is False
        assert launcher.validation.required_files == ["config.json"]
        assert launcher.validation.forbidden_patterns == [r"rm"]
        assert launcher.validation.working_directory == "/tmp"
        assert launcher.validation.resolve_paths is True

    def test_roundtrip_serialization(self) -> None:
        """Test that to_dict -> from_dict preserves all data."""
        original = CustomLauncher(
            id="maya_001",
            name="Maya 2024",
            description="Maya launcher for VFX",
            command="maya -proj $project",
            category="dcc",
            variables={"project": "/mnt/projects/default"},
            environment=LauncherEnvironment(type="rez", packages=["maya-2024"]),
            terminal=LauncherTerminal(required=True, persist=False, title="Maya"),
            validation=LauncherValidation(
                check_executable=True,
                required_files=["license.lic"],
                resolve_paths=True,
            ),
        )

        # Round-trip
        data = original.to_dict()
        restored = CustomLauncher.from_dict(data)

        # Check main fields
        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.command == original.command
        assert restored.category == original.category
        assert restored.variables == original.variables

        # Check nested objects
        assert restored.environment.type == original.environment.type
        assert restored.environment.packages == original.environment.packages
        assert restored.terminal.required == original.terminal.required
        assert restored.terminal.title == original.terminal.title
        assert restored.validation.check_executable == original.validation.check_executable
        assert restored.validation.required_files == original.validation.required_files

    def test_from_dict_handles_missing_nested_fields(self) -> None:
        """Test from_dict handles partial nested object data gracefully."""
        data = {
            "id": "test_001",
            "name": "Test",
            "description": "Test",
            "command": "test",
            "category": "custom",
            "variables": {},
            "environment": {"type": "bash"},  # Minimal environment
            "terminal": {},  # Empty terminal (should use defaults)
            "validation": {},  # Empty validation (should use defaults)
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        launcher = CustomLauncher.from_dict(data)

        # Should use defaults for missing fields
        assert launcher.environment.type == "bash"
        assert launcher.environment.packages == []
        assert launcher.terminal.required is False
        assert launcher.validation.check_executable is True

    def test_from_dict_with_none_command_prefix(self) -> None:
        """Test from_dict handles None command_prefix correctly."""
        data = {
            "id": "test_001",
            "name": "Test",
            "description": "Test",
            "command": "test",
            "category": "custom",
            "variables": {},
            "environment": {
                "type": "bash",
                "packages": ["pkg1"],
                "source_files": ["file1"],
                "command_prefix": None,  # Explicitly None
            },
            "terminal": {"required": False, "persist": False, "title": None},
            "validation": {
                "check_executable": True,
                "required_files": [],
                "forbidden_patterns": [],
                "working_directory": None,
                "resolve_paths": False,
            },
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        launcher = CustomLauncher.from_dict(data)

        assert launcher.environment.command_prefix is None
        assert launcher.terminal.title is None
        assert launcher.validation.working_directory is None

    def test_from_dict_with_non_list_packages(self) -> None:
        """Test from_dict handles non-list packages gracefully."""
        data = {
            "id": "test_001",
            "name": "Test",
            "description": "Test",
            "command": "test",
            "category": "custom",
            "variables": {},
            "environment": {
                "type": "bash",
                "packages": "not_a_list",  # Invalid type (should be handled)
                "source_files": None,  # Also invalid
            },
            "terminal": {},
            "validation": {},
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        launcher = CustomLauncher.from_dict(data)

        # Should handle invalid types gracefully
        assert launcher.environment.packages == []
        assert launcher.environment.source_files == []


# ============================================================================
# Test ProcessInfo
# ============================================================================


class TestProcessInfo:
    """Test ProcessInfo class."""

    @pytest.fixture
    def mock_process(self) -> Mock:
        """Create a mock subprocess.Popen object."""
        from unittest.mock import Mock

        process = Mock()
        process.pid = 12345
        process.poll.return_value = None  # Running
        process.returncode = None
        return process

    def test_initialization(self, mock_process: Mock) -> None:
        """Test ProcessInfo initialization."""
        info = ProcessInfo(
            process=mock_process,
            launcher_id="maya_001",
            launcher_name="Maya 2024",
            command="maya -proj /mnt/project",
            timestamp=1234567890.0,
        )

        assert info.process == mock_process
        assert info.launcher_id == "maya_001"
        assert info.launcher_name == "Maya 2024"
        assert info.command == "maya -proj /mnt/project"
        assert info.timestamp == 1234567890.0
        assert info.validated is False  # Default

    def test_validated_flag_defaults_to_false(self, mock_process: Mock) -> None:
        """Test that validated flag defaults to False."""
        info = ProcessInfo(
            process=mock_process,
            launcher_id="test",
            launcher_name="Test",
            command="test",
            timestamp=0.0,
        )
        assert info.validated is False

    def test_can_set_validated_flag(self, mock_process: Mock) -> None:
        """Test that validated flag can be set after initialization."""
        info = ProcessInfo(
            process=mock_process,
            launcher_id="test",
            launcher_name="Test",
            command="test",
            timestamp=0.0,
        )
        info.validated = True
        assert info.validated is True


# ============================================================================
# Test ProcessInfoDict TypedDict
# ============================================================================


class TestProcessInfoDict:
    """Test ProcessInfoDict TypedDict."""

    def test_typed_dict_structure(self) -> None:
        """Test that ProcessInfoDict has correct structure."""
        # This is a static type check, but we can verify the structure
        # by creating a valid dict that matches the TypedDict
        valid_dict: ProcessInfoDict = {
            "type": "maya",
            "key": "maya_20240101_120000_abc123",
            "launcher_id": "maya_001",
            "launcher_name": "Maya 2024",
            "command": "maya -proj /mnt/project",
            "pid": 12345,
            "running": True,
            "start_time": 1234567890.0,
        }

        # Verify all fields present
        assert valid_dict["type"] == "maya"
        assert valid_dict["key"] == "maya_20240101_120000_abc123"
        assert valid_dict["launcher_id"] == "maya_001"
        assert valid_dict["launcher_name"] == "Maya 2024"
        assert valid_dict["command"] == "maya -proj /mnt/project"
        assert valid_dict["pid"] == 12345
        assert valid_dict["running"] is True
        assert valid_dict["start_time"] == 1234567890.0
