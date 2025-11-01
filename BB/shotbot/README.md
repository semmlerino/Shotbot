# ShotBot - VFX Shot Launcher

A PySide6 GUI application for browsing VFX shots and launching applications in shot context.

## Features

- Visual shot browsing with thumbnail grid
- Two-tab interface:
  - **My Shots**: Your current shots from `ws -sg`
  - **Other 3DE scenes**: Browse 3DE scenes created by other artists
- Launch applications (3de, Nuke, Maya, RV, Publish) in shot context
- Automatic thumbnail loading from shot directories with caching
- Resizable thumbnail view with Ctrl+scroll zoom
- Command logging with timestamps
- Persistent settings (last selected shot, window layout, thumbnail size, active tab)
- Dark theme optimized for VFX workflows
- Enhanced shot selection visibility with glow effect
- Nuke integration: Optional undistortion nodes and raw plate loading
- Background shot refresh with change detection
- 3DE scene discovery: Automatically finds and displays 3DE scenes from other users

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
- `Arrow Keys` - Navigate between shots (works in both tabs)
- `Home` - Jump to first shot
- `End` - Jump to last shot
- `Enter` - Launch default app (Nuke for "My Shots", 3DE for "Other 3DE scenes")
- `Double-click` on shot - Launch default app (Nuke) or 3DE with scene file

### Shot Thumbnails

Thumbnails are loaded from:
```
/shows/<show>/shots/<sequence>/<shot>/publish/editorial/cutref/v001/jpg/1920x1080/
```

If no thumbnail is found, a placeholder is displayed.

### Other 3DE Scenes Tab

The "Other 3DE scenes" tab shows 3DE scene files created by other users (excluding gabriel-h):

- **Scene Discovery**: Automatically scans for .3de files in user directories:
  ```
  /shows/<show>/shots/<sequence>/<shot>/user/<username>/mm/3de/mm-default/scenes/scene/<plate>/*.3de
  ```
- **Enhanced Thumbnails**: Each thumbnail displays:
  - Shot name (e.g., "AB_123_0010")
  - User who created the scene (e.g., "john-d")
  - Plate name (e.g., "FG01", "BG01")
- **Scene Launching**: Double-clicking opens 3DE with the specific scene file
- **Caching**: Scene discovery results are cached for 30 minutes
- **Background Updates**: Scenes refresh automatically every 5 minutes

## Architecture

### Core Components
- `shotbot.py` - Main entry point
- `main_window.py` - Main application window with tabbed interface
- `config.py` - Configuration constants

### Shot Management
- `shot_model.py` - Shot data model with caching and change detection
- `shot_grid.py` - Thumbnail grid widget for "My Shots" tab
- `shot_info_panel.py` - Current shot information display
- `thumbnail_widget.py` - Individual thumbnail display with selection effects

### 3DE Scene Features
- `threede_scene_model.py` - Data model for 3DE scenes from other users
- `threede_scene_finder.py` - Discovers .3de files in user directories
- `threede_shot_grid.py` - Grid widget for "Other 3DE scenes" tab
- `threede_thumbnail_widget.py` - Enhanced thumbnails showing user and plate info
- `threede_scene_scanner.py` - Background scanner with progress reporting

### Application Integration
- `command_launcher.py` - Application launching with scene file support
- `undistortion_finder.py` - Finds undistortion .nk files for Nuke
- `raw_plate_finder.py` - Finds raw plate sequences for Nuke

### Utilities
- `log_viewer.py` - Command history display
- `cache_manager.py` - Caching for thumbnails, shots, and 3DE scenes

## Settings

Settings are stored in `~/.shotbot/settings.json` and include:
- Window geometry and layout
- Last selected shot
- Thumbnail size preference
- Active tab selection
- Nuke integration preferences (undistortion nodes, raw plate loading)

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