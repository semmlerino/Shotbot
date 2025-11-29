# Shotbot DCC Launch System - Comprehensive Exploration

## Overview
The Shotbot launch system consists of three main layers:
1. **UI Layer** (launcher_panel.py) - Visual launch cards and quick launch buttons
2. **Control Layer** (controllers/launcher_controller.py) - Coordination and options handling
3. **Execution Layer** (command_launcher.py) - Actual DCC application launching

---

## 1. Launch Block Widgets (Colored DCC Launch Cards)

### Main Widget: `AppLauncherSection` (launcher_panel.py:59-383)
**Purpose**: Individual colored launch card for one DCC application (3DE, Maya, Nuke, RV)

#### Structure:
```
AppLauncherSection (QWidget + QtWidgetMixin)
├── Header Section (expand button + app name + shortcut badge)
│   ├── expand_button (QToolButton) - Toggle expand/collapse
│   ├── name_label (QLabel) - App name (3DE, Nuke, Maya, RV)
│   └── shortcut_badge (QLabel) - Shows keyboard shortcut key
├── Launch Button (large colored button)
│   └── launch_button (QPushButton) - Main launch button
└── Content Section (collapsed by default, expands on click)
    ├── Checkboxes (optional launch options)
    │   └── Multiple QCheckBox with labels & tooltips
    └── Plate Selector (QComboBox for selecting plate version)
```

#### Key Attributes:
- `config: AppConfig` - Configuration dataclass with:
  - `name: str` - App identifier ("3de", "nuke", "maya", "rv", "publish")
  - `command: str` - Command to execute
  - `icon: str` - Emoji icon
  - `color: str` - Hex color like "#2b4d6f"
  - `tooltip: str` - Hover text
  - `shortcut: str` - Keyboard shortcut ("3", "N", "M", "R", "P")
  - `checkboxes: list[CheckboxConfig]` - Launch options
  
- `is_expanded: bool` - Tracks collapse/expand state
- `checkboxes: dict` - Maps checkbox keys to QCheckBox widgets
- `plate_selector: QComboBox | None` - For selecting plate version
- `_launch_in_progress: bool` - Disable button during launch

#### Visual Design:
The launch button uses color themes with hover effects:
- Base color is set from `AppConfig.color`
- Hover: Lightened version (+20% brightness)
- Pressed: Darkened version (-20% brightness)
- Disabled: Desaturated

#### Color Mapping (launcher_panel.py:500-571):
```python
# 3DE
config = AppConfig(
    name="3de",
    color="#2b4d6f",  # Deep blue
    shortcut="3",
    ...
)

# Nuke
config = AppConfig(
    name="nuke",
    color="#5d4d2b",  # Brown/tan
    shortcut="N",
    ...
)

# Maya
config = AppConfig(
    name="maya",
    color="#4d2b5d",  # Purple
    shortcut="M",
    ...
)

# RV (Review)
config = AppConfig(
    name="rv",
    color="#2b5d4d",  # Teal
    shortcut="R",
    ...
)

# Publish (custom launcher)
color="#5d2b2b"  # Dark red
```

#### Launch Option Checkboxes:
Each app has different options:

**3DE**:
- "Include raw plate" (key: "include_raw_plate")
- "Open latest 3DE" (key: "open_latest_threede")

**Nuke**:
- "Include raw plate" (key: "include_raw_plate")
- "Create new script" (key: "create_new_file")

**Maya**:
- "Include raw plate" (key: "include_raw_plate")
- "Open latest Maya" (key: "open_latest_maya")

**RV**:
- "Include raw plate" (key: "include_raw_plate")

### Container Widget: `LauncherPanel` (launcher_panel.py:386-772)
**Purpose**: Main panel containing all launch cards

#### Structure:
```
LauncherPanel (QWidget + QtWidgetMixin)
├── Quick Launch Row (fast access bar at top)
│   ├── Label: "Quick Launch"
│   └── Buttons: [3], [N], [M], [R], [P]
│       └── Each with emoji icon + keyboard shortcut
├── Launch Cards Grid (scrollable)
│   ├── AppLauncherSection (3DE)
│   ├── AppLauncherSection (Nuke)
│   ├── AppLauncherSection (Maya)
│   ├── AppLauncherSection (RV)
│   └── (2x2 grid layout)
└── Custom Launchers Section (below grid)
    └── Custom launcher buttons (added dynamically)
```

#### Key Attributes:
- `app_sections: dict[str, AppLauncherSection]` - Maps app name to widget
- `_quick_buttons: dict[str, QPushButton]` - Quick launch buttons
- `_current_shot: Shot | None` - Current selected shot
- `custom_launcher_buttons: dict[str, QPushButton]` - Dynamic launcher buttons
- `custom_launcher_container: QWidget` - Container for custom launchers

