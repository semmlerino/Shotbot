# Shotbot Shot Files Panel - Exploration Report

## Overview
The Shot Files Panel is a UI component that displays scene files (3DEqualizer, Maya, Nuke) associated with a currently selected shot in the Shotbot application.

---

## 1. SHOT FILES PANEL IMPLEMENTATION

### File Location
`/home/gabrielh/projects/shotbot/shot_files_panel.py`

### Class Hierarchy
```
ShotFilesPanel (QtWidgetMixin, QWidget)
├── FileTypeSection (QtWidgetMixin, QWidget) [one per file type: 3DE, Maya, Nuke]
│   └── FileListItem (QFrame) [one per file in the section]
```

### Key Classes

#### ShotFilesPanel (lines 276-357)
- **Purpose**: Main panel container displaying files for current shot
- **Structure**:
  - Header label "Files" with styling
  - Three FileTypeSection instances (one for each FileType enum)
  - Stretch at bottom for layout flexibility
- **Layout**: QVBoxLayout with:
  - `setContentsMargins(0, 10, 0, 0)` - 10px top margin, no other margins
  - `setSpacing(5)` - 5px between sections
- **Size Policy**: Uses `addStretch()` at bottom (line 326)
- **Minimum Height**: None set (flexible)

#### FileTypeSection (lines 138-273)
- **Purpose**: Collapsible section for one file type (3DE, Maya, or Nuke)
- **Features**:
  - Expand/collapse button (QToolButton)
  - Header with file type name and count: "3DEqualizer (24)"
  - Indented content area containing file list
- **Layout Structure**:
  - QVBoxLayout with `setContentsMargins(0, 0, 0, 5)` and `setSpacing(3)`
  - Header area: QHBoxLayout with expand button and label
  - Content area: QWidget with QVBoxLayout using `setContentsMargins(20, 0, 0, 0)` (left indent)
- **Header Label Styling** (lines 195-201):
  - Uses FILE_TYPE_COLORS for color (red/teal/orange)
  - Font: bold, 11px
- **Visibility**: Only shown if section has files (line 268)

#### FileListItem (lines 32-135)
- **Purpose**: Single file row displaying filename, user, and age
- **Layout**: QHBoxLayout with:
  - `setContentsMargins(5, 2, 5, 2)` - minimal padding
  - `setSpacing(10)` - 10px between elements
- **Elements** (left to right):
  1. File name label (flex: 1) - "#ddd", 11px
  2. User label - "#888", 10px
  3. Age label - "#666", 10px
- **Styling** (lines 82-90):
  ```python
  background-color: transparent;
  border-radius: 3px;
  # On hover: background-color: #2a2a2a;
  ```
- **Interactions**: Right-click context menu (open, open folder, copy path)

---

## 2. COLOR SYSTEM

### File Location
`/home/gabrielh/projects/shotbot/scene_file.py` (lines 34-38)

### FILE_TYPE_COLORS Dictionary
```python
FILE_TYPE_COLORS: dict[FileType, str] = {
    FileType.THREEDE: "#c0392b",  # Red
    FileType.MAYA: "#16a085",     # Teal
    FileType.NUKE: "#d35400",     # Orange
}
```

### Usage in Shot Files Panel
- Header labels use these colors for section names (line 199)
- FILE_TYPE_COLORS is imported at top of shot_files_panel.py (line 21)

---

## 3. DESIGN SYSTEM & THEMING

### File Location
`/home/gabrielh/projects/shotbot/design_system.py`

