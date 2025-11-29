# Files Section & Plate Space Implementation - Complete Exploration

## Executive Summary

The Files section has been **fully integrated** with the Launch system as of commit 475ba4e. Users can now:
1. Click on any file in the Files section to set it as the default for that DCC
2. An arrow indicator (->) marks the currently selected file
3. The selected file is passed through the launch chain to CommandLauncher
4. Each DCC maintains independent file selection state

---

## 1. FILE SELECTION STATE MANAGEMENT

### Per-DCC Selected Files Storage

**Location**: `right_panel.py` lines 74-79

```python
# Per-DCC selected file state (user clicks file row to set)
self._selected_files: dict[str, SceneFile | None] = {
    "3de": None,
    "nuke": None,
    "maya": None,
}
```

**Key Properties**:
- Stores one selected file per DCC app
- Initialized to None for each DCC
- Updated when user single-clicks a file row in Files section
- Cleared when shot changes (line 295 in right_panel.py)
- Per-DCC independence: selecting a 3DE file doesn't affect Maya selection

### State Lifecycle

1. **Initialization**: All DCCs start with `None` (no file selected)
2. **User Click**: Single-click on file row calls `_on_file_selected(scene_file)`
3. **Storage**: File stored in `_selected_files[app_name]`
4. **Visual Update**: Arrow indicator displayed in Files table
5. **Launch Time**: Selected file passed to LauncherController
6. **Shot Change**: All selections cleared (line 295)

---

## 2. FILE SELECTION UI COMPONENTS

### Files Section Container

**File**: `files_section.py` (133 lines)

**Class**: `FilesSection` - Collapsible wrapper

```python
class FilesSection(QtWidgetMixin, QWidget):
    # Signals
    file_selected = Signal(object)        # SceneFile clicked
    file_open_requested = Signal(object)  # SceneFile double-clicked
    expanded_changed = Signal(bool)       # Section collapsed/expanded
```

**Key Methods**:
- `set_files(dict[FileType, list[SceneFile]])` - Set files by type
- `get_selected_file() -> SceneFile | None` - Get currently selected
- `set_current_tab(FileType)` - Switch to specific tab
- `set_default_file(SceneFile)` - Mark file with arrow indicator (line 429 in files_tab_widget.py)

### FilesTabWidget - Tabbed Tables

**File**: `files_tab_widget.py` (438 lines)

**Class**: `FilesTabWidget` - Manages three tables (3DE, Maya, Nuke)

```python
class FilesTabWidget(QtWidgetMixin, QWidget):
    # Signals
    file_selected = Signal(object)        # Single-click
    file_open_requested = Signal(object)  # Double-click
    
    # Attributes
    _tables: dict[FileType, QTableWidget]
    _models: dict[FileType, FileTableModel]
    _tab_indices: dict[FileType, int]
```

**Table Structure**:
- Column 0: Version (with arrow indicator if default)
- Column 1: Age (relative time like "2 hours ago")
- Column 2: User (file creator)
- Additional columns: File type display

### FileTableModel - Data & Display

**File**: `files_tab_widget.py` (37-177)

**Class**: `FileTableModel(QAbstractTableModel)`

```python
class FileTableModel(QAbstractTableModel):
    COLUMNS = ("Version", "Age", "User")
    
    def set_current_default(self, file: SceneFile | None) -> None:
        """Mark file as default with arrow indicator."""
        if file and file in self._files:
            self._current_default = file
            row = self._files.index(file)
            self._refresh_row_for_file(row)
```

**Visual Indicator**:
- Arrow (`->`) prepended to version string for selected file (line 164)
- Example: `"-> v005"` instead of just `"v005"`
- Updated via `set_current_default()` method
- Cleared by passing `None`

---

## 3. PER-DCC FILE SELECTION FLOW

### User Interaction → File Selection

**Step 1: User Clicks File**

File: `files_tab_widget.py` lines 332-343

```python
def _on_row_clicked(self, index: QModelIndex) -> None:
    """Handle single-click on file row."""
    scene_file = self._model.get_file(index.row())
    if scene_file:
        self.file_selected.emit(scene_file)  # Signal emitted
```