#### Signals:
- `app_launch_requested(app_name: str, shot: Shot)` - Emitted when launch button clicked
- `custom_launcher_requested(launcher_id: str)` - Emitted for custom launchers

---

## 2. Quick Launch Row Implementation

### Quick Launch Buttons (launcher_panel.py:461-495)
Located at top of LauncherPanel above the grid cards.

#### Structure:
```
Quick Launch Row:
┌─────────────────────────────────────────────┐
│ Quick Launch  [3] [N] [M] [R] [P]           │
│               3DE Nuke Maya RV Publish      │
└─────────────────────────────────────────────┘
```

#### Button Definition (lines 463-466):
```python
quick_apps = [
    ("3de", "🎬", "#2b4d6f"),    # 3DE: Film emoji, blue
    ("nuke", "🎨", "#5d4d2b"),   # Nuke: Artist palette, brown
    ("maya", "🎭", "#4d2b5d"),   # Maya: Theater masks, purple
    ("rv", "📽️", "#2b5d4d"),     # RV: Film reel, teal
]
```

#### Visual Styling (launcher_panel.py:468-495):
```python
btn = QPushButton(icon, "")  # Icon only
btn.setFixedSize(48, 48)     # Square button
btn.setStyleSheet(f"""
    QPushButton {{
        background-color: {color};
        ...
        border-radius: 4px;
    }}
    QPushButton:hover {{
        background-color: {lighter_color};
    }}
    ...
""")
btn.setToolTip(f"Press '{app_name.upper()}' to launch {app_name}")
btn.clicked.connect(lambda: self._on_quick_launch(app_name))
```

#### Signal Handler (_on_quick_launch, lines 683-692):
```python
def _on_quick_launch(self, app_name: str) -> None:
    """Quick launch with current shot (no options dialog)."""
    if self._current_shot is None:
        return
    # Emit with currently selected shot
    self.app_launch_requested.emit(app_name, self._current_shot)
```

---

## 3. Launch Context & Options Handling

### LaunchContext Dataclass (command_launcher.py:42-63)
Encapsulates all launch options passed to CommandLauncher.

```python
@dataclass
class LaunchContext:
    """Context for launching an application with optional parameters."""
    
    # Launch options
    include_raw_plate: bool = False        # Include raw plate footage
    open_latest_threede: bool = False      # Open latest 3DE scene
    open_latest_maya: bool = False         # Open latest Maya scene
    open_latest_scene: bool = False        # Open latest generic scene
    create_new_file: bool = False          # Create new file (Nuke)
    selected_plate: str | None = None      # Which plate to use
```

### Options Collection Flow:

#### 1. LauncherController.get_launch_options() (lines 188-215)
Retrieves checkbox states from AppLauncherSection:
```python
def get_launch_options(self, app_name: str) -> dict[str, bool]:
    """Get current checkbox states for app."""
    section = self.window.launcher_panel.app_sections.get(app_name)
    if section:
        return section.get_checkbox_states()
    return {}
```

#### 2. LauncherController._build_launch_options() (lines 243-290)
Converts checkbox states + plate selection into LaunchContext:
```python
options = {
    "include_raw_plate": checkbox_states.get("include_raw_plate", False),
    "open_latest_threede": checkbox_states.get("open_latest_threede", False),
    "open_latest_maya": checkbox_states.get("open_latest_maya", False),
    "open_latest_scene": checkbox_states.get("open_latest_scene", False),
    "create_new_file": checkbox_states.get("create_new_file", False),
    "selected_plate": plate_text if plate_text != "Default" else None,
}
context = LaunchContext(**options)
```

#### 3. Plate Selection (AppLauncherSection.set_available_plates, lines 355-371)
```python
def set_available_plates(self, plates: list[str]) -> None:
    """Update available plate options in dropdown."""
    if self.plate_selector:
        self.plate_selector.clear()
        self.plate_selector.addItems(["Default"] + plates)
```

---

## 4. Keyboard Shortcut Implementation

### BaseGridView.keyPressEvent (base_grid_view.py:428-451)
Global keyboard shortcut handler for all grid views.

```python
def keyPressEvent(self, event: QKeyEvent) -> None:
    """Handle keyboard shortcuts (3, N, M, R, P)."""
    
    key_map = {
        Qt.Key.Key_3: "3de",
        Qt.Key.Key_N: "nuke",
        Qt.Key.Key_M: "maya",
        Qt.Key.Key_R: "rv",
        Qt.Key.Key_P: "publish",
    }
    
    key = Qt.Key(event.key())
    if key in key_map:
        self.app_launch_requested.emit(key_map[key])
        event.accept()
    else:
        self.list_view.keyPressEvent(event)  # Default navigation
```

