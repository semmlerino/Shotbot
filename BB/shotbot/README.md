# ShotBot - VFX Shot Launcher

A PySide6 GUI application for browsing VFX shots and launching applications in shot context.

## Features

- Visual shot browsing with thumbnail grid
- Launch applications (3de, Nuke, Maya, RV, Publish) in shot context
- Automatic thumbnail loading from shot directories with caching
- Resizable thumbnail view with Ctrl+scroll zoom
- Command logging with timestamps
- Persistent settings (last selected shot, window layout, thumbnail size)
- Dark theme optimized for VFX workflows
- Enhanced shot selection visibility with glow effect
- Nuke integration: Optional undistortion nodes and raw plate loading
- Background shot refresh with change detection

## Requirements

- Python 3.8+
- PySide6
- Access to `ws -sg` command for shot listing
- Linux environment (for terminal launching)

## Installation

1. Clone or download the shotbot directory
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\Scripts\activate     # Windows
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. For development, also install dev dependencies:
   ```bash
   pip install -r requirements-dev.txt
   ```

## Usage

Run the application:
```bash
python shotbot.py
# or
./shotbot.py
```

### Keyboard Shortcuts

- `F5` - Refresh shot list
- `Ctrl + +` - Increase thumbnail size
- `Ctrl + -` - Decrease thumbnail size
- `Ctrl + Mouse Wheel` - Zoom thumbnails
- `Double-click` on shot - Launch default app (Nuke)

### Shot Thumbnails

Thumbnails are loaded from:
```
/shows/<show>/shots/<sequence>/<shot>/publish/editorial/cutref/v001/jpg/1920x1080/
```

If no thumbnail is found, a placeholder is displayed.

## Architecture

- `shotbot.py` - Main entry point
- `main_window.py` - Main application window with shot info panel
- `shot_model.py` - Shot data model with caching and change detection
- `shot_grid.py` - Thumbnail grid widget
- `thumbnail_widget.py` - Individual thumbnail display with selection effects
- `command_launcher.py` - Application launching logic with Nuke integration
- `log_viewer.py` - Command history display
- `shot_info_panel.py` - Current shot information display
- `cache_manager.py` - Thumbnail and shot list caching
- `undistortion_finder.py` - Finds undistortion .nk files for Nuke
- `raw_plate_finder.py` - Finds raw plate sequences for Nuke
- `config.py` - Configuration constants

## Settings

Settings are stored in `~/.shotbot/settings.json` and include:
- Window geometry and layout
- Last selected shot
- Thumbnail size preference

## Development

### Code Quality

```bash
# Run linting
source venv/bin/activate
ruff check .
ruff format .

# Type checking with basedpyright
source venv/bin/activate
python -m basedpyright

# Or use the convenience script
./typecheck.sh
```

### Testing

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

## Customization

To add new applications, edit the `APPS` dictionary in `config.py`:
```python
APPS = {
    "3de": "3de",
    "nuke": "nuke",
    "maya": "maya",
    "rv": "rv",
    "publish": "publish_standalone",
    "houdini": "houdini"  # Add new app
}
```