**Step 2: RightPanelWidget Handles Selection**

File: `right_panel.py` lines 224-233

```python
def _on_file_selected(self, scene_file: SceneFile) -> None:
    """Handle user clicking a file row - set as default for that DCC."""
    app_name = self._file_type_to_app(scene_file.file_type)
    if app_name:
        self._selected_files[app_name] = scene_file
        self._update_default_indicators(app_name, scene_file)
```

**Mapping Function**: `_file_type_to_app()`

File: `right_panel.py` lines 235-248

```python
def _file_type_to_app(self, file_type: FileType) -> str | None:
    """Map FileType to app name."""
    mapping = {
        FileType.THREEDE: "3de",
        FileType.MAYA: "maya",
        FileType.NUKE: "nuke",
    }
    return mapping.get(file_type)
```

**Step 3: Visual Indicator Update**

File: `right_panel.py` lines 250-281

```python
def _update_default_indicators(self, app_name: str, scene_file: SceneFile) -> None:
    """Update UI to show selected file with arrow."""
    # Switch to correct tab
    self._files_section.set_current_tab(scene_file.file_type)
    
    # Set default indicator (arrow) in Files table
    self._files_section.set_default_file(scene_file)
    
    # Update DCC section with file info
    dcc_section = self._dcc_accordion.get_section(app_name)
    if dcc_section and scene_file:
        version_str = scene_file.name  # or extract version
        dcc_section.set_opening_file(version_str)
```

---

## 4. FILE SELECTION DURING LAUNCH

### Launch Flow with Selected File

**Entry Point**: User presses shortcut or clicks launch button

File: `right_panel.py` lines 187-222

```python
def _on_dcc_launch(self, app_name: str) -> None:
    """Handle DCC launch from accordion."""
    if not self._current_shot:
        return
    
    # Get selected file for this DCC
    selected_file = self._selected_files.get(app_name)
    
    if selected_file:
        # Launch with selected file
        self.launch_requested.emit(app_name, 
                                  {"selected_file": selected_file})
    else:
        # Normal launch (no selected file)
        self.launch_requested.emit(app_name, {})
```

### LauncherController Integration

File: `controllers/launcher_controller.py` lines 417-448

```python
def _launch_with_selected_file(
    self, app_name: str, scene_file: SceneFile
) -> bool:
    """Launch an application with a user-selected file."""
    
    if not self._current_shot:
        return False
    
    workspace_path = self._current_shot.workspace_path
    file_path = Path(scene_file.path)
    
    # Pass to CommandLauncher
    if self.window.command_launcher.launch_with_file(
        app_name, file_path, workspace_path
    ):
        self.window.update_status(
            f"Launched {app_name} with {scene_file.name}"
        )
        return True
    return False
```

---

## 5. DATA STRUCTURES FOR PLATE SPACES

### SceneFile Dataclass

File: `scene_file.py` lines 41-114

```python
@dataclass(frozen=True, slots=True)
class SceneFile:
    """Immutable scene file representation."""
    
    path: Path                  # Full file path
    file_type: FileType         # 3DE, Maya, or Nuke
    modified_time: datetime     # Last modified
    user: str                   # Creator username
    version: int | None = None  # Version number (optional)
    
    @property
    def app_name(self) -> str:
        """Return app name for launching."""
        return _FILE_TYPE_TO_APP[self.file_type]
    
    @property
    def name(self) -> str:
        """Return just the filename."""
        return self.path.name
    
    @property
    def display_name(self) -> str:
        """Return display name: '3DEqualizer', 'Maya', 'Nuke'."""
        return _FILE_TYPE_TO_DISPLAY[self.file_type]
    
    @property
    def relative_age(self) -> str:
        """Return human-readable age like '2 hours ago'."""
        # ... calculation logic
        
    @property
    def color(self) -> str:
        """Return color for this file type."""
        return FILE_TYPE_COLORS[self.file_type]
```

### FileType Enum

File: `scene_file.py` lines 11-23

