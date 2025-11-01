# ShotBot Custom Launcher Documentation

## Table of Contents

1. [Overview](#overview)
2. [Configuration File Format](#configuration-file-format)
3. [JSON Schema](#json-schema)
4. [API Documentation](#api-documentation)
5. [User Guide](#user-guide)
6. [Developer Documentation](#developer-documentation)
7. [FAQ and Troubleshooting](#faq-and-troubleshooting)
8. [Best Practices](#best-practices)

---

## Overview

The ShotBot Custom Launcher feature allows users to define and execute custom application commands within shot contexts. This system extends beyond the built-in applications (3DE, Nuke, Maya, RV, Publish) to support any application or script that can be executed in a VFX pipeline environment.

### Key Features

- **Custom Application Support**: Define any executable, script, or command
- **Variable Substitution**: Dynamic path and context substitution
- **Terminal Integration**: Support for multiple terminal emulators
- **Environment Management**: Rez environment integration
- **Shot Context**: Automatic workspace setup with `ws` command
- **Platform Support**: Linux-focused with extensible terminal support
- **Validation**: Built-in command validation and error handling

### Use Cases

- Launch custom tools with shot-specific configurations
- Execute pipeline scripts in proper environments
- Open applications with pre-loaded shot data
- Run custom processing commands
- Launch debugging or diagnostic tools

---

## Configuration File Format

### File Location

The custom launcher configuration is stored in a JSON file at:

**Linux/Unix:**
```
$HOME/.shotbot/custom_launchers.json
```

**Alternative Locations (searched in order):**
1. `$SHOTBOT_CONFIG_DIR/custom_launchers.json`
2. `$HOME/.config/shotbot/custom_launchers.json`
3. `$HOME/.shotbot/custom_launchers.json` (default)

### Basic Structure

```json
{
  "version": "1.0",
  "launchers": {
    "my_custom_app": {
      "name": "My Custom Application",
      "description": "Custom VFX tool for shot processing",
      "command": "my_vfx_tool",
      "category": "custom",
      "environment": {
        "type": "rez",
        "packages": ["PySide6_Essentials", "my_tool_package"]
      },
      "terminal": {
        "required": true,
        "persist": false
      },
      "variables": {
        "shot_path": "{workspace_path}",
        "shot_name": "{full_name}"
      },
      "validation": {
        "check_executable": true,
        "required_files": []
      }
    }
  },
  "terminal_preferences": [
    "gnome-terminal",
    "konsole",
    "xterm"
  ],
  "default_environment": {
    "type": "bash",
    "source_files": [
      "$HOME/.bashrc"
    ]
  }
}
```

### Configuration Examples

#### Simple Executable
```json
{
  "version": "1.0",
  "launchers": {
    "blender": {
      "name": "Blender",
      "description": "3D modeling and animation software",
      "command": "blender",
      "category": "modeling",
      "terminal": {
        "required": false
      }
    }
  }
}
```

#### Rez Environment with Complex Command
```json
{
  "version": "1.0",
  "launchers": {
    "shotbot_debug": {
      "name": "ShotBot Debug Mode",
      "description": "Launch ShotBot with debug logging",
      "command": "python3 '{shotbot_path}' --debug --shot={full_name}",
      "category": "debug",
      "environment": {
        "type": "rez",
        "packages": ["PySide6_Essentials", "pillow", "Jinja2"],
        "command_prefix": "rez env {packages} --"
      },
      "terminal": {
        "required": true,
        "persist": true,
        "title": "ShotBot Debug - {shot_name}"
      },
      "variables": {
        "shotbot_path": "/nethome/gabriel-h/output/ShotBotv5/copy/shotbot.py",
        "shot_name": "{show}_{sequence}_{shot}"
      },
      "validation": {
        "check_executable": false,
        "required_files": ["{shotbot_path}"]
      }
    }
  }
}
```

#### Script with Arguments
```json
{
  "version": "1.0",
  "launchers": {
    "render_submit": {
      "name": "Submit Render",
      "description": "Submit shot for farm rendering",
      "command": "/studio/tools/render_submit.py --shot={workspace_path} --frames={frame_range}",
      "category": "rendering",
      "environment": {
        "type": "bash",
        "variables": {
          "SHOT_ROOT": "{workspace_path}",
          "CURRENT_SHOT": "{full_name}"
        }
      },
      "terminal": {
        "required": true,
        "persist": true
      },
      "variables": {
        "frame_range": "1001-1100"
      },
      "pre_execution": [
        "echo 'Submitting render for {full_name}'",
        "cd {workspace_path}"
      ],
      "post_execution": [
        "echo 'Render submitted successfully'",
        "read -p 'Press Enter to close...'"
      ]
    }
  }
}
```

---

## JSON Schema

### Complete Schema Definition

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ShotBot Custom Launcher Configuration",
  "description": "Configuration schema for ShotBot custom application launchers",
  "type": "object",
  "required": ["version", "launchers"],
  "properties": {
    "version": {
      "type": "string",
      "description": "Configuration format version",
      "enum": ["1.0"]
    },
    "launchers": {
      "type": "object",
      "description": "Dictionary of custom launcher definitions",
      "patternProperties": {
        "^[a-zA-Z][a-zA-Z0-9_-]*$": {
          "$ref": "#/definitions/launcher"
        }
      },
      "additionalProperties": false
    },
    "terminal_preferences": {
      "type": "array",
      "description": "Ordered list of preferred terminal emulators",
      "items": {
        "type": "string",
        "enum": ["gnome-terminal", "konsole", "xterm", "alacritty", "terminator"]
      },
      "default": ["gnome-terminal", "konsole", "xterm"]
    },
    "default_environment": {
      "$ref": "#/definitions/environment",
      "description": "Default environment settings for all launchers"
    }
  },
  "definitions": {
    "launcher": {
      "type": "object",
      "required": ["name", "command"],
      "properties": {
        "name": {
          "type": "string",
          "description": "Display name for the launcher",
          "minLength": 1,
          "maxLength": 100
        },
        "description": {
          "type": "string",
          "description": "Description of what the launcher does",
          "maxLength": 500
        },
        "command": {
          "type": "string",
          "description": "Command to execute (supports variable substitution)",
          "minLength": 1
        },
        "category": {
          "type": "string",
          "description": "Category for grouping launchers",
          "enum": ["modeling", "animation", "compositing", "rendering", "pipeline", "debug", "custom"],
          "default": "custom"
        },
        "environment": {
          "$ref": "#/definitions/environment"
        },
        "terminal": {
          "$ref": "#/definitions/terminal"
        },
        "variables": {
          "type": "object",
          "description": "Custom variables for substitution",
          "patternProperties": {
            "^[a-zA-Z][a-zA-Z0-9_]*$": {
              "type": "string"
            }
          }
        },
        "validation": {
          "$ref": "#/definitions/validation"
        },
        "pre_execution": {
          "type": "array",
          "description": "Commands to run before main command",
          "items": {
            "type": "string"
          }
        },
        "post_execution": {
          "type": "array",
          "description": "Commands to run after main command",
          "items": {
            "type": "string"
          }
        },
        "enabled": {
          "type": "boolean",
          "description": "Whether this launcher is enabled",
          "default": true
        }
      }
    },
    "environment": {
      "type": "object",
      "properties": {
        "type": {
          "type": "string",
          "enum": ["bash", "rez", "conda", "custom"],
          "default": "bash"
        },
        "packages": {
          "type": "array",
          "description": "Packages to include (for rez/conda environments)",
          "items": {
            "type": "string"
          }
        },
        "command_prefix": {
          "type": "string",
          "description": "Custom command prefix for environment setup"
        },
        "variables": {
          "type": "object",
          "description": "Environment variables to set",
          "patternProperties": {
            "^[A-Z][A-Z0-9_]*$": {
              "type": "string"
            }
          }
        },
        "source_files": {
          "type": "array",
          "description": "Files to source before execution",
          "items": {
            "type": "string"
          }
        }
      }
    },
    "terminal": {
      "type": "object",
      "properties": {
        "required": {
          "type": "boolean",
          "description": "Whether a terminal window is required",
          "default": true
        },
        "persist": {
          "type": "boolean",
          "description": "Whether to keep terminal open after execution",
          "default": false
        },
        "title": {
          "type": "string",
          "description": "Custom terminal window title (supports variables)",
          "maxLength": 100
        },
        "geometry": {
          "type": "string",
          "description": "Terminal window geometry (WIDTHxHEIGHT+X+Y)",
          "pattern": "^\\d+x\\d+(\\+\\d+\\+\\d+)?$"
        },
        "working_directory": {
          "type": "string",
          "description": "Working directory for terminal (supports variables)"
        }
      }
    },
    "validation": {
      "type": "object",
      "properties": {
        "check_executable": {
          "type": "boolean",
          "description": "Whether to verify executable exists in PATH",
          "default": true
        },
        "required_files": {
          "type": "array",
          "description": "Files that must exist before execution",
          "items": {
            "type": "string"
          }
        },
        "required_environment_vars": {
          "type": "array",
          "description": "Environment variables that must be set",
          "items": {
            "type": "string"
          }
        },
        "minimum_permissions": {
          "type": "string",
          "description": "Minimum file permissions required",
          "enum": ["read", "execute", "write"]
        }
      }
    }
  }
}
```

---

## API Documentation

### CustomLauncherManager Class

#### Core Methods

##### `load_configuration(config_path: Optional[str] = None) -> bool`
**Description**: Load custom launcher configuration from JSON file.

**Parameters**:
- `config_path`: Optional path to configuration file. If None, uses default location.

**Returns**: `True` if successful, `False` otherwise.

**Example**:
```python
manager = CustomLauncherManager()
success = manager.load_configuration()
if not success:
    print("Failed to load configuration")
```

**Error Codes**:
- `CONFIG_NOT_FOUND`: Configuration file not found
- `INVALID_JSON`: JSON parsing error
- `SCHEMA_VALIDATION_FAILED`: Configuration doesn't match schema

---

##### `get_launchers() -> Dict[str, LauncherConfig]`
**Description**: Get all available custom launchers.

**Returns**: Dictionary mapping launcher IDs to configuration objects.

**Example**:
```python
launchers = manager.get_launchers()
for launcher_id, config in launchers.items():
    print(f"{launcher_id}: {config.name}")
```

---

##### `execute_launcher(launcher_id: str, shot: Shot, **kwargs) -> LaunchResult`
**Description**: Execute a custom launcher in shot context.

**Parameters**:
- `launcher_id`: ID of the launcher to execute
- `shot`: Shot object providing context
- `**kwargs`: Additional variables for substitution

**Returns**: `LaunchResult` object with execution details.

**Example**:
```python
result = manager.execute_launcher(
    "my_custom_app",
    current_shot,
    custom_var="value"
)
if result.success:
    print(f"Launched successfully: PID {result.process_id}")
else:
    print(f"Launch failed: {result.error_message}")
```

---

##### `validate_launcher(launcher_config: LauncherConfig) -> ValidationResult`
**Description**: Validate a launcher configuration before execution.

**Parameters**:
- `launcher_config`: Configuration to validate

**Returns**: `ValidationResult` with validation status and messages.

**Example**:
```python
validation = manager.validate_launcher(config)
if not validation.is_valid:
    for error in validation.errors:
        print(f"Validation error: {error}")
```

---

### LauncherConfig Class

#### Properties

```python
class LauncherConfig:
    name: str                    # Display name
    description: str             # Description text
    command: str                 # Command template
    category: str                # Category for grouping
    environment: EnvironmentConfig  # Environment settings
    terminal: TerminalConfig     # Terminal settings
    variables: Dict[str, str]    # Custom variables
    validation: ValidationConfig # Validation rules
    pre_execution: List[str]     # Pre-execution commands
    post_execution: List[str]    # Post-execution commands
    enabled: bool                # Whether enabled
```

#### Methods

##### `substitute_variables(shot: Shot, **kwargs) -> str`
**Description**: Substitute variables in command template.

**Parameters**:
- `shot`: Shot object for context variables
- `**kwargs`: Additional variables

**Returns**: Command string with variables substituted.

---

##### `validate() -> ValidationResult`
**Description**: Validate this launcher configuration.

**Returns**: Validation result with any errors or warnings.

---

### Variable Substitution

#### Built-in Variables

The following variables are automatically available for substitution:

| Variable | Description | Example |
|----------|-------------|---------|
| `{workspace_path}` | Shot workspace directory | `/shows/myshow/shots/seq01/seq01_0010` |
| `{show}` | Show name | `myshow` |
| `{sequence}` | Sequence name | `seq01` |
| `{shot}` | Shot name | `0010` |
| `{full_name}` | Full shot name | `seq01_0010` |
| `{user}` | Current username | `gabriel-h` |
| `{home}` | User home directory | `/home/gabriel-h` |
| `{timestamp}` | Current timestamp | `2024-01-15_14-30-00` |
| `{date}` | Current date | `2024-01-15` |
| `{time}` | Current time | `14:30:00` |

#### Custom Variables

Custom variables can be defined in the launcher configuration:

```json
{
  "variables": {
    "tool_path": "/studio/tools/my_tool",
    "config_file": "{workspace_path}/config/tool_config.json"
  }
}
```

Variables can reference other variables and will be resolved recursively.

---

### Signal System

#### Signals Emitted

##### `launcher_executed(launcher_id: str, command: str, timestamp: str)`
**Description**: Emitted when a launcher is successfully executed.

**Parameters**:
- `launcher_id`: ID of the executed launcher
- `command`: Full command that was executed
- `timestamp`: Execution timestamp

---

##### `launcher_failed(launcher_id: str, error: str, timestamp: str)`
**Description**: Emitted when launcher execution fails.

**Parameters**:
- `launcher_id`: ID of the failed launcher
- `error`: Error message
- `timestamp`: Failure timestamp

---

##### `configuration_loaded(config_path: str, launcher_count: int)`
**Description**: Emitted when configuration is successfully loaded.

**Parameters**:
- `config_path`: Path to loaded configuration file
- `launcher_count`: Number of launchers loaded

---

##### `configuration_error(config_path: str, error: str)`
**Description**: Emitted when configuration loading fails.

**Parameters**:
- `config_path`: Path to configuration file
- `error`: Error message

---

### Terminal Execution Methods

#### Supported Terminal Emulators

1. **gnome-terminal** (preferred)
   - Full feature support
   - Custom titles and geometry
   - Tab and window management

2. **konsole**
   - KDE desktop environment
   - Profile support
   - Tab management

3. **xterm**
   - Universal fallback
   - Basic functionality
   - Limited customization

4. **alacritty**
   - GPU-accelerated
   - YAML configuration
   - Cross-platform

5. **terminator**
   - Advanced terminal features
   - Split panes
   - Plugin support

#### Terminal Command Construction

```python
def build_terminal_command(self, launcher_config: LauncherConfig, 
                          final_command: str) -> List[str]:
    """Build terminal command based on configuration and preferences."""
    
    terminal = launcher_config.terminal
    
    if self.preferred_terminal == "gnome-terminal":
        cmd = ["gnome-terminal"]
        
        if terminal.title:
            cmd.extend(["--title", terminal.title])
            
        if terminal.geometry:
            cmd.extend(["--geometry", terminal.geometry])
            
        if terminal.working_directory:
            cmd.extend(["--working-directory", terminal.working_directory])
            
        cmd.extend(["--", "bash", "-i", "-c", final_command])
        
        if terminal.persist:
            final_command += "; read -p 'Press Enter to close...'"
            
    return cmd
```

---

### Error Handling

#### Error Codes

| Code | Description | Resolution |
|------|-------------|------------|
| `LAUNCHER_NOT_FOUND` | Launcher ID not found | Check launcher configuration |
| `COMMAND_VALIDATION_FAILED` | Command validation failed | Fix command syntax |
| `EXECUTABLE_NOT_FOUND` | Executable not in PATH | Install or configure PATH |
| `INSUFFICIENT_PERMISSIONS` | Insufficient file permissions | Check file permissions |
| `ENVIRONMENT_SETUP_FAILED` | Environment setup failed | Check environment configuration |
| `TERMINAL_NOT_AVAILABLE` | No terminal emulator available | Install terminal emulator |
| `VARIABLE_SUBSTITUTION_FAILED` | Variable substitution error | Check variable definitions |
| `PRE_EXECUTION_FAILED` | Pre-execution command failed | Check pre-execution commands |
| `LAUNCH_TIMEOUT` | Launch process timeout | Increase timeout or check command |

#### Exception Hierarchy

```python
class LauncherError(Exception):
    """Base exception for launcher errors."""
    pass

class ConfigurationError(LauncherError):
    """Configuration-related errors."""
    pass

class ValidationError(LauncherError):
    """Validation-related errors."""
    pass

class ExecutionError(LauncherError):
    """Execution-related errors."""
    pass
```

---

## User Guide

### Getting Started

#### 1. Create Configuration File

Create the configuration directory and file:

```bash
mkdir -p ~/.shotbot
touch ~/.shotbot/custom_launchers.json
```

#### 2. Basic Configuration

Start with a simple launcher configuration:

```json
{
  "version": "1.0",
  "launchers": {
    "my_tool": {
      "name": "My Custom Tool",
      "description": "Custom pipeline tool",
      "command": "/studio/tools/my_tool --shot={full_name}",
      "category": "pipeline"
    }
  }
}
```

#### 3. Test the Configuration

Launch ShotBot and verify your custom launcher appears in the application menu.

### Adding Custom Launchers

#### Simple Application Launcher

```json
{
  "blender": {
    "name": "Blender",
    "description": "Open Blender in shot context",
    "command": "blender",
    "category": "modeling",
    "terminal": {
      "required": false
    }
  }
}
```

#### Script with Arguments

```json
{
  "plate_check": {
    "name": "Plate Checker",
    "description": "Verify plate sequences",
    "command": "python3 /studio/tools/plate_checker.py --path={workspace_path}",
    "category": "pipeline",
    "terminal": {
      "required": true,
      "persist": true,
      "title": "Plate Check - {full_name}"
    }
  }
}
```

#### Rez Environment Launcher

```json
{
  "nuke_custom": {
    "name": "Nuke (Custom Build)",
    "description": "Launch custom Nuke build with specific packages",
    "command": "nuke",
    "category": "compositing",
    "environment": {
      "type": "rez",
      "packages": ["nuke-13.2.1", "my_nuke_plugins", "ocio_configs"],
      "variables": {
        "NUKE_PATH": "/studio/nuke/plugins",
        "OCIO": "/studio/config/aces_1.2/config.ocio"
      }
    }
  }
}
```

### Variable Usage Examples

#### File Path Construction

```json
{
  "variables": {
    "scene_file": "{workspace_path}/maya/scenes/{full_name}_layout_v001.ma",
    "output_dir": "{workspace_path}/maya/renders/{sequence}",
    "reference_plate": "{workspace_path}/plates/latest/{shot}.####.exr"
  }
}
```

#### Date/Time Stamping

```json
{
  "render_submit": {
    "name": "Submit Render",
    "command": "/studio/tools/submit_render.py --shot={full_name} --timestamp={timestamp}",
    "variables": {
      "log_file": "/tmp/render_submit_{full_name}_{timestamp}.log"
    }
  }
}
```

### Terminal Configuration

#### Custom Window Title

```json
{
  "terminal": {
    "required": true,
    "title": "Debug Session - {show} {sequence} {shot}",
    "persist": true
  }
}
```

#### Specific Working Directory

```json
{
  "terminal": {
    "required": true,
    "working_directory": "{workspace_path}/scripts",
    "geometry": "120x30+100+100"
  }
}
```

### Environment Management

#### Rez Package Environment

```json
{
  "environment": {
    "type": "rez",
    "packages": [
      "python-3.9",
      "PySide6_Essentials",
      "numpy",
      "my_studio_tools"
    ],
    "variables": {
      "PYTHONPATH": "/studio/python/lib",
      "STUDIO_ROOT": "/studio"
    }
  }
}
```

#### Conda Environment

```json
{
  "environment": {
    "type": "conda",
    "packages": ["conda", "activate", "my_env"],
    "command_prefix": "conda activate my_env &&"
  }
}
```

#### Custom Environment Setup

```json
{
  "environment": {
    "type": "custom",
    "command_prefix": "source /studio/env/setup.sh &&",
    "variables": {
      "STUDIO_ENV": "production",
      "LOG_LEVEL": "INFO"
    },
    "source_files": [
      "/studio/env/aliases.sh",
      "$HOME/.studio_profile"
    ]
  }
}
```

### Validation Configuration

#### Executable Validation

```json
{
  "validation": {
    "check_executable": true,
    "required_files": [
      "/studio/tools/my_tool",
      "{workspace_path}/config/tool_config.json"
    ],
    "required_environment_vars": ["STUDIO_ROOT", "SHOT_ROOT"]
  }
}
```

#### File Permission Checks

```json
{
  "validation": {
    "required_files": ["{workspace_path}/data/input.mov"],
    "minimum_permissions": "read"
  }
}
```

### Pre/Post Execution Commands

#### Setup and Cleanup

```json
{
  "pre_execution": [
    "echo 'Starting tool for shot {full_name}'",
    "mkdir -p {workspace_path}/temp",
    "cd {workspace_path}"
  ],
  "post_execution": [
    "echo 'Tool execution completed'",
    "rm -rf {workspace_path}/temp",
    "echo 'Press Enter to close terminal'",
    "read"
  ]
}
```

---

## Developer Documentation

### Extension Points

#### Adding New Terminal Types

To add support for a new terminal emulator:

1. **Extend Terminal Builder**:

```python
class TerminalBuilder:
    def build_command(self, terminal_type: str, config: TerminalConfig, 
                     command: str) -> List[str]:
        builders = {
            'gnome-terminal': self._build_gnome_terminal,
            'konsole': self._build_konsole,
            'xterm': self._build_xterm,
            'my_terminal': self._build_my_terminal,  # Add new builder
        }
        
        builder = builders.get(terminal_type)
        if not builder:
            raise UnsupportedTerminalError(f"Unsupported terminal: {terminal_type}")
            
        return builder(config, command)
    
    def _build_my_terminal(self, config: TerminalConfig, command: str) -> List[str]:
        """Build command for my custom terminal."""
        cmd = ["my_terminal"]
        
        if config.title:
            cmd.extend(["--title", config.title])
            
        cmd.extend(["--execute", command])
        return cmd
```

2. **Register Terminal**:

```python
# In terminal registry
SUPPORTED_TERMINALS = {
    'gnome-terminal': {
        'executable': 'gnome-terminal',
        'features': ['title', 'geometry', 'working_directory', 'tabs'],
        'builder': '_build_gnome_terminal'
    },
    'my_terminal': {
        'executable': 'my_terminal',
        'features': ['title', 'execute'],
        'builder': '_build_my_terminal'
    }
}
```

3. **Update Schema**:

```json
{
  "terminal_preferences": {
    "items": {
      "enum": ["gnome-terminal", "konsole", "xterm", "my_terminal"]
    }
  }
}
```

#### Adding New Environment Types

To add support for a new environment management system:

1. **Implement Environment Handler**:

```python
class MyEnvironmentHandler(EnvironmentHandler):
    def setup_command(self, config: EnvironmentConfig, base_command: str) -> str:
        """Setup environment for command execution."""
        if config.type != "my_env":
            return base_command
            
        # Build environment setup
        env_cmd = "my_env_setup"
        
        if config.packages:
            env_cmd += f" --packages {' '.join(config.packages)}"
            
        if config.variables:
            for key, value in config.variables.items():
                env_cmd += f" --env {key}={value}"
                
        return f"{env_cmd} -- {base_command}"
    
    def validate_environment(self, config: EnvironmentConfig) -> ValidationResult:
        """Validate environment configuration."""
        result = ValidationResult()
        
        # Check if my_env_setup is available
        if not shutil.which("my_env_setup"):
            result.add_error("my_env_setup not found in PATH")
            
        return result
```

2. **Register Handler**:

```python
# In environment registry
ENVIRONMENT_HANDLERS = {
    'bash': BashEnvironmentHandler(),
    'rez': RezEnvironmentHandler(),
    'conda': CondaEnvironmentHandler(),
    'my_env': MyEnvironmentHandler(),
}
```

#### Custom Validation Rules

Add custom validation logic:

```python
class CustomValidationRule(ValidationRule):
    def __init__(self, name: str, rule_func: Callable):
        self.name = name
        self.rule_func = rule_func
    
    def validate(self, launcher_config: LauncherConfig, 
                shot: Shot) -> ValidationResult:
        """Apply custom validation rule."""
        result = ValidationResult()
        
        try:
            self.rule_func(launcher_config, shot, result)
        except Exception as e:
            result.add_error(f"Validation rule '{self.name}' failed: {e}")
            
        return result

# Register custom rule
def check_shot_has_plates(config: LauncherConfig, shot: Shot, result: ValidationResult):
    plate_path = f"{shot.workspace_path}/plates"
    if not os.path.exists(plate_path):
        result.add_warning(f"No plates directory found: {plate_path}")

validation_manager.register_rule(
    CustomValidationRule("shot_has_plates", check_shot_has_plates)
)
```

#### Plugin System

Create a plugin architecture for custom launchers:

```python
class LauncherPlugin(ABC):
    @abstractmethod
    def get_launcher_configs(self) -> Dict[str, LauncherConfig]:
        """Return launcher configurations provided by this plugin."""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Return plugin name."""
        pass
    
    def initialize(self) -> bool:
        """Initialize plugin. Return True if successful."""
        return True
    
    def cleanup(self):
        """Cleanup plugin resources."""
        pass

class MyPlugin(LauncherPlugin):
    def get_launcher_configs(self) -> Dict[str, LauncherConfig]:
        return {
            "my_tool": LauncherConfig(
                name="My Tool",
                command="/path/to/my_tool",
                # ... other config
            )
        }
    
    def get_name(self) -> str:
        return "My Studio Plugin"
```

### Integration with Existing Features

#### Shot Model Integration

Custom launchers automatically integrate with the existing shot model:

```python
# In CommandLauncher class
def launch_custom_app(self, launcher_id: str, **kwargs) -> bool:
    """Launch a custom application."""
    if not self.current_shot:
        self._emit_error("No shot selected")
        return False
    
    # Get custom launcher
    launcher_config = self.custom_manager.get_launcher(launcher_id)
    if not launcher_config:
        self._emit_error(f"Unknown custom launcher: {launcher_id}")
        return False
    
    # Execute with shot context
    result = self.custom_manager.execute_launcher(
        launcher_id, 
        self.current_shot, 
        **kwargs
    )
    
    return result.success
```

#### UI Integration

Custom launchers appear in the main application UI:

```python
# In main window
def populate_custom_launchers_menu(self):
    """Add custom launchers to application menu."""
    custom_menu = self.menubar.addMenu("Custom Tools")
    
    launchers = self.command_launcher.custom_manager.get_launchers()
    
    # Group by category
    categories = {}
    for launcher_id, config in launchers.items():
        category = config.category or "Other"
        if category not in categories:
            categories[category] = []
        categories[category].append((launcher_id, config))
    
    # Create menu items
    for category, launcher_list in categories.items():
        category_menu = custom_menu.addMenu(category.title())
        
        for launcher_id, config in launcher_list:
            action = QAction(config.name, self)
            action.setStatusTip(config.description)
            action.triggered.connect(
                lambda checked, lid=launcher_id: 
                self.launch_custom_app(lid)
            )
            category_menu.addAction(action)
```

#### Logging Integration

Custom launcher execution is logged using the existing logging system:

```python
# In custom launcher manager
def execute_launcher(self, launcher_id: str, shot: Shot, **kwargs) -> LaunchResult:
    """Execute launcher with full logging."""
    logger.info(f"Executing custom launcher: {launcher_id}")
    logger.debug(f"Shot context: {shot.full_name}")
    logger.debug(f"Additional variables: {kwargs}")
    
    try:
        # Execute launcher
        result = self._do_execute(launcher_id, shot, **kwargs)
        
        if result.success:
            logger.info(f"Custom launcher executed successfully: {launcher_id}")
            self.command_executed.emit(
                datetime.now().strftime("%H:%M:%S"),
                f"Custom: {result.command}"
            )
        else:
            logger.error(f"Custom launcher failed: {result.error_message}")
            self.command_error.emit(
                datetime.now().strftime("%H:%M:%S"),
                f"Custom launcher failed: {result.error_message}"
            )
            
        return result
        
    except Exception as e:
        logger.exception(f"Exception executing custom launcher {launcher_id}")
        return LaunchResult(success=False, error_message=str(e))
```

---

## FAQ and Troubleshooting

### Frequently Asked Questions

#### Q: How do I launch ShotBot itself as a custom launcher?

**A**: Use a rez environment configuration like this:

```json
{
  "shotbot_debug": {
    "name": "ShotBot Debug",
    "description": "Launch ShotBot with debug logging in current shot context",
    "command": "python3 '{shotbot_path}' --debug",
    "environment": {
      "type": "rez",
      "packages": ["PySide6_Essentials", "pillow", "Jinja2"]
    },
    "variables": {
      "shotbot_path": "/nethome/gabriel-h/output/ShotBotv5/copy/shotbot.py"
    },
    "terminal": {
      "required": true,
      "persist": false
    }
  }
}
```

#### Q: Can I use environment variables in my commands?

**A**: Yes, environment variables are supported in several ways:

1. **Direct shell expansion**: `$HOME`, `$USER`, etc.
2. **Environment configuration**: Set variables in the environment section
3. **Variable substitution**: Use `{variable}` syntax for custom variables

```json
{
  "command": "$MY_TOOL_PATH/tool --config=$HOME/.tool_config --shot={full_name}",
  "environment": {
    "variables": {
      "MY_TOOL_PATH": "/studio/tools",
      "TOOL_CONFIG": "{workspace_path}/config"
    }
  }
}
```

#### Q: How do I handle tools that require interactive input?

**A**: Use terminal persistence and pre/post execution commands:

```json
{
  "terminal": {
    "required": true,
    "persist": true
  },
  "post_execution": [
    "echo 'Tool execution completed'",
    "read -p 'Press Enter to close...'"
  ]
}
```

#### Q: Can I create launchers that work without a selected shot?

**A**: Currently, all launchers require shot context. However, you can create global launchers by:

1. Using minimal shot-dependent variables
2. Providing fallback values in your scripts
3. Using the `{user}` and `{home}` variables which don't depend on shot selection

#### Q: How do I debug launcher execution issues?

**A**: Enable debug logging and check the logs:

1. **Enable debug mode**: Set `SHOTBOT_DEBUG=1` environment variable
2. **Check logs**: Look at console output or log files
3. **Test commands manually**: Copy the generated command and run it manually
4. **Use validation**: Enable all validation options to catch issues early

### Common Issues and Solutions

#### Issue: "Launcher not found" error

**Symptoms**: Custom launcher doesn't appear in the UI or fails to execute.

**Causes**:
- Configuration file not found
- Invalid JSON syntax
- Launcher ID not matching pattern `^[a-zA-Z][a-zA-Z0-9_-]*$`

**Solutions**:
1. Check configuration file location: `~/.shotbot/custom_launchers.json`
2. Validate JSON syntax using online validator
3. Ensure launcher IDs follow naming convention
4. Check ShotBot logs for configuration errors

#### Issue: "Command validation failed" error

**Symptoms**: Launcher fails to execute with validation error.

**Causes**:
- Executable not found in PATH
- Required files don't exist
- Insufficient permissions

**Solutions**:
1. **Check executable**: `which my_command`
2. **Verify file paths**: Ensure all referenced files exist
3. **Check permissions**: Use `ls -la` to verify file permissions
4. **Disable validation temporarily**: Set `"check_executable": false` for testing

#### Issue: "No terminal available" error

**Symptoms**: Launcher fails to start with terminal error.

**Causes**:
- No supported terminal emulator installed
- Terminal emulator not in PATH
- X11/Wayland display issues

**Solutions**:
1. **Install terminal**: `sudo apt install gnome-terminal`
2. **Check PATH**: Ensure terminal executable is in PATH
3. **Try different terminal**: Update `terminal_preferences` in config
4. **Check display**: Ensure `$DISPLAY` is set correctly

#### Issue: "Variable substitution failed" error

**Symptoms**: Variables in commands not being replaced correctly.

**Causes**:
- Undefined variables
- Circular variable references
- Invalid variable syntax

**Solutions**:
1. **Check variable names**: Ensure all variables are defined
2. **Use built-in variables**: Start with `{workspace_path}`, `{full_name}`, etc.
3. **Test variable expansion**: Use echo commands to verify values
4. **Avoid circular references**: Variables should not reference themselves

#### Issue: "Environment setup failed" error

**Symptoms**: Rez or conda environment fails to activate.

**Causes**:
- Missing packages
- Incorrect package names
- Environment system not available

**Solutions**:
1. **Test environment manually**: Try rez/conda commands independently
2. **Check package names**: Verify package names and versions
3. **Use simpler environment**: Start with basic bash environment
4. **Check system availability**: Ensure rez/conda is installed and configured

#### Issue: Commands fail with "Permission denied"

**Symptoms**: Executable launches but fails with permission error.

**Causes**:
- Script not executable
- Missing file permissions
- SELinux/AppArmor restrictions

**Solutions**:
1. **Make executable**: `chmod +x /path/to/script`
2. **Check file ownership**: Ensure files are owned by current user
3. **Test permissions**: Run commands manually to verify
4. **Check security systems**: Disable SELinux/AppArmor temporarily for testing

#### Issue: Terminal window doesn't persist

**Symptoms**: Terminal closes immediately after command execution.

**Causes**:
- Command exits quickly
- Terminal configuration issues
- Post-execution commands not configured

**Solutions**:
1. **Enable persistence**: Set `"persist": true` in terminal config
2. **Add pause command**: Include `read` command in post-execution
3. **Use background processes**: For long-running commands, use `&` or nohup
4. **Check terminal features**: Some terminals may not support persistence

### Performance Considerations

#### Large Configuration Files

**Issue**: Slow startup with many custom launchers.

**Solutions**:
- Lazy load launcher configurations
- Cache parsed configurations
- Split configurations into multiple files
- Disable unused launchers

#### Memory Usage

**Issue**: High memory usage with many launchers.

**Solutions**:
- Use object pooling for launcher instances
- Implement garbage collection for unused launchers
- Limit concurrent launcher executions
- Monitor memory usage in long-running sessions

#### Network File Systems

**Issue**: Slow performance with configuration on network storage.

**Solutions**:
- Cache configurations locally
- Use local temporary directories for execution
- Implement background configuration updates
- Monitor network latency and timeout appropriately

---

## Best Practices

### Configuration Management

#### 1. Organize by Category

Group related launchers together:

```json
{
  "launchers": {
    "modeling_maya": { "category": "modeling", "name": "Maya" },
    "modeling_blender": { "category": "modeling", "name": "Blender" },
    "comp_nuke": { "category": "compositing", "name": "Nuke" },
    "comp_fusion": { "category": "compositing", "name": "Fusion" }
  }
}
```

#### 2. Use Descriptive Names and Descriptions

```json
{
  "plate_validator": {
    "name": "Plate Sequence Validator",
    "description": "Validates plate sequences for missing frames, color space, and resolution consistency"
  }
}
```

#### 3. Version Your Configurations

```json
{
  "version": "1.0",
  "config_version": "2024-01-15_v1.2",
  "last_updated": "2024-01-15T14:30:00Z"
}
```

#### 4. Use Environment-Specific Configurations

Maintain separate configurations for different environments:

- `custom_launchers_dev.json` - Development environment
- `custom_launchers_prod.json` - Production environment
- `custom_launchers_local.json` - Local overrides

### Command Design

#### 1. Use Absolute Paths

Always use absolute paths for executables and files:

```json
{
  "command": "/studio/tools/my_tool --config=/studio/config/tool.conf"
}
```

#### 2. Handle Paths with Spaces

Quote paths that might contain spaces:

```json
{
  "command": "my_tool --input='{workspace_path}/input file.mov'"
}
```

#### 3. Provide Fallback Values

Use variables with fallback values:

```json
{
  "variables": {
    "output_format": "${OUTPUT_FORMAT:-exr}",
    "thread_count": "${THREAD_COUNT:-4}"
  }
}
```

#### 4. Validate Dependencies

Always validate required dependencies:

```json
{
  "validation": {
    "required_files": ["/studio/tools/my_tool"],
    "required_environment_vars": ["STUDIO_ROOT"],
    "check_executable": true
  }
}
```

### Error Handling

#### 1. Graceful Degradation

Design commands to handle missing resources gracefully:

```bash
# Good: Check for optional resources
if [ -f "$OPTIONAL_CONFIG" ]; then
    my_tool --config="$OPTIONAL_CONFIG"
else
    my_tool --use-defaults
fi
```

#### 2. Comprehensive Logging

Include logging in your commands:

```json
{
  "pre_execution": [
    "echo '[INFO] Starting tool execution for {full_name}'",
    "echo '[INFO] Workspace: {workspace_path}'"
  ],
  "post_execution": [
    "echo '[INFO] Tool execution completed'",
    "echo '[INFO] Check logs at: {workspace_path}/logs/'"
  ]
}
```

#### 3. Timeout Management

Set appropriate timeouts for long-running processes:

```json
{
  "command": "timeout 300 /studio/tools/long_running_tool",
  "post_execution": [
    "if [ $? -eq 124 ]; then echo '[WARNING] Tool timed out after 5 minutes'; fi"
  ]
}
```

### Security Considerations

#### 1. Input Validation

Validate all user inputs and file paths:

```json
{
  "validation": {
    "required_files": ["{workspace_path}"],
    "minimum_permissions": "read"
  }
}
```

#### 2. Avoid Shell Injection

Use parameterized commands when possible:

```json
{
  "command": "python3 /studio/tools/safe_tool.py --shot-name '{full_name}' --workspace '{workspace_path}'"
}
```

#### 3. Limit File Access

Use working directories to limit file access:

```json
{
  "terminal": {
    "working_directory": "{workspace_path}",
    "required": true
  }
}
```

#### 4. Environment Isolation

Use environment management to isolate tool execution:

```json
{
  "environment": {
    "type": "rez",
    "packages": ["isolated_tool_env"]
  }
}
```

### Performance Optimization

#### 1. Cache Validation Results

Cache expensive validation operations:

```python
@lru_cache(maxsize=128)
def validate_tool_availability(tool_path: str) -> bool:
    return os.path.exists(tool_path) and os.access(tool_path, os.X_OK)
```

#### 2. Lazy Load Configurations

Load configurations only when needed:

```python
class LazyLauncherConfig:
    def __init__(self, config_path: str):
        self._config_path = config_path
        self._config = None
    
    @property
    def config(self):
        if self._config is None:
            self._config = self._load_config()
        return self._config
```

#### 3. Background Validation

Validate launchers in background threads:

```python
def validate_all_launchers():
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(validate_launcher, launcher_id)
            for launcher_id in launcher_configs
        ]
        
        for future in as_completed(futures):
            result = future.result()
            # Handle validation result
```

#### 4. Optimize Terminal Startup

Choose fast-starting terminals and minimize initialization:

```json
{
  "terminal_preferences": [
    "alacritty",      // Fast GPU-accelerated
    "gnome-terminal", // Feature-rich but slower
    "xterm"           // Minimal fallback
  ]
}
```

### Testing and Debugging

#### 1. Create Test Configurations

Maintain test configurations with known working setups:

```json
{
  "test_echo": {
    "name": "Test Echo",
    "description": "Simple test launcher that echoes shot information",
    "command": "echo 'Shot: {full_name}, Path: {workspace_path}'",
    "category": "debug"
  }
}
```

#### 2. Use Debug Mode

Enable debug logging for troubleshooting:

```bash
SHOTBOT_DEBUG=1 python3 shotbot.py
```

#### 3. Manual Command Testing

Always test generated commands manually:

```bash
# Copy command from logs and test
ws /shows/myshow/shots/seq01/seq01_0010 && my_tool --shot=seq01_0010
```

#### 4. Incremental Configuration

Build configurations incrementally:

1. Start with simple command
2. Add environment setup
3. Add validation
4. Add pre/post execution
5. Add terminal customization

This systematic approach helps identify issues early and ensures reliable launcher configurations.