### Key Design Tokens
```python
@dataclass
class ColorPalette:
    # Primary backgrounds
    bg_primary: str = "#1E1E1E"      # Main background
    bg_secondary: str = "#252525"    # Card/panel background
    bg_tertiary: str = "#2D2D2D"     # Elevated surfaces
    
    # Surface colors
    surface: str = "#333333"
    surface_hover: str = "#3D3D3D"
    surface_pressed: str = "#2A2A2A"
    
    # Text colors (WCAG AA compliant)
    text_primary: str = "#FFFFFF"    # 21:1 contrast
    text_secondary: str = "#B0B0B0"  # 7:1 contrast
    text_disabled: str = "#707070"   # 4.5:1 contrast

@dataclass
class Spacing:
    unit: int = 4                    # 4px base unit
    xs: int = 4                      # 1 unit
    sm: int = 8                      # 2 units
    md: int = 16                     # 4 units
    lg: int = 24                     # 6 units
```

### Global Stylesheet
- Generated via `design_system.get_stylesheet()` but NOT currently applied to Shot Files Panel
- Shot Files Panel uses inline QSS stylesheets instead

### Current Shot Info Panel Styling (shot_info_panel.py)
```python
# Container (line 172-178)
self.setStyleSheet("""
    ShotInfoPanel {
        background-color: #1a1a1a;
        border: 1px solid #333;
        border-radius: 6px;
    }
""")
```

---

## 4. SIZE POLICY & CONSTRAINTS IN LAYOUT

### Main Window Layout (main_window.py, lines 351-473)

#### Splitter Configuration
```python
# Line 378
self.splitter = QSplitter(Qt.Orientation.Horizontal)
main_layout.addWidget(self.splitter)

# Line 446 - Fixed split sizes
self.splitter.setSizes([840, 360])  # 70/30 split
```

#### Right Panel Layout (lines 412-443)
```python
right_widget = QWidget()
right_layout = QVBoxLayout(right_widget)
right_layout.setContentsMargins(0, 0, 0, 0)

# ShotInfoPanel - NO SIZE CONSTRAINTS
self.shot_info_panel = ShotInfoPanel(self.cache_manager)
right_layout.addWidget(self.shot_info_panel)

# LauncherPanel - HAS MINIMUM HEIGHT
self.launcher_panel = LauncherPanel()
self.launcher_panel.setMinimumHeight(400)  # ← CONSTRAINT HERE
right_layout.addWidget(self.launcher_panel)

# Log viewer (in group box)
log_group = QGroupBox("Command Log")
log_layout = QVBoxLayout(log_group)
self.log_viewer = LogViewer()
log_layout.addWidget(self.log_viewer)
right_layout.addWidget(log_group)

self.splitter.addWidget(right_widget)
```

#### Size Policy Analysis
| Component | Min Height | Max Height | Stretch | Notes |
|-----------|-----------|-----------|---------|-------|
| ShotInfoPanel | 200px | None | Flexible | `setMinimumHeight(200)` at line 181 |
| LauncherPanel | 400px | None | Flexible | `setMinimumHeight(400)` at line 423 |
| LogViewer (in QGroupBox) | None | None | Flexible | Takes remaining space |
| Right layout | None | None | 1 (flex) | Uses `addWidget()` for all items, no stretch |

### ShotInfoPanel Constraints (shot_info_panel.py)
```python
# Line 181 - Only constraint is minimum height
self.setMinimumHeight(200)
```

### Shot Files Panel Constraints (shot_files_panel.py)
```python
# No size constraints set
# Uses QVBoxLayout with addStretch() at bottom
# Expands/contracts based on parent size
```

---

## 5. LAYOUT HIERARCHY & SPACING