```python
class FileType(Enum):
    """Supported file types."""
    THREEDE = auto()
    MAYA = auto()
    NUKE = auto()

# Mapping to app names
_FILE_TYPE_TO_APP: dict[FileType, str] = {
    FileType.THREEDE: "3de",
    FileType.MAYA: "maya",
    FileType.NUKE: "nuke",
}

# Mapping to display names
_FILE_TYPE_TO_DISPLAY: dict[FileType, str] = {
    FileType.THREEDE: "3DEqualizer",
    FileType.MAYA: "Maya",
    FileType.NUKE: "Nuke",
}

# Colors for visual display
FILE_TYPE_COLORS: dict[FileType, str] = {
    FileType.THREEDE: "#c0392b",  # Red
    FileType.MAYA: "#16a085",     # Teal
    FileType.NUKE: "#d35400",     # Orange
}
```

---

## 6. PRE-SELECTION LOGIC (CURRENTLY IMPLEMENTED)

### Auto-Selection of Latest File

**Current Behavior**:
- Files are sorted by version (highest first)
- No automatic selection happens
- User must click to select

**To Auto-Select Latest Version**:

Would add to `right_panel.py` `set_files()` method (line 319):

```python
def set_files(self, files_by_type: dict[FileType, list[SceneFile]]) -> None:
    """Set files for display and optionally auto-select latest."""
    
    self._files_section.set_files(files_by_type)
    
    # Optional: Auto-select latest for each DCC
    for file_type, files in files_by_type.items():
        if files:
            app_name = self._file_type_to_app(file_type)
            if app_name:
                # Auto-select the first (latest by version)
                latest_file = files[0]
                self._selected_files[app_name] = latest_file
                
                # Update visual indicator
                self._update_default_indicators(app_name, latest_file)
```

### Shot Change Clears Selections

File: `right_panel.py` lines 283-317

```python
def set_shot(self, shot: Shot, skip_dcc_update: bool = False) -> None:
    """Set the current shot and clear file selections."""
    
    self._current_shot = shot
    
    # Clear previous selections when shot changes
    self._selected_files = {
        "3de": None,
        "nuke": None,
        "maya": None,
    }
    
    # ... rest of initialization
```

---

## 7. KEY FILES SUMMARY

| File | Class | Purpose | Key Method |
|------|-------|---------|-----------|
| `right_panel.py` | `RightPanelWidget` | Coordinates Files + Launch | `_on_file_selected()`, `get_dcc_options()` |
| `files_section.py` | `FilesSection` | Collapsible file wrapper | `set_files()`, `set_default_file()` |
| `files_tab_widget.py` | `FilesTabWidget` | Tabbed file tables | `set_files()`, `set_default_file()` |
| `files_tab_widget.py` | `FileTableModel` | Table data + display | `set_current_default()` |
| `scene_file.py` | `SceneFile` | File data | N/A (dataclass) |
| `controllers/launcher_controller.py` | `LauncherController` | Launch coordination | `_launch_with_selected_file()` |

---

## 8. ARCHITECTURAL FLOW DIAGRAM

```
┌─────────────────────────────────────────────────┐
│          RightPanelWidget                       │
│  (Coordinates Files + Launch)                   │
│                                                 │
│  _selected_files: dict[str, SceneFile | None] │
│  {                                              │
│      "3de": <SceneFile>,   ← User selected     │
│      "nuke": None,                             │
│      "maya": <SceneFile>   ← User selected     │
│  }                                              │
└────────────┬─────────────────────┬──────────────┘
             │                     │
             ↓                     ↓
  ┌──────────────────┐   ┌─────────────────────┐
  │ FilesSection     │   │ DCCAccordion        │
  │  (display)       │   │  (launch buttons)   │
  │                  │   │                     │
  │ Tabs:            │   │ Sections:           │
  │ • 3DE (table)    │ ← │ • 3DE section       │
  │ • Maya (table)   │   │ • Nuke section      │
  │ • Nuke (table)   │   │ • Maya section      │
  │                  │   │                     │
  │ [-> v005] 2h ago │   │ [Launch 3DE] btn    │
  │ [   v004] 5h ago │   │                     │
  └────────┬─────────┘   └──────┬──────────────┘
           │                    │
           │                    │
      Click file ────→ _on_file_selected()
           │            │
           │            ↓
           │      Store in _selected_files["3de"]
           │      Update arrow indicator
           │      Set DCC section info
           │
           └─────────────────→ User clicks [Launch]
                              │
                              ↓
                      Launch chain gets
                      selected_file from
                      _selected_files["3de"]
                              │
                              ↓
                      LauncherController
                              │
                              ↓
                      CommandLauncher.launch_with_file()
```