### Shortcut Display in UI:
1. **Shortcut Badge** - Shown on AppLauncherSection header (launcher_panel.py:119-130):
   ```python
   if self.config.shortcut:
       shortcut_badge = QLabel(self.config.shortcut.upper())
       shortcut_badge.setStyleSheet("""
           background-color: #333;
           color: #888;
           padding: 2px 6px;
           border-radius: 3px;
       """)
       shortcut_badge.setToolTip(f"Press '{self.config.shortcut.upper()}' to launch")
   ```

2. **Quick Launch Buttons** - Shows shortcut in tooltip and visual placement

3. **Hint Text** - LauncherPanel displays hint (launcher_panel.py:441):
   ```python
   hint_label = QLabel("Tip: Double-click a scene or use shortcuts (3, N, M, R, P)")
   ```

### Shortcut Binding:
- No explicit QShortcut used - relies on keyPressEvent in grid views
- Shortcuts work when grid view has focus
- All views inherit from BaseGridView, so all have shortcuts

---

## 5. Launch Command Execution Flow

### Signal Flow:
```
1. User clicks launch button (or presses keyboard shortcut)
   ↓
2. AppLauncherSection/BaseGridView emits app_launch_requested(app_name, shot)
   ↓
3. LauncherPanel emits app_launch_requested signal
   ↓
4. MainWindow catches signal via LauncherController
   ↓
5. LauncherController.launch_app(app_name, shot)
   ↓
6. CommandLauncher.launch_app(app_name, context)
   ↓
7. New terminal window opens with command
```

### LauncherController.launch_app (lines 315-378)
Main entry point from UI.

```python
def launch_app(self, app_name: str, captured_shot: Shot | None = None) -> None:
    """Launch application with shot context."""
    
    # Determine effective shot
    effective_shot = captured_shot or self._current_shot
    if not effective_shot:
        return
    
    # Set current shot in CommandLauncher
    self.launcher.set_current_shot(effective_shot)
    
    # Build launch options from checkboxes
    options = self.get_launch_options(app_name)
    
    # Execute with options
    self._execute_launch_with_options(app_name, options)
```

### LauncherController._execute_launch_with_options (lines 292-313)
Builds LaunchContext and calls CommandLauncher.

```python
def _execute_launch_with_options(
    self, app_name: str, options: dict[str, bool]
) -> None:
    """Build LaunchContext and launch."""
    
    context = LaunchContext(
        include_raw_plate=options.get("include_raw_plate", False),
        open_latest_threede=options.get("open_latest_threede", False),
        open_latest_maya=options.get("open_latest_maya", False),
        open_latest_scene=options.get("open_latest_scene", False),
        create_new_file=options.get("create_new_file", False),
        selected_plate=options.get("selected_plate"),
    )
    
    # Launch with context
    self.launcher.launch_app_with_scene_context(app_name, context)
```

### CommandLauncher.launch_app (command_launcher.py:385-614)
Actual DCC application launching.

```python
def launch_app(
    self, app_name: str, context: LaunchContext | None = None
) -> None:
    """Launch application with shot context.
    
    Args:
        app_name: "3de", "nuke", "maya", "rv", etc.
        context: Launch options (plates, scene opening, etc.)
    """
    
    # Build launch command based on app_name + context
    # Handle app-specific setup (Nuke environment, scene opening, etc.)
    # Validate workspace
    # Launch in new terminal window
    # Connect signal handlers for progress/errors
```

### Terminal Launch (_launch_in_new_terminal, lines 306-366)
Actually spawns the new terminal window:

```python
def _launch_in_new_terminal(self, command: str) -> None:
    """Launch command in new GNOME terminal window."""
    
    # Build full terminal command
    terminal_cmd = f"gnome-terminal -- bash -ilc '{command}'"
    
    # Execute via ProcessPoolManager (manages session pool)
    self.process_executor.execute(terminal_cmd)
```

---

## 6. Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                      PRESENTATION LAYER                  │
│  MainWindow.launcher_panel (LauncherPanel)              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Quick Launch Row      │  Grid of AppLauncherSections   │
│  [3] [N] [M] [R] [P]   │  ┌──────────┬──────────┐       │
│                        │  │  3DE     │  Nuke    │       │
│                        │  │ [Launch] │ [Launch] │       │
│                        │  ├──────────┼──────────┤       │
│                        │  │  Maya    │  RV      │       │
│                        │  │ [Launch] │ [Launch] │       │
│                        │  └──────────┴──────────┘       │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  Signals: app_launch_requested(app_name, shot)          │
│           custom_launcher_requested(launcher_id)        │
└─────────────────────────────────────────────────────────┘
              │
              ↓ connects to
