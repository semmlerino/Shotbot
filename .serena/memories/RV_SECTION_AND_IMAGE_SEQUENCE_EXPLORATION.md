# Shotbot RV Section and Image Sequence Exploration

## EXECUTIVE SUMMARY

The shotbot codebase has a modern, well-structured RV section implementation as part of a DCC (Digital Content Creation) accordion system. RV is configured with the same pattern as 3DE, Maya, and Nuke, but currently has **no files section** because RV is a playback/review tool without scene files. Image sequence detection is handled through several finder utilities, with comprehensive support for EXR sequences and playblast patterns.

---

## 1. RV SECTION IMPLEMENTATION

### Location: `/home/gabrielh/projects/shotbot/dcc_section.py` (lines 132-140)

RV is one of four DCCs defined in `DEFAULT_DCC_CONFIGS`:

```python
DCCConfig(
    name="rv",
    display_name="RV",
    color="#2b5d4d",         # Teal accent color
    shortcut="R",             # Keyboard shortcut
    tooltip="Launch RV for playback and review",
    has_files_section=False,  # KEY: No files panel for RV
    file_type=None,          # KEY: No scene files to display
)
```

### Key Characteristics

| Property | Value | Purpose |
|----------|-------|---------|
| **name** | "rv" | Internal identifier |
| **display_name** | "RV" | UI label |
| **color** | "#2b5d4d" | Left accent border in collapsed header |
| **shortcut** | "R" | Keyboard shortcut (Alt+R or direct press) |
| **has_files_section** | False | No embedded files sub-section |
| **file_type** | None | Not used for file discovery |
| **has_plate_selector** | True (default) | Can select plate space |
| **checkboxes** | None | No launch options |

### RV Section Structure

