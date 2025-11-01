# Nuke Scripting Learnings & Best Practices

## 🎯 Key Discoveries from Production Issues

### 1. Critical Misconception: Read Nodes Are NOT for Scripts

#### ❌ **WRONG - Common Mistake**
```python
# THIS DOES NOT WORK!
Read_File_1 {
    inputs 0
    file "/path/to/script.nk"
    file_type nk  # ← Read nodes don't support .nk files!
    name import_script
}
```

#### ✅ **CORRECT - Proper Methods**

**In Python API (Interactive Nuke):**
```python
# Method 1: Paste nodes from file
nuke.nodePaste('/path/to/script.nk')

# Method 2: Load as toolset
nuke.loadToolset('/path/to/script.nk')  

# Method 3: Source the script
nuke.scriptSource('/path/to/script.nk')

# Method 4: Import specific nodes
nuke.scriptReadFile('/path/to/script.nk')
```

**In Static .nk Script Generation:**
```python
# You must read the file content and embed it directly
with open('undistortion.nk', 'r') as f:
    undist_content = f.read()
    # Parse and embed the nodes in your generated script
```

### 2. File Path Handling - Critical Rules

#### **Rule 1: Always Use Forward Slashes**
```python
# ❌ WRONG (Windows backslashes)
file "C:\shots\plate.####.exr"

# ✅ CORRECT (Forward slashes everywhere)
file "C:/shots/plate.####.exr"

# Python helper function
def escape_path(path: str) -> str:
    """Convert to Nuke-compatible path."""
    return path.replace("\\", "/")
```

#### **Rule 2: Frame Padding Formats**
```python
# Nuke accepts multiple formats:
"plate.####.exr"     # Hash notation (4 digits)
"plate.%04d.exr"     # Printf notation (preferred)
"plate.######.exr"   # 6-digit padding
"plate.%06d.exr"     # Printf 6-digit

# Conversion for Nuke
nuke_path = plate_path.replace("####", "%04d")
```

#### **Rule 3: Path Escaping in TCL**
```python
# Spaces and special characters need proper handling
file "/path with spaces/plate.%04d.exr"  # Usually works
file {{/path with spaces/plate.%04d.exr}}  # Safer with braces
```

### 3. Node Types and Their Purposes

| Node Type | Purpose | File Types | Common Mistake |
|-----------|---------|------------|----------------|
| **Read** | Import image sequences | EXR, JPEG, PNG, DPX, TIFF | Trying to load .nk files |
| **ReadGeo** | Import 3D geometry | OBJ, FBX, ABC, USD | Using Read for geo |
| **Camera** | Import camera data | CHAN, FBX, ABC | Manual camera creation |
| **Group** | Container for nodes | N/A | Not understanding input/output |
| **LiveGroup** | Dynamic external reference | .nk, .gizmo | Not available in all versions |

### 4. OCIO Color Management

#### **Proper ACES Configuration**
```tcl
Root {
    colorManagement OCIO
    OCIO_config aces_1.2
    defaultViewerLUT "OCIO LUTs"
    workingSpaceLUT "ACES - ACEScg"
    monitorLut "Rec.709 (ACES)"
    int8Lut "Rec.709 (ACES)"
    int16Lut "Rec.709 (ACES)"
    logLut "Log film emulation (ACES)"
    floatLut linear
}
```

#### **Colorspace Detection Pattern**
```python
def detect_colorspace(filename: str) -> str:
    """Map filename patterns to OCIO colorspaces."""
    name_lower = filename.lower()
    
    if "aces" in name_lower:
        return "ACES - ACEScg"
    elif "lin_sgamut3cine" in name_lower:
        return "Input - Sony - S-Gamut3.Cine - Linear"
    elif "rec709" in name_lower:
        return "Output - Rec.709"
    elif "srgb" in name_lower:
        return "Output - sRGB"
    else:
        return "scene_linear"  # Safe default
```

### 5. Frame Range Detection Best Practices

