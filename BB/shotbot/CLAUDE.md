# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with the shotbot repository.

## Project Overview

ShotBot is a PySide6-based GUI application for VFX shot browsing and application launching. It integrates with VFX pipeline tools using the `ws` (workspace) command to list and navigate shots.

## Key Features

- Visual shot browsing with thumbnail grid
- Launch applications (3de, Nuke, Maya, RV, Publish) in shot context  
- Shot information panel with thumbnails
- Caching system for shots and thumbnails
- Background refresh with change detection
- Persistent settings using Qt's QSettings

## Architecture

### Core Components

- **`shotbot.py`** - Main entry point
- **`main_window.py`** - Main application window with shot info panel integration
- **`shot_model.py`** - Shot data model with caching and change detection
- **`shot_grid.py`** - Thumbnail grid widget
- **`thumbnail_widget.py`** - Individual thumbnail display
- **`command_launcher.py`** - Application launching using `ws` command
- **`log_viewer.py`** - Command history display
- **`shot_info_panel.py`** - Current shot information display
- **`cache_manager.py`** - Thumbnail and shot list caching
- **`config.py`** - Configuration constants

### Key Implementation Details

1. **Workspace Command**: Uses `ws` shell function (not an executable) via `bash -i -c`
2. **Settings Storage**: QByteArray hex conversion using `.data().decode('ascii')`
3. **Change Detection**: `refresh_shots()` returns tuple `(success, has_changes)`
4. **Caching**: Shots cached for 30 minutes, thumbnails cached permanently
5. **Background Refresh**: Every 5 minutes, only updates UI if changes detected

## Testing

**IMPORTANT**: Always run tests through the `run_tests.py` script to avoid Qt initialization issues and timeouts:

```bash
# Run all tests
python run_tests.py

# Run specific test file
python run_tests.py tests/unit/test_shot_model.py

# Run specific test
python run_tests.py tests/unit/test_shot_model.py::TestShot::test_shot_creation

# Run with coverage
python run_tests.py --cov

# Run tests matching a pattern
python run_tests.py -k "test_cache"
```

**Do NOT run pytest directly** as it will cause timeouts and Qt platform errors. The `run_tests.py` script properly configures the environment and disables xvfb plugin for WSL compatibility.

## Development Guidelines

### Running the Application

```bash
# In rez environment
rez env PySide6_Essentials pillow Jinja2 -- python3 shotbot.py

# Or with virtual environment
source venv/bin/activate
python shotbot.py
```

### Code Quality

```bash
# Run linting
source venv/bin/activate
ruff check .
ruff format .

# Type checking (if basedpyright is installed)
basedpyright
```

### Common Issues

1. **"ws command not found"**: The `ws` command is a shell function, not an executable. Use `bash -i -c` to invoke it.

2. **Qt platform errors**: Use `run_tests.py` for testing, not direct pytest invocation.

3. **Settings hex conversion**: Use `.data().decode('ascii')` for QByteArray to hex string conversion.

## Recent Changes

- Added shot info panel showing current shot details
- Implemented caching system with background refresh
- Fixed subprocess execution for VFX environment
- Updated tests to match new API (tuple return from refresh_shots)
- Reduced excessive mocking in tests