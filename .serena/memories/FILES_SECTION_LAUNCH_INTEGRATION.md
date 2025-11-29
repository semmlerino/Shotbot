# Files Section & Launch System Integration Analysis

## Executive Summary

The Files section is a **read-only UI component** showing version history of scene files (3DE, Maya, Nuke) by file type. It currently has **NO INTEGRATION** with the Launch system. Selection functionality exists in the UI but is not connected to launcher operations.

---

## 1. FILES SECTION IMPLEMENTATION LOCATION

### Primary Files:
1. **`files_section.py`** (133 lines)
   - Main container class: `FilesSection`
   - Wraps `FilesTabWidget` in a `CollapsibleSection`
   - Shows file count in header when collapsed
   - Signals: `file_selected`, `file_open_requested`, `expanded_changed`

2. **`files_tab_widget.py`** (394 lines)
   - `FileTableModel` - QAbstractTableModel for table display
   - `FilesTabWidget` - Tabbed interface with 3 tables (one per file type)
   - Each table shows: Version, Age, User columns
   - Signals: `file_selected` (single-click), `file_open_requested` (double-click)

3. **`shot_files_panel.py`** (357 lines) - DEPRECATED
   - Old implementation with inline file display
   - Contains: `FileListItem`, `FileTypeSection`, `ShotFilesPanel`
   - Used expandable sections instead of tabs
   - No longer in active use (replaced by new files_section.py approach)

### Hierarchy:
```
RightPanelWidget (right_panel.py)
├── ShotInfoPanel (top)
│   ├── Thumbnail + Shot info
│   └── [OLD: ShotFilesPanel - DEPRECATED]
├── FilesSection (NEW - replaces ShotFilesPanel)
│   └── CollapsibleSection (collapsible_section.py)
│       └── FilesTabWidget
│           ├── Table for 3DE files
│           ├── Table for Maya files
│           └── Table for Nuke files
├── LauncherPanel (middle)
│   ├── Quick Launch buttons [3] [N] [M] [R] [P]
│   └── App cards (3DE, Nuke, Maya, RV launch buttons)
└── LogViewer (bottom)
```

---

## 2. COLLAPSIBLE HEADER IMPLEMENTATION

### Location: `files_section.py` lines 56-58

```python
self._section = CollapsibleSection(title, expanded=expanded, parent=self)
_ = self._section.expanded_changed.connect(self.expanded_changed)
self._section.set_content(self._files_tab)
```

**CollapsibleSection Class** (from `collapsible_section.py`):
- Has expand/collapse button
- Shows title with optional count badge
- Count updated via `set_count(count)` method (line 94)
- Expanded state persisted (line 57, 98-104)

### Header Display:
- Default: Collapsed, showing "Files (24)" when files present
- When expanded: Shows full tabbed interface
- Expansion state tracked and restored between sessions

---

## 3. CURRENT RELATIONSHIP TO LAUNCH FUNCTIONALITY

### **CURRENTLY NOT INTEGRATED** - Key Finding:

1. **File Selection Available But Unused**:
   - `FilesSection.get_selected_file()` → returns SceneFile or None
   - `FilesTabWidget` emits `file_selected` and `file_open_requested` signals
   - No connections to launcher in current codebase

2. **Launch System Components** (separate from Files):
   - `LauncherPanel` - buttons for launching apps
   - `LauncherController` - coordinates launch actions
   - `CommandLauncher` - executes actual launches
   - **None of these check or use selected file from FilesSection**

3. **Current Launch Flow**:
   ```
   Click launch button → LauncherPanel.app_launch_requested signal
                    ↓
   LauncherController.launch_app(app_name, shot)
                    ↓
   CommandLauncher.launch_app(app_name, context)
   
   (Note: NO file selection involved)
   ```

---

## 4. WHAT HAPPENS ON FILE SELECTION (Current Behavior)

### Single-Click (Select):
- Line `files_tab_widget.py:299-310` - `_on_row_clicked()`
- Emits `file_selected` signal with SceneFile object
- Currently unconnected - no handler

### Double-Click (Open):
- Line `files_tab_widget.py:312-323` - `_on_row_double_clicked()`
- Emits `file_open_requested` signal with SceneFile object
- Currently unconnected - no handler
- (Would likely open file in external application if connected)

### No "Default" Version Concept:
- Files are displayed in order (via `VersionHandlingMixin._sort_files_by_version()`)
- Latest version would be at top (line 165-210 in version_mixin.py)
- But no explicit "default" or "selected" marking in UI

---

## 5. SIGNALS & API AVAILABLE FOR LAUNCH INTEGRATION

### FilesSection Signals:
```python
file_selected = Signal(object)        # SceneFile clicked
file_open_requested = Signal(object)  # SceneFile double-clicked
expanded_changed = Signal(bool)       # Section collapsed/expanded
```

### FilesSection Methods:
```python
get_selected_file() → SceneFile | None    # Get current selection
get_total_file_count() → int              # Total files across all types
set_files(dict[FileType, list])           # Set files by type
set_current_tab(FileType)                 # Switch to specific tab
is_expanded() → bool                      # Check if expanded
set_expanded(bool)                        # Show/hide section
```

### SceneFile Object (from `scene_file.py`):
```python
@dataclass
class SceneFile:
    path: str                    # Full file path
    file_type: FileType          # 3DE, Maya, or Nuke
    version: str                 # Version number
    user: str                    # Creator username
    modified_date: datetime      # Last modified
```

---

## 6. VERSION HANDLING (VersionHandlingMixin)

### Location: `version_mixin.py` (339 lines)