The RV section in the UI will show:
- **Header** (always visible):
  - Expand/collapse arrow
  - "RV" label in teal color (#2b5d4d)
  - Version info (if available)
  - Keyboard shortcut badge "R"
  
- **Expanded content** (when toggled):
  - Launch button (blue/primary color)
  - Plate selector dropdown (if plates available)
  - NO files sub-section (unlike 3DE, Maya, Nuke)

---

## 2. RIGHT PANE ARCHITECTURE

### File Structure

```
right_panel.py (RightPanelWidget)
  └── dcc_accordion.py (DCCAccordion)
      ├── dcc_section.py (DCCSection for 3DE)
      │   └── _setup_files_subsection() → FileTableView with files list
      ├── dcc_section.py (DCCSection for Maya)
      │   └── _setup_files_subsection()
      ├── dcc_section.py (DCCSection for Nuke)
      │   └── _setup_files_subsection()
      └── dcc_section.py (DCCSection for RV)
          └── NO FILES SECTION (file_type=None, has_files_section=False)
```

### Key Classes

#### RightPanelWidget (`right_panel.py`, lines 34-324)
- **Purpose**: Composition root for right panel
- **Contains**: ScrollArea with DCCAccordion
- **Layout**: QVBoxLayout with scrollable content
- **Signals**: `launch_requested` (app_name, options dict)
- **Key Method**: `set_shot(shot, discover_files=True)` - Updates all DCC sections with new shot

#### DCCAccordion (`dcc_accordion.py`, lines 28-322)
- **Purpose**: Container for all DCC sections (3DE, Maya, Nuke, RV)
- **Contains**: 4 DCCSection instances (one per DCC)
- **Signals**:
  - `launch_requested(app_name, options)`
  - `section_expanded(app_name, is_expanded)`
  - `file_selected(app_name, scene_file)` - Only for DCCs with files
- **Key Methods**:
  - `set_files_for_dcc(app_name, files)` - Populates files for 3DE/Maya/Nuke
  - `set_default_file_for_dcc(app_name, file)` - Highlights a file as selected
  - `get_selected_file(app_name)` - Returns currently selected file
  - `set_launch_description(app_name, description)` - Shows custom launch info

#### DCCSection (`dcc_section.py`, lines 151-1026)
- **Purpose**: Individual collapsible section for one DCC
- **Features**:
  - Expand/collapse header with version info
  - Launch button with selected file indication
  - Option checkboxes (Nuke: 3 options; 3DE/Maya: 1 option; RV: 0 options)
  - Plate selector (all DCCs except RV will use it)
  - Files sub-section (only for 3DE, Maya, Nuke - NOT RV)
- **Key Methods**:
  - `set_files(files)` - Updates file list (RV will never call this)
  - `set_available_plates(plates)` - Updates plate selector options
  - `get_options()` - Returns checkbox states as dict
  - `get_selected_file()` - Returns user-clicked file from files table
  - `get_selected_plate()` - Returns plate selector value

---

## 3. RV LAUNCHING FLOW

### How RV Launch Works

**Flow: User clicks RV launch button → RightPanelWidget → CommandLauncher**

1. **User clicks "Launch" in RV section**
   - DCCSection emits: `launch_requested("rv", options_dict)`
   - options_dict contains: `{"selected_plate": "FG01"}` (if plate selected)

2. **DCCAccordion relays signal**
   - Emits: `launch_requested("rv", options_dict)` to parent

3. **RightPanelWidget handles launch**
   - Intercepts: `launch_requested("rv", options_dict)`
   - Injects selected file (if any - RV has none)
   - Emits: `launch_requested("rv", options_dict)` upward

4. **LauncherController catches signal**
   - Calls: `command_launcher.launch_app("rv", context=LaunchContext(...))` 
   - Or legacy: `launch_app("rv", selected_plate=None)`

5. **CommandLauncher.launch_app() executes** (`command_launcher.py`, lines 386-615)
   - Gets base command from `Config.APPS["rv"]`
   - No special handling (no scene files, no plate Read nodes)
   - Validates workspace path
   - Builds: `ws {workspace_path} && {env_fixes}rv`
   - Wraps with Rez if configured
   - Launches in new terminal via ProcessExecutor

### Current RV Launch Code Path

```python
# In CommandLauncher.launch_app()
if app_name == "rv":
    command = Config.APPS["rv"]  # Get "rv" command
    # NO special handling for RV (lines 471-526 skip RV entirely)
    # Falls through to workspace + rez wrapping
    # Build workspace command: "ws {path} && rv"
    # Launch in terminal
```

### Key Insight: RV Has No Options

Unlike Nuke (3 checkboxes), 3DE (1 checkbox), and Maya (1 checkbox), RV has:
- ✅ **Plate selector** (can select FG01, BG01, etc.)
- ❌ **No launch checkboxes** (no scene files to open)
- ❌ **No files section** (playback tool, not editor)
- ❌ **No version info** (no RV scene files)

---

## 4. IMAGE SEQUENCE DETECTION & HANDLING

### File Discovery Infrastructure

#### Key Files:
- **`shot_file_finder.py`**: Main interface for discovering files by type
- **`raw_plate_finder.py`**: EXR sequence detection with frame range
- **`nuke_media_detector.py`**: Properties detector (frame range, colorspace, resolution)
- **`file_discovery.py`**: Core file discovery service
- **`finder_utils.py`**: Utility functions for file searching
- **`plate_discovery.py`**: Plate directory discovery

### 1. Raw Plate Finder (`raw_plate_finder.py`)

**Purpose**: Find EXR sequences for shots

**Key Methods**:

```python
RawPlateFinder.find_latest_raw_plate(shot_workspace_path, shot_name)
  → Returns: Path pattern like "/path/to/FG01/v001/exr/4312x2304/shot_0001_linear_v001.####.exr"
  → Returns: None if no plate found

RawPlateFinder.find_plate_for_space(shot_workspace_path, shot_name, plate_space)
  → Returns: Path to specific plate (e.g., "BG01") with #### for frame numbers
```

**EXR Sequence Pattern Detection**:

```
Base path: {workspace}/plates/{plate_name}/{version}/exr/{resolution}/
Pattern: {shot_name}_turnover-plate_{plate_name}_{colorspace}_{version}.####.exr

Examples:
- DM_066_3580_turnover-plate_FG01_lin_v001.####.exr
- DM_066_3580_turnover-plate_BG01_logc3_v002.####.exr
- DM_066_3580_turnover-plate_FG01lin_v001.####.exr (alt pattern)
```

**Features**:
- Case-insensitive filesystem handling
- Pattern cache for performance
- Colorspace detection (lin_, logc, alexa, rec709, srgb)
- Resolution extraction (4312x2304, 1920x1080, etc.)
- Version priority ordering

### 2. Nuke Media Detector (`nuke_media_detector.py`)

**Purpose**: Analyze media properties from plate paths

**Key Methods**:

```python
NukeMediaDetector.detect_frame_range(plate_path)
  → Returns: (first_frame, last_frame) by scanning directory for matching files
  → Default: (1001, 1100) for VFX standard range

NukeMediaDetector.detect_colorspace(plate_path)
  → Returns: (colorspace_name, raw_flag)
  → Examples: ("linear", True), ("logc3ei800", False), ("rec709", False)

NukeMediaDetector.detect_resolution(plate_path)
  → Returns: (width, height) extracted from path like "4312x2304"
  → Default: (4312, 2304) for production
```

**Colorspace Detection Logic**:
- "lin_" or "linear" → ("linear", raw=True)
- "logc" or "alexa" → ("logc3ei800", raw=False)
- "log" → ("log", raw=False)
- "rec709" → ("rec709", raw=False)
- "srgb" → ("sRGB", raw=False)
- Default → ("linear", raw=True)

### 3. Shot File Finder (`shot_file_finder.py`)

**Purpose**: Unified interface for finding all file types (3DE, Maya, Nuke)

**Key Method**:

```python
ShotFileFinder.find_all_files(shot)
  → Returns: dict[FileType, list[SceneFile]]
  → {
      FileType.THREEDE: [SceneFile(...), SceneFile(...), ...],
      FileType.MAYA: [SceneFile(...), ...],
      FileType.NUKE: [SceneFile(...), ...],
    }
```

**File Discovery Patterns**:
- **3DE**: ThreeDELatestFinder.find_all_threede_scenes(workspace)
  - Pattern: `{workspace}/**/*.3de`
  
- **Maya**: MayaLatestFinder.find_all_maya_scenes(workspace)
  - Pattern: `{workspace}/**/*.ma` or `**/*.mb`
  
- **Nuke**: Scans user directories
  - Pattern: `{workspace}/user/*/mm/nuke/**/*.nk`

**SceneFile Object**:
```python
@dataclass
class SceneFile:
    path: Path
    file_type: FileType  # THREEDE, MAYA, NUKE
    modified_time: datetime
    user: str           # Extracted from "user/{username}/..." path
    version: int | None # Extracted from "_v###.ext" pattern
```

### 4. Plate Discovery (`plate_discovery.py`)

**Purpose**: Discover available plate directories

**Key Methods**:
- `discover_plate_directories(base_path)` → Returns list of (name, priority) tuples
- Scans for directories: FG01, BG01, bg01, etc.
- Priority ordering: FG > BG > Custom

---

## 5. IMAGE SEQUENCE PATTERNS IN USE

### Pattern 1: Raw Plate EXR Sequences

**Used by**: Nuke (for Read nodes), RV (for playback)

**Directory Structure**:
```
{workspace}/plates/{plate_name}/{version}/exr/{resolution}/
├── DM_066_3580_turnover-plate_FG01_lin_v001.0001.exr
├── DM_066_3580_turnover-plate_FG01_lin_v001.0002.exr
├── ... (frame sequence)
└── DM_066_3580_turnover-plate_FG01_lin_v001.1200.exr
```

**Detection Logic**:
- RawPlateFinder scans directory
- Finds first EXR file
- Extracts colorspace from filename
- Returns pattern: `path.####.exr`
- Frame range detected by scanning actual files

### Pattern 2: Maya Playblasts (TBD)

**Not Yet Implemented**: No playblast detection code found

**Expected Pattern** (industry standard):
```
{workspace}/user/{username}/playblasts/
├── {shot_name}_v001.mov
├── {shot_name}_v001.exr (frame sequence or direct EXR)
└── {shot_name}_v002.mov
```

### Pattern 3: Nuke Renders (Partially Implemented)

**Handled by**: NukeMediaDetector and nuke_script_generator

**Expected Patterns**:
- Nuke script output node → creates EXR sequences
- Nuke internally handles frame ranges for Read/Write nodes
- Paths typically: `{workspace}/renders/{version}/`

---

## 6. HOW RV WOULD USE IMAGE SEQUENCES

### Option 1: Via Plate Selector (Current)

RV section has plate selector dropdown. User selects:
- "FG01" → RV opens workspace with plate space FG01
- "BG01" → RV opens workspace with plate space BG01

**Command**: `ws {workspace} && rv` (RV finds plates via workspace env vars)

### Option 2: Via RV Scene Files (Proposed)

If we add RV support for .rv files (RV session files):

**Steps**:
1. Set `has_files_section=True` in DCCConfig for RV
2. Create `RVFileFinder` to find `.rv` files in workspace
3. Add `file_type=FileType.RV` to config (add to scene_file.py enum)
4. DCCSection will show files list for RV
5. User selects `.rv` file, RV opens it

### Option 3: Via Image Sequence Direct (Advanced)

RV can load image sequences directly:
```bash
rv /path/to/plates/FG01/v001/exr/4312x2304/shot_0001_lin_v001.####.exr
```

**Would require**:
1. Add checkbox: "Load plate sequence"
2. Modify CommandLauncher.launch_app("rv") to:
   - Find plate via RawPlateFinder
   - Append sequence path to command
3. Example: `ws {workspace} && rv {plate_path}`

---

## 7. KEY FINDINGS

### ✅ What Exists
- **RV Section**: Fully configured in DEFAULT_DCC_CONFIGS (lines 132-140)
- **RV UI**: Renders as collapsible section with launch button
- **RV Launching**: Basic command building in CommandLauncher.launch_app()
- **Plate Selector**: Available for RV (has_plate_selector=True default)
- **Image Sequences**: EXR detection via RawPlateFinder and NukeMediaDetector

### ⚠️ What's Limited
- **RV Files Section**: Disabled (has_files_section=False)
- **RV-Specific Options**: None configured (no checkboxes, no scene files)
- **Playblast Detection**: Not implemented (no dedicated finder)
- **RV Scene Files**: No .rv file discovery or support

### 🔧 Extension Points

1. **Add RV files support**:
   - Create `rv_scene_finder.py` to find `.rv` files
   - Add to `shot_file_finder.py`
   - Set `has_files_section=True` in DCCConfig
   - Add `FileType.RV` enum

2. **Add playblast detection**:
   - Create `playblast_finder.py` for `.mov` and `.exr` sequences
   - Pattern: `{workspace}/playblasts/` or `{workspace}/user/{user}/renders/`
   - Return as SceneFile objects

3. **Add direct plate sequence loading**:
   - Add checkbox to RV: "Load plate sequence"
   - Modify launch_app() to append plate path
   - Use RawPlateFinder output as sequence arg

---

## 8. FILE DEPENDENCIES MAP

```
right_panel.py (RightPanelWidget)
  ├── dcc_accordion.py (DCCAccordion)
  │   └── dcc_section.py (DCCSection) × 4
  │       ├── files_tab_widget.py (FileTableModel) [Only for 3DE/Maya/Nuke]
  │       └── scene_file.py (SceneFile, FileType enum)
  │
  └── shot_file_finder.py (ShotFileFinder)
      ├── threede_latest_finder.py
      ├── maya_latest_finder.py
      ├── nuke_*.py
      └── raw_plate_finder.py
          ├── plate_discovery.py
          └── nuke_media_detector.py

command_launcher.py (CommandLauncher)
  ├── nuke_launch_router.py
  ├── nuke_launch_handler.py
  ├── raw_plate_finder.py
  ├── threede_latest_finder.py
  └── maya_latest_finder.py
```

---

## 9. IMPLEMENTATION NOTES

### RV Configuration Consistency

RV follows the same pattern as other DCCs:
- ✅ Keyboard shortcut "R"
- ✅ Color scheme (#2b5d4d teal)
- ✅ Display name "RV"
- ✅ Tooltip
- ✅ Plate selector available

### RV Limitations (By Design)

- ❌ No launch checkboxes (doesn't modify scene/behavior)
- ❌ No files section (playback tool, not scene editor)
- ❌ No version tracking (workspace doesn't apply)

### Best Practices for RV Integration

1. **Keep simple**: RV = launch with workspace only
2. **Leverage plates**: Plate selector handles content choice
3. **Consider future**: .rv files (session files) could be added later
4. **Pattern compatibility**: Use RawPlateFinder output for direct sequence loading