#### **Method 1: File System Scanning**
```python
def detect_frame_range(plate_path: str) -> tuple[int, int]:
    """Scan actual files to find frame range."""
    plate_dir = Path(plate_path).parent
    pattern = Path(plate_path).name.replace("####", r"(\d{4})")
    frame_regex = re.compile(pattern)
    
    frame_numbers = []
    for file in plate_dir.iterdir():
        if match := frame_regex.match(file.name):
            frame_numbers.append(int(match.group(1)))
    
    if frame_numbers:
        return min(frame_numbers), max(frame_numbers)
    return 1001, 1100  # VFX standard default
```

#### **Method 2: Metadata Reading (Advanced)**
```python
# Using Nuke Python API
read_node = nuke.nodes.Read(file=path)
first = read_node['first'].value()
last = read_node['last'].value()
```

### 6. Read Node Essential Knobs

```tcl
Read {
    inputs 0
    
    # File specification
    file_type exr                    # Explicit file type
    file "/path/to/plate.%04d.exr"   # File path with padding
    proxy "/path/to/proxy.%04d.exr"  # Optional proxy path
    
    # Frame range
    first 1001        # Start frame
    last 1100         # End frame
    origfirst 1001    # Original start (for reference)
    origlast 1100     # Original end (for reference)
    origset true      # Use original range
    
    # Format
    format "4312 2304 0 0 4312 2304 1 plate_format"
    
    # Error handling
    on_error black    # black, checkerboard, or error
    reload 0          # Auto-reload off
    
    # Color
    colorspace "ACES - ACEScg"  # OCIO colorspace
    raw false                    # Raw data interpretation
    premultiplied true          # Alpha premultiplication
    auto_alpha true             # Auto-detect alpha
    
    # UI
    name Read_Plate
    label "\\[value colorspace]\\nframes: \\[value first]-\\[value last]"
    selected true
    xpos 0
    ypos -150
}
```

### 7. Python API vs Static Script Generation

| Aspect | Python API (in Nuke) | Static .nk Generation |
|--------|----------------------|----------------------|
| **Context** | Running inside Nuke | External script creation |
| **Node Creation** | `nuke.nodes.Read()` | Write TCL text |
| **Import .nk** | `nuke.nodePaste()` | Must embed content |
| **Path Access** | Can query Nuke prefs | Must detect from filesystem |
| **Error Handling** | Try/except with Nuke errors | Standard Python exceptions |
| **Validation** | Nuke validates immediately | No validation until loaded |

### 8. Common Pitfalls and Solutions

#### **Pitfall 1: Assuming Read Nodes Are Universal**
- **Problem**: Trying to use Read for scripts, gizmos, or geometry
- **Solution**: Use appropriate node types or import methods

#### **Pitfall 2: Windows Path Separators**
- **Problem**: Backslashes break TCL parsing
- **Solution**: Always convert to forward slashes

#### **Pitfall 3: Missing OCIO Configuration**
- **Problem**: Colors look wrong or nodes error
- **Solution**: Ensure OCIO environment variable is set

#### **Pitfall 4: Frame Padding Mismatches**
- **Problem**: #### vs %04d confusion
- **Solution**: Standardize on %04d for Nuke

#### **Pitfall 5: Forgetting origset Flag**
- **Problem**: Frame range resets when reloading
- **Solution**: Set `origset true` in Read nodes

### 9. Resolution Detection Pattern

```python
def detect_resolution(path: str) -> tuple[int, int]:
    """Extract resolution from path patterns."""
    # Common patterns: 4312x2304, 1920_1080, etc.
    patterns = [
        r"(\d{3,4})[x](\d{3,4})",   # 1920x1080
        r"(\d{3,4})[_](\d{3,4})",   # 1920_1080
    ]
    
    for pattern in patterns:
        if match := re.search(pattern, path):
            width = int(match.group(1))
            height = int(match.group(2))
            # Sanity check
            if 640 <= width <= 8192 and 480 <= height <= 4320:
                return width, height
    
    return 4312, 2304  # Production default
```