---

## 9. VERSION SORTING & SELECTION

### Version Handling

File: `version_mixin.py` (339 lines)

**Available Methods**:
- `_extract_version(filename)` - Parse version from filename
- `_find_latest_by_version(files)` - Get highest version
- `_sort_files_by_version(files)` - Sort by version (descending)
- `_group_files_by_version(files)` - Group by major version
- `_filter_by_version_range(files, min, max)` - Filter versions

**Current Usage**:
- Files sorted descending (latest first) in table display
- Highest version appears at row 0
- User can click any row to select (not just latest)

**For Pre-Selection**:
- `files[0]` after sorting = latest version
- Check `SceneFile.version` property if numeric version exists
- Or use `scene_file.name` for filename-based version

---

## 10. SIGNAL CONNECTIONS

### FilesSection Signals → RightPanelWidget Slots

File: `right_panel.py` lines 163-185

```python
def _connect_signals(self) -> None:
    """Connect child widget signals."""
    
    # Files section
    self._files_section.file_selected.connect(self._on_file_selected)
    self._files_section.file_open_requested.connect(
        self.file_open_requested.emit
    )
    
    # DCC accordion
    self._dcc_accordion.launch_requested.connect(self._on_dcc_launch)
    
    # Quick launch
    self._quick_launch.launch_requested.connect(self._on_quick_launch)
```

### Launch Flow

```
User clicks file
    ↓
FilesSection.file_selected signal emitted
    ↓
RightPanelWidget._on_file_selected() called
    ↓
Store in _selected_files[app_name]
    ↓
Update visual indicator (_update_default_indicators)
    ↓
User clicks [Launch]
    ↓
RightPanelWidget._on_dcc_launch() called
    ↓
RightPanelWidget.launch_requested signal emitted with selected_file
    ↓
LauncherController._on_launch_requested() catches signal
    ↓
LauncherController._launch_with_selected_file() executes
    ↓
CommandLauncher.launch_with_file(app_name, file_path, workspace)
```

---

## 11. INTEGRATION POINTS FOR ENHANCEMENTS

### 1. Auto-Selection of Latest File
**Where**: `RightPanelWidget.set_files()` (line 319)
**What**: After setting files, auto-select `files[0]` for each type
**Effect**: First (latest) file would be marked with arrow on load

### 2. Persistent Selection Across Sessions
**Where**: `SettingsManager` integration in `RightPanelWidget`
**What**: Save selected file paths to settings.json per shot
**Effect**: Remember user's last selection when returning to shot

### 3. Per-DCC Version Pinning
**Where**: `LaunchContext` dataclass in `command_launcher.py`
**What**: Add `pinned_version: dict[str, str]` field
**Effect**: Store user's preferred version per DCC globally

### 4. "Open Latest" checkbox auto-set
**Where**: `DCCAccordion` when file selected
**What**: Auto-check "Open latest" checkboxes when file selected
**Effect**: Eliminate separate file + option click steps

---

## Summary

The Files section **is fully integrated** with the Launch system:
- ✅ Per-DCC file selection tracking in `_selected_files` dict
- ✅ Single-click sets file as default for that DCC
- ✅ Arrow indicator (`->`) shows selected file in table
- ✅ Selected file passed through launch chain
- ✅ Selection cleared when shot changes
- ✅ Each DCC maintains independent selection
- ✅ Data flows through signals properly

**Key Files**:
- State management: `right_panel.py` (_selected_files dict)
- UI display: `files_tab_widget.py` (FileTableModel with arrow)
- Data model: `scene_file.py` (SceneFile dataclass)
- Launch integration: `controllers/launcher_controller.py` (_launch_with_selected_file)