┌─────────────────────────────────────────────────────────┐
│                 CONTROLLER LAYER                         │
│           LauncherController                            │
├─────────────────────────────────────────────────────────┤
│ - get_launch_options(app_name) → dict[str, bool]        │
│ - _build_launch_options() → LaunchContext               │
│ - launch_app(app_name, shot) → delegates to             │
│   CommandLauncher.launch_app()                          │
└─────────────────────────────────────────────────────────┘
              │
              ↓
┌─────────────────────────────────────────────────────────┐
│                  EXECUTION LAYER                         │
│              CommandLauncher                            │
├─────────────────────────────────────────────────────────┤
│ launch_app(app_name, context: LaunchContext)            │
│  ├─ Validate workspace                                  │
│  ├─ Handle app-specific setup (Nuke, Maya, etc.)        │
│  ├─ Open latest scenes if requested                     │
│  ├─ Include raw plates if requested                     │
│  └─ _launch_in_new_terminal(command)                    │
│      └─ ProcessPoolManager.execute()                    │
│          └─ GNOME Terminal spawned                      │
└─────────────────────────────────────────────────────────┘
```

---

## 7. Key Files and Locations

| File | Purpose |
|------|---------|
| `/home/gabrielh/projects/shotbot/launcher_panel.py` | UI: LauncherPanel + AppLauncherSection + quick launch buttons |
| `/home/gabrielh/projects/shotbot/controllers/launcher_controller.py` | Control: Options collection + launch coordination |
| `/home/gabrielh/projects/shotbot/command_launcher.py` | Execution: DCC application spawning + command building |
| `/home/gabrielh/projects/shotbot/base_grid_view.py` | Keyboard shortcut handling (keyPressEvent) |
| `/home/gabrielh/projects/shotbot/main_window.py` | Main orchestrator: connects all signals |

---

## 8. Configuration Structure

### AppConfig Dataclass (launcher_panel.py:34-45)
```python
@dataclass
class AppConfig:
    """Configuration for a launchable application."""
    name: str              # "3de", "nuke", "maya", "rv"
    command: str           # Command to execute
    icon: str              # Emoji icon
    color: str             # Hex color
    tooltip: str           # Hover text
    shortcut: str = ""     # Keyboard shortcut key
    checkboxes: list[CheckboxConfig] = field(default_factory=list)
```

### CheckboxConfig Dataclass (launcher_panel.py:48-56)
```python
@dataclass
class CheckboxConfig:
    """Configuration for a checkbox option."""
    label: str             # Display label
    tooltip: str           # Hover tooltip
    key: str               # Storage key
    default: bool = False  # Default state
```

---

## 9. Launch Options Summary

### How Options Flow Through System:
1. **UI Collection**: AppLauncherSection checkboxes → get_checkbox_states()
2. **Conversion**: LauncherController._build_launch_options() → LaunchContext
3. **Passing**: LaunchContext passed to CommandLauncher.launch_app()
4. **Usage**: CommandLauncher interprets context and modifies command/behavior

### Example: Including Raw Plate
```python
# User clicks checkbox "Include raw plate"
checkbox.setChecked(True)

# get_checkbox_state retrieves: {"include_raw_plate": True}

# LaunchContext created: LaunchContext(include_raw_plate=True, ...)

# CommandLauncher interprets and adds raw plate path to command:
# command = "nuke /path/to/raw_plate.mov /path/to/script.nk"
```

---

## Summary of Key Findings

1. **3 Main Widget Classes**:
   - `AppLauncherSection` - Individual colored DCC card
   - `LauncherPanel` - Container with quick launch row + grid
   - Quick launch buttons (inline in LauncherPanel)

2. **Color System**:
   - Each DCC has fixed hex color (3DE: #2b4d6f, Nuke: #5d4d2b, etc.)
   - Colors lightened/darkened for hover/pressed states
   - Applied via Qt stylesheets

3. **Keyboard Shortcuts**:
   - Global handler in BaseGridView.keyPressEvent()
   - Maps Qt.Key.Key_3/N/M/R/P to app names
   - Displayed in shortcut badges and tooltips

4. **Launch Options**:
   - Checkboxes per app (Include plate, Open latest scene, etc.)
   - Collected into AppLauncherSection.get_checkbox_states()
   - Converted to LaunchContext dataclass
   - Passed through CommandLauncher for app-specific behavior

5. **Execution Path**:
   - UI click → app_launch_requested signal
   - LauncherController catches signal
   - Gets options from AppLauncherSection
   - Builds LaunchContext
   - Calls CommandLauncher.launch_app()
   - Opens new terminal with command
