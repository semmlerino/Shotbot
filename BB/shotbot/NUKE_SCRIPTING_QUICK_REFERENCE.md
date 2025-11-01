# Nuke Scripting Quick Reference

## 🚨 Most Important Rule
**Read nodes are for IMAGES ONLY** (EXR, JPEG, DPX, etc.)  
**NOT for .nk scripts!** Use `nuke.nodePaste()` or embed content instead.

## 🎬 Common Tasks

### Load Image Sequence
```tcl
Read {
    file "/path/to/plate.%04d.exr"
    first 1001
    last 1100
    colorspace "ACES - ACEScg"
    name Read_Plate
}
```

### Import Nuke Script (Python API)
```python
# Inside Nuke
nuke.nodePaste('/path/to/script.nk')
```

### Import Nuke Script (Static Generation)
```python
# Read and embed the content
with open('script.nk', 'r') as f:
    script_content = f.read()
# Then include in your generated script
```

### Path Conversion
```python
# Always convert to forward slashes
nuke_path = windows_path.replace("\\", "/")
```

### Frame Pattern Conversion
```python
# Convert #### to %04d for Nuke
nuke_pattern = pattern.replace("####", "%04d")
```

## 📊 Node Type Cheat Sheet

| File Type | Node to Use | Example |
|-----------|------------|---------|
| `.exr`, `.jpg`, `.png` | `Read` | `Read { file "plate.%04d.exr" }` |
| `.mov`, `.mp4` | `Read` | `Read { file "video.mov" }` |
| `.nk` script | `nuke.nodePaste()` | `nuke.nodePaste("script.nk")` |
| `.gizmo` | `nuke.load()` | `nuke.load("MyGizmo")` |
| `.obj`, `.abc` | `ReadGeo` | `ReadGeo { file "model.abc" }` |
| `.chan` | `Camera` | `Camera { read_from_file true }` |

## 🎨 Colorspace Quick Reference

| Pattern in Filename | OCIO Colorspace |
|--------------------|-----------------|
| `aces`, `acescg` | `"ACES - ACEScg"` |
| `lin_sgamut3cine` | `"Input - Sony - S-Gamut3.Cine - Linear"` |
| `rec709` | `"Output - Rec.709"` |
| `srgb` | `"Output - sRGB"` |
| `linear`, `lin_` | `"scene_linear"` |

## 🔧 Essential Read Node Knobs

```tcl
Read {
    # Required
    file "/path/to/images.%04d.exr"
    
    # Frame Range
    first 1001
    last 1100
    origfirst 1001
    origlast 1100
    origset true
    
    # Format
    format "4312 2304 0 0 4312 2304 1"
    
    # Color
    colorspace "ACES - ACEScg"
    premultiplied true
    auto_alpha true
    
    # Error Handling
    on_error black  # or "checkerboard"
}
```

## 📁 Path Patterns

### VFX Standard Paths
```
/shows/{show}/shots/{seq}/{shot}/publish/turnover/plate/
```

### Frame Padding Examples
```
plate.1001.exr      → single frame
plate.####.exr      → plate.1001.exr, plate.1002.exr
plate.%04d.exr      → same as above (Nuke preferred)
plate.######.exr    → 6-digit padding
plate.%06d.exr      → 6-digit (Nuke preferred)
```

## ⚡ Python API vs Static Scripts

### Python API (Inside Nuke)
```python
# Create nodes dynamically
read = nuke.nodes.Read(file="/path/to/plate.%04d.exr")
read['first'].setValue(1001)
read['last'].setValue(1100)

# Import scripts
nuke.nodePaste("/path/to/script.nk")
nuke.scriptSource("/path/to/script.nk")
```

### Static Script Generation
```python
# Generate TCL text
script = """Read {
    file "/path/to/plate.%04d.exr"
    first 1001
    last 1100
}"""

# Save to file
with open("output.nk", "w") as f:
    f.write(script)
```

## 🚫 Common Mistakes to Avoid

1. ❌ Using `Read` for .nk files
2. ❌ Backslashes in file paths  
3. ❌ Missing `origset true` flag
4. ❌ Wrong colorspace names
5. ❌ Using `####` instead of `%04d`
6. ❌ Not escaping special characters
7. ❌ Forgetting `file_type` specification

## ✅ Correct OCIO Setup

```tcl
Root {
    colorManagement OCIO
    OCIO_config aces_1.2
    workingSpaceLUT "ACES - ACEScg"
    monitorLut "Rec.709 (ACES)"
}
```

## 🔍 Debug Commands

```bash
# Validate script syntax
nuke -t -x script.nk

# Run script in terminal mode
nuke -t script.nk

# Check available OCIO configs
echo $OCIO
```

## 📝 Label Expressions

```tcl
# Show colorspace and frame range
label "\\[value colorspace]\\nframes: \\[value first]-\\[value last]"

# Show file name
label "\\[file tail \\[value file]]"

# Show resolution
label "\\[value width]x\\[value height]"
```

## 🎯 Remember

- **Forward slashes** always (even on Windows)
- **%04d** not #### for Nuke
- **Read nodes** for images only
- **nodePaste()** for importing scripts
- **OCIO config** must match facility
- **origset true** to preserve frame range