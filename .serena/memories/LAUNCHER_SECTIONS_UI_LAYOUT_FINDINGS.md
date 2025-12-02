# Launcher Sections UI Layout - Findings

## Summary
The right pane launcher sections (3DEqualizer, Maya, Nuke, RV) are implemented in a hierarchical component structure. The issues are related to top margin/padding and text overlap with buttons.

## File Structure & Components

### 1. **RightPanelWidget** (right_panel.py)
- **Location**: Lines 34-367
- **Role**: Composition root for the entire right panel
- **Key Layout Setup** (lines 108-115):
  ```python
  content_layout = QVBoxLayout(content_widget)
  content_layout.setContentsMargins(10, 24, 10, 10)  # TOP MARGIN = 24px
  content_layout.setSpacing(12)
  ```
- **Issues to Fix**:
  - The `24px` top margin in `content_layout.setContentsMargins(10, 24, 10, 10)` controls spacing for first section
  - This is where "3DEqualizer section starts too high" issue originates

### 2. **DCCAccordion** (dcc_accordion.py)
- **Location**: Lines 28-322
- **Role**: Container for all DCC sections
- **Layout Configuration** (lines 69-70):
  ```python
  layout = QVBoxLayout(self)
  layout.setSpacing(12)  # SPACING BETWEEN SECTIONS = 12px
  ```
- **Note**: No top margin - inherits spacing from parent RightPanelWidget

### 3. **DCCSection** (dcc_section.py)
- **Location**: Lines 147-1264
- **Role**: Individual collapsible section (one per DCC)
- **Structure**: Header + Collapsible content with Launch button + Description

#### Container Setup (lines 226-240):
```python
self._container = QWidget()
self._container.setStyleSheet(f"""
    QWidget#dccContainer {{
        background-color: {self._get_tinted_background()};
        border: 1px solid #333;
        border-left: 3px solid {self.config.color};
        border-radius: 4px;
    }}
""")

container_layout = QVBoxLayout(self._container)
container_layout.setContentsMargins(8, 6, 8, 6)  # PADDING INSIDE SECTION
container_layout.setSpacing(4)  # SPACING BETWEEN HEADER & CONTENT
```

#### Header Layout (lines 242-293):
- Expand/collapse arrow button
- DCC name label (bold, colored)
- Version info label

#### Content Layout (lines 295-411):
```python
self._content = QWidget()
self._content.setVisible(False)
content_layout = QVBoxLayout(self._content)
content_layout.setContentsMargins(26, 4, 0, 4)  # INDENT UNDER ARROW + 4px TOP/BOTTOM
content_layout.setSpacing(4)  # SPACING WITHIN EXPANDED CONTENT
```

### 4. **Launch Button & Description Text**
- **Button**: Located in content_layout (line 303)
  ```python
  self._launch_btn = QPushButton("Launch")
  content_layout.addWidget(self._launch_btn)
  ```
  
- **Description Label**: Lines 335-347
  ```python
  self._launch_description = QLabel()
  self._launch_description.setStyleSheet(f"""
      QLabel {{
          color: #888;
          font-size: {design_system.typography.size_tiny}px;
          margin-top: 12px;  # VERTICAL SPACING ISSUE HERE
      }}
  """)
  self._launch_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
  self._launch_description.setVisible(False)
  content_layout.addWidget(self._launch_description)
  ```

## Critical Spacing Values

| Component | Property | Value | Line Reference |
|-----------|----------|-------|-----------------|
| RightPanelWidget content | `setContentsMargins(top=24)` | 24px | right_panel.py:110 |
| DCCAccordion sections | `setSpacing` | 12px | dcc_accordion.py:70 |
| DCCSection container | `setContentsMargins` | 8,6,8,6 | dcc_section.py:235 |
| DCCSection container | `setSpacing` | 4px | dcc_section.py:236 |
| DCCSection content | `setContentsMargins(top=4)` | 4px | dcc_section.py:300 |
| DCCSection content | `setSpacing` | 4px | dcc_section.py:301 |
| Launch description | CSS `margin-top` | 12px | dcc_section.py:341 |

## Issues to Fix

### Issue 1: "3DEqualizer section starts too high"
**Root Cause**: 24px top margin in `RightPanelWidget._setup_ui()` line 110
- Change: `content_layout.setContentsMargins(10, 24, 10, 10)`
- **Potential Fix**: Increase the 24 value (e.g., 32, 40) or adjust the 4px content padding

### Issue 2: "Text like 'Opens: v089 | bg01' overlaps Launch buttons"
**Root Cause**: CSS `margin-top: 12px` in launch_description QLabel stylesheet (line 341)
- The margin may be creating negative space or not accounting for button height
- The `content_layout.setSpacing(4)` between launch button and description may be too small
- **Potential Fix**: 
  - Increase CSS margin-top value (e.g., 4px or 6px)
  - OR increase layout spacing from 4px to 6px/8px
  - OR adjust alignment/layout of the description label

## Layout Hierarchy

```
RightPanelWidget (margin-top: 24px)
  └─ QScrollArea
      └─ content_widget
          └─ DCCAccordion (spacing: 12px between sections)
              ├─ DCCSection (3DEqualizer)
              │   └─ _container (padding: 8,6,8,6 | spacing: 4px)
              │       ├─ header (always visible)
              │       │   ├─ expand arrow
              │       │   ├─ DCC name (bold, colored)
              │       │   └─ version label
              │       └─ _content (hidden when collapsed | spacing: 4px)
              │           ├─ Launch button
              │           ├─ Launch description (margin-top: 12px) ← TEXT OVERLAP HERE
              │           ├─ Checkboxes
              │           ├─ Plate selector
              │           └─ Files sub-section
              ├─ DCCSection (Maya)
              ├─ DCCSection (Nuke)
              └─ DCCSection (RV)
```

## Related Methods for Modifications

### RightPanelWidget._setup_ui()
- File: `/home/gabrielh/projects/shotbot/right_panel.py`
- Lines: 75-134
- Key line to modify: 110

### DCCSection._setup_ui()
- File: `/home/gabrielh/projects/shotbot/dcc_section.py`
- Lines: 219-411
- Launch description styling: Lines 335-347
- Content layout setup: Lines 298-301

### DCCSection._apply_styles()
- File: `/home/gabrielh/projects/shotbot/dcc_section.py`
- Lines: 413-547
- Launch description styling (dynamic): Lines 476-481

## Testing Recommendations

1. **Visual testing** with expanded sections
2. **Check all DCC sections** (3DE, Maya, Nuke, RV)
3. **Test with and without file lists** (files sub-section)
4. **Test responsive behavior** when window resized
5. **Verify text doesn't truncate** for long version strings