### 10. Undistortion Integration Strategies

#### **Strategy 1: Embedded Nodes (Best for Simple Cases)**
```python
# Read the undistortion file
with open(undist_path, 'r') as f:
    content = f.read()

# Extract LensDistortion nodes
if 'LensDistortion {' in content:
    # Parse and embed the node
    # Wrap in a Group for organization
```

#### **Strategy 2: Import Instructions (Most Flexible)**
```tcl
BackdropNode {
    label "To apply undistortion:\n1. File > Import Script\n2. Navigate to: /path/to/undist.nk\n3. Connect to plate"
}
```

#### **Strategy 3: LiveGroup (Nuke 13+)**
```tcl
LiveGroup {
    file "/path/to/undistortion.nk"
    autolabel "nuke.thisNode().name()"
}
```

### 11. Best Practices Summary

1. **Always validate paths exist** before generating scripts
2. **Use forward slashes** regardless of platform
3. **Set explicit file_type** in Read nodes
4. **Include frame range** even if full sequence
5. **Specify colorspace** explicitly
6. **Add meaningful labels** with expressions
7. **Handle errors gracefully** with on_error knob
8. **Document non-obvious choices** with comments
9. **Test with various file formats** (EXR, DPX, JPEG)
10. **Verify OCIO configuration** matches facility setup

### 12. Debugging Tips

#### **Check Generated Script Syntax**
```bash
# Validate script without opening GUI
nuke -t -x test_script.nk
```

#### **Python REPL Testing**
```python
# Test in Nuke's Script Editor
import nuke
n = nuke.createNode("Read")
n['file'].setValue("/path/to/plate.%04d.exr")
print(n['first'].value())
```

#### **Enable Verbose Logging**
```python
# In generated scripts
print("Loading plate: {}".format(plate_path))
print("Detected frames: {}-{}".format(first, last))
```

### 13. VFX Pipeline Integration

#### **Standard Frame Ranges**
- Film: 1001-2000 (most common)
- Commercials: 0-100 or 1001-1100
- Games: 0-based (0-99)

#### **Plate Naming Conventions**
```
{show}_{sequence}_{shot}_plate_{element}_{colorspace}_v{version}.{frame}.{ext}
Example: PROJ_SEQ01_SH010_plate_BG01_aces_v003.1001.exr
```

#### **Directory Structure**
```
/shows/{show}/shots/{sequence}/{shot}/
    /publish/
        /turnover/
            /plate/
                /input_plate/
                    /{element}/
                        /v{version}/
                            /exr/
                                /{resolution}/
```

### 14. Performance Considerations

- **Proxy Usage**: Always set proxy paths for 4K+ plates
- **Localization**: Use Nuke's localization for network files
- **Frame Step**: Use frame step for initial loading of heavy sequences
- **Region of Interest**: Set ROI for faster processing during setup

### 15. Security and Path Validation

```python
def validate_safe_path(path: str) -> bool:
    """Ensure path is safe to use in scripts."""
    # Prevent injection attacks
    forbidden = ['..', '~', '$', '`', ';', '&&', '||', '>', '<', '|']
    path_str = str(path)
    
    for pattern in forbidden:
        if pattern in path_str:
            return False
    
    # Ensure it's a real path
    return Path(path).exists()
```

## Summary

The most critical learning is that **Read nodes are exclusively for image/video files**, not for importing Nuke scripts. This fundamental misunderstanding can lead to hours of debugging. Always use the appropriate import method for the file type and context (Python API vs static script generation).

When generating Nuke scripts programmatically, remember that you're writing TCL code that will be interpreted by Nuke. This means proper escaping, forward slashes, and explicit configuration of all necessary knobs.

The VFX pipeline has specific conventions and requirements (OCIO, frame ranges, naming) that must be respected for smooth integration.