### Margins & Spacing Summary
```
MainWindow
└── ShotInfoPanel (200px min height)
    ├── Main QVBoxLayout: margins(10, 10, 10, 10), spacing(10)
    │
    ├── Top Section (thumbnail + info)
    │   └── QHBoxLayout: margins(0, 0, 0, 0), spacing(15)
    │       ├── Thumbnail: 128x128 fixed
    │       └── Info QVBoxLayout: spacing(5)
    │           ├── Shot name (18px bold)
    │           ├── Show/Sequence (12px)
    │           └── Path (9px, word-wrapped)
    │
    ├── ShotFilesPanel
    │   └── QVBoxLayout: margins(0, 10, 0, 0), spacing(5)
    │       ├── "Files" header label
    │       ├── FileTypeSection (3DE)
    │       │   ├── Header: button(20x20) + label + stretch
    │       │   └── Content: QWidget with margins(20, 0, 0, 0) for indent
    │       │       └── FileListItem (per file)
    │       ├── FileTypeSection (Maya)
    │       ├── FileTypeSection (Nuke)
    │       └── addStretch()
    │
    └── LauncherPanel (400px min height)
```

---

## 6. KEY FILES SUMMARY

| File | Location | Purpose |
|------|----------|---------|
| `shot_files_panel.py` | Root | Main Files panel widget (ShotFilesPanel, FileTypeSection, FileListItem) |
| `scene_file.py` | Root | Scene file model & FILE_TYPE_COLORS definition |
| `shot_info_panel.py` | Root | Parent container for ShotFilesPanel + thumbnail + info |
| `design_system.py` | Root | Centralized design tokens (colors, typography, spacing) - NOT YET APPLIED |
| `launcher_panel.py` | Root | Launcher buttons below ShotInfoPanel (setMinimumHeight: 400) |
| `main_window.py` | Root | Overall layout (splitter: 70/30, right panel: ShotInfoPanel + LauncherPanel + LogViewer) |

---

## 7. CURRENT STYLING APPROACH

### Inline QSS vs Design System
- **Shot Files Panel**: Uses inline `setStyleSheet()` calls
- **File List Items**: Each label has separate `setStyleSheet()` call
- **Design System**: Exists but NOT actively applied to Files panel

### Colors Currently Used (hardcoded)
```python
# In FileListItem
name_label.setStyleSheet("color: #ddd; font-size: 11px;")
user_label.setStyleSheet("color: #888; font-size: 10px;")
age_label.setStyleSheet("color: #666; font-size: 10px;")

# In FileTypeSection header
color = FILE_TYPE_COLORS[self._file_type]  # Red/Teal/Orange
self._header_label.setStyleSheet(f"color: {color}; ...")

# In FileTypeSection expand button
setStyleSheet("""
    QToolButton {
        border: none;
        background: transparent;
    }
    QToolButton:hover {
        background-color: #333;
        border-radius: 2px;
    }
""")

# In FileListItem frame
setStyleSheet("""
    FileListItem {
        background-color: transparent;
        border-radius: 3px;
    }
    FileListItem:hover {
        background-color: #2a2a2a;
    }
""")
```

---

## 8. OBSERVATIONS & SPACE ISSUES

### Right Panel Layout Issues
1. **LauncherPanel minimum height (400px)**: Takes significant space
2. **ShotInfoPanel minimum height (200px)**: Also substantial
3. **No stretch factors**: All three right-panel widgets (ShotInfoPanel, LauncherPanel, LogViewer) are added with `addWidget()` without stretch factors
4. **Files panel visibility**: Completely collapsible sections + stretch at bottom means panel adapts to available space

### Files Panel Specific
- **Adaptive height**: Uses `addStretch()` - expands if section has room, collapses if constrained
- **Collapsible sections**: Each file type is independently collapsible
- **No truncation**: File names can be long (full path in tooltip via `setToolTip()`)
- **Indentation**: 20px left margin for file items inside sections

---

## 9. MISSING DESIGN SYSTEM INTEGRATION

The `design_system.py` module exists but is not integrated into:
- ShotFilesPanel styling
- FileTypeSection styling
- FileListItem styling
- ShotInfoPanel styling

Opportunities for unification:
- Use `design_system.colors.text_secondary` for user/age labels
- Use `design_system.colors.surface_hover` for hover states
- Use `design_system.spacing` for margins/padding
- Apply global stylesheet via `qApp.setStyleSheet(design_system.get_stylesheet())`