**Capabilities** (methods available for sorting/filtering):
- `_extract_version(filename)` - Parse version from filename
- `_find_latest_by_version(files)` - Get highest version number
- `_find_earliest_by_version(files)` - Get lowest version number
- `_sort_files_by_version(files)` - Sort ascending/descending
- `_group_files_by_version(files)` - Group by major version
- `_filter_by_version_range(files, min, max)` - Filter to range
- `_find_next_version(current_version)` - Calculate next version

**Currently Used**:
- Files are sorted by version for table display
- Highest version appears first in table

**Not Used for Launch**:
- No concept of "default version to launch"
- Each DCC launcher uses its own file discovery

---

## 7. KEY FILES SUMMARY TABLE

| File | Class | Purpose | Signals | Parent |
|------|-------|---------|---------|--------|
| `files_section.py` | `FilesSection` | Collapsible wrapper | `file_selected`, `file_open_requested`, `expanded_changed` | RightPanelWidget |
| `files_tab_widget.py` | `FilesTabWidget` | Tabbed tables | `file_selected`, `file_open_requested` | FilesSection |
| `files_tab_widget.py` | `FileTableModel` | Table data | - | FilesTabWidget |
| `shot_files_panel.py` | `ShotFilesPanel` | OLD (deprecated) | - | - |
| `right_panel.py` | `RightPanelWidget` | Container | - | MainWindow |
| `launcher_panel.py` | `LauncherPanel` | Launch UI | `app_launch_requested` | RightPanelWidget |
| `launcher_controller.py` | `LauncherController` | Coordination | - | MainWindow |
| `command_launcher.py` | `CommandLauncher` | Execution | - | LauncherController |

---

## 8. DESIGN OBSERVATIONS

### Files Section Strengths:
- Clean signal/slot architecture ready for extension
- Separate concerns: UI (FilesTabWidget) vs. container (FilesSection)
- Persistent expansion state (collapsed by default per user preference)
- Version sorting built-in via VersionHandlingMixin

### Launch System Strengths:
- Clean separation: UI (LauncherPanel) → Control (LauncherController) → Execution (CommandLauncher)
- Extensible via LaunchContext dataclass
- Keyboard shortcuts (3, N, M, R, P) and quick-launch buttons

### Connection Gap:
- **No bridge exists between file selection and launch parameters**
- FilesSection has selection capability but no consumers
- CommandLauncher doesn't check for selected files
- LaunchContext has no "selected_file" field (only selected_plate)

---

## 9. POTENTIAL INTEGRATION POINTS

For future file-based launching:

1. **Add field to LaunchContext** (command_launcher.py:42-63):
   ```python
   @dataclass
   class LaunchContext:
       selected_file: SceneFile | None = None  # NEW
       # ... other fields
   ```

2. **Connect FilesSection signals in RightPanelWidget**:
   ```python
   self._files_section.file_selected.connect(
       lambda file: self._on_file_selected(file)
   )
   ```

3. **Pass selected file through launch chain**:
   - LauncherController gets selection from FilesSection
   - Includes in LaunchContext
   - CommandLauncher uses it for app-specific behavior

4. **Mark "default" version** (optional UI enhancement):
   - Add visual indicator (icon/highlight) to latest version row
   - Or auto-select row 0 (highest version) on load

---

## 10. ARCHITECTURAL DIAGRAM

```
┌─────────────────────────────────────────────┐
│           RightPanelWidget                  │
├─────────────────────────────────────────────┤
│                                              │
│  ┌──────────────────────────────────────┐  │
│  │ ShotInfoPanel                        │  │
│  │ ├─ Thumbnail + shot info             │  │
│  └──────────────────────────────────────┘  │
│                                              │
│  ┌──────────────────────────────────────┐  │
│  │ FilesSection (COLLAPSIBLE)           │  │
│  │ ├─ Header: "Files (24)"              │  │
│  │ └─ Content: FilesTabWidget           │  │
│  │    ├─ Tab: 3DE files (table)         │  │
│  │    ├─ Tab: Maya files (table)        │  │
│  │    └─ Tab: Nuke files (table)        │  │
│  │       ↓ signals:                     │  │
│  │       file_selected(SceneFile)       │  │
│  │       file_open_requested(SceneFile) │  │
│  └──────────────────────────────────────┘  │
│          ⚠️  DISCONNECTED                   │
│          (signals have no listeners)        │
│                                              │
│  ┌──────────────────────────────────────┐  │
│  │ LauncherPanel                        │  │
│  │ ├─ Quick Launch: [3] [N] [M] [R] [P]│  │
│  │ └─ Cards: 3DE | Nuke | Maya | RV    │  │
│  │    ↓ signal:                         │  │
│  │    app_launch_requested(app, shot)   │  │
│  └──────────────────────────────────────┘  │
│       ↓ connects to                        │
│       LauncherController                   │
│                                              │
│  ┌──────────────────────────────────────┐  │
│  │ LogViewer                            │  │
│  └──────────────────────────────────────┘  │
│                                              │
└─────────────────────────────────────────────┘
```

---

## Summary

**Files Section = Display-Only UI**
- Shows version history of scene files
- Supports single-click (file_selected) and double-click (file_open_requested)
- Signals exist but currently unused
- Has `get_selected_file()` method available

**Launch System = Action-Driven**
- Launches DCCs with shot context
- Uses LaunchContext for options
- Takes no input from file selection

**Current Status: NOT INTEGRATED**
- Both subsystems work independently
- No "default version" affecting launch
- File selection signals are unconnected
