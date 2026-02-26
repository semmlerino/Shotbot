# ShotBot - Matchmove Shot Launcher

A PySide6 GUI application for a **Matchmove artist at BlueBolt**, providing shot browsing and DCC launching tailored to the matchmove pipeline.

## Matchmove Workflow

Shotbot supports the standard matchmove pipeline:

```
3DEqualizer → Maya → Nuke → Publish
   (track)    (finalize)  (review)  (deliver)
```

1. **3DEqualizer**: Camera tracking, point clouds, lens distortion
2. **Maya**: Import tracked camera, scene finalization, playblasts
3. **Nuke**: Review playblasts, comp checks, final tweaks
4. **Publish**: Export deliverables from Nuke

## Features

- Visual shot browsing with thumbnail grid
- Three-tab interface:
  - **My Shots**: Your current shots from `ws -sg`
  - **Other 3DE scenes**: Browse 3DE scenes created by other artists
  - **Previous Shots**: Completed/migrated shots from prior sessions
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

- Python 3.11+
- PySide6
- Pillow
- Access to `ws -sg` command for shot listing
- Linux environment (for terminal launching)

## Installation

1. Clone or download the shotbot directory
2. Install [uv](https://github.com/astral-sh/uv) (fast Python package manager):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. Install dependencies:
   ```bash
   uv pip install -r requirements.txt
   ```

## Usage

### Normal Mode (Requires VFX Environment)
Run the application in a VFX environment with access to `ws -sg`:
```bash
uv run python shotbot.py
```

### Mock Mode (No VFX Environment Needed)
Run with mock data for development/testing without `ws` command:
```bash
uv run python shotbot.py --mock
# or
SHOTBOT_MOCK=1 uv run python shotbot.py
```

Mock mode uses demo shot data from `demo_shots.json` and doesn't require:
- Access to `ws -sg` command
- VFX facility network access
- Shot directories or thumbnails

Perfect for:
- Development and testing
- Offline work
- CI/CD pipelines
- Demos and training

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

The "Other 3DE scenes" tab shows 3DE scene files created by other matchmove artists. This is useful for:
- Seeing what shots colleagues are working on
- Picking up work from another artist
- Checking reference tracks for similar shots

- **Scene Discovery**: Automatically scans for .3de files in user directories:
  ```
  /shows/<show>/shots/<sequence>/<shot>/user/<username>/mm/3de/mm-default/scenes/scene/<plate>/*.3de
  ```
- **Enhanced Thumbnails**: Each thumbnail displays:
  - Shot name (e.g., "AB_123_0010")
  - User who created the scene (e.g., "john-d")
  - Plate name (e.g., "FG01", "BG01")
- **Scene Launching**: Double-clicking opens 3DE with the specific scene file
- **Caching**: Scene discovery uses persistent incremental caching (no TTL expiration)

## Architecture

### Core Components
- `shotbot.py` - Main entry point
- `main_window.py` - Main application window with tabbed interface
- `type_definitions.py` - Core type definitions (ShotData, ShotStatus, etc.)
- `config.py` - Configuration constants

### Shot Management
- `shot_model.py` - Shot data model with caching and change detection
- `shot_grid_view.py` - Thumbnail grid widget for "My Shots" tab
- `shot_info_panel.py` - Current shot information display
- `thumbnail_widget.py` - Individual thumbnail display with selection effects
- `previous_shots_model.py` - Data model for completed/migrated shots
- `previous_shots_view.py` - Grid widget for "Previous Shots" tab

### 3DE Scene Features
- `threede_scene_model.py` - Data model for 3DE scenes from other users
- `threede_scene_finder.py` - Discovers .3de files in user directories
- `threede_grid_view.py` - Grid widget for "Other 3DE scenes" tab
- `threede_thumbnail_widget.py` - Enhanced thumbnails showing user and plate info
- `threede_scene_worker.py` - Background scanner with progress reporting

### Application Integration
- `command_launcher.py` - Main launcher orchestrating application launches with shot context
- `refresh_orchestrator.py` - Coordinated data refresh logic
- `launch/` - Launch system components:
  - `command_builder.py` - Builds commands with rez wrapping, logging
  - `environment_manager.py` - Detects terminals, rez availability
  - `process_executor.py` - Executes processes in terminal emulators
  - `process_verifier.py` - Verifies process execution success
### Utilities
- `log_viewer.py` - Command history display
- `cache_manager.py` - Caching for thumbnails, shots, and 3DE scenes
- `controllers/` - Application controllers for filtering, shot selection, and UI state

## Settings

Settings are managed via Qt's QSettings system, stored at `~/.config/ShotBot/ShotBot.conf` on Linux. Persisted settings include:
- Window geometry and layout
- Last selected shot
- Thumbnail size preference
- Active tab selection
- Nuke integration preferences (undistortion nodes, raw plate loading)

## Development

### Code Quality

```bash
# Run linting
~/.local/bin/uv run ruff check .
~/.local/bin/uv run ruff format .

# Type checking with basedpyright
~/.local/bin/uv run basedpyright

# Or use the convenience script
./typecheck.sh
```

### Testing

```bash
# Default suite (parallel, Qt-safe)
~/.local/bin/uv run pytest tests/ -n auto --dist=loadgroup

# Comprehensive (includes legacy + performance tests)
~/.local/bin/uv run pytest tests/ tests/performance/ -m "" -n auto --dist=loadgroup

# Serial run (useful when iterating on a single suite)
~/.local/bin/uv run pytest tests/

# Targeted runs
~/.local/bin/uv run pytest tests/unit/test_shot_model.py -v
~/.local/bin/uv run pytest tests/unit/test_shot_model.py::TestShot::test_shot_creation -v
~/.local/bin/uv run pytest tests/ -k "test_cache" -v
```

> Coverage is disabled by default for faster runs. Enable manually with
> `~/.local/bin/uv run pytest tests/ --cov=. --cov-report=html:coverage_html`.

For deeper guidance (Qt hygiene, fixture behavior, debugging tips) see
[UNIFIED_TESTING_V2.md](./UNIFIED_TESTING_V2.md).

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
