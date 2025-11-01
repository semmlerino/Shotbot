# Nuke Script Generator Fix Summary

## Critical Issues Fixed

### 1. ❌ **CRITICAL ERROR: Wrong Node Type for .nk Import**
**Previous (Incorrect):**
```python
Read_File_1 {
 inputs 0  
 file {undistortion_path}
 file_type nk  # ❌ WRONG! Read nodes are for images, not scripts!
 name undistortion_import
}
```

**Fixed (Correct):**
- Removed incorrect `Read_File_1` node attempt
- Added proper instructions via `BackdropNode` and `StickyNote`
- Attempts to embed `LensDistortion` nodes directly in a `Group`
- Provides manual import instructions as fallback

### 2. ✅ **Proper Read Node Syntax**
The Read node now includes all required knobs properly:
```python
Read {
 inputs 0
 file_type exr
 file "{nuke_path}"  # Properly escaped path
 format "{width} {height} 0 0 {width} {height} 1 square_pixels"
 proxy "{nuke_path}"
 first {first_frame}
 last {last_frame}
 origfirst {first_frame}
 origlast {last_frame}
 origset true
 on_error black
 reload 0
 auto_alpha true
 premultiplied true
 raw false
 colorspace {colorspace}
 name Read_Plate
 label "\\[value colorspace]\\nframes: {first_frame}-{last_frame}"
}
```

## Key Improvements

### Path Handling
- **Cross-platform compatibility**: Converts backslashes to forward slashes
- **Pattern conversion**: Handles both `####` and `%04d` formats
- **Path escaping**: Proper escaping for Nuke script syntax

### Frame Detection
- **Smart regex matching**: Detects actual frame numbers from files
- **Default fallback**: Uses VFX standard 1001-1100 if detection fails
- **Pattern flexibility**: Works with various naming conventions

### Colorspace Detection
Automatically detects from filename patterns:
- `aces` → `"ACES - ACEScg"`
- `lin_sgamut3cine` → `"Input - Sony - S-Gamut3.Cine - Linear"`
- `rec709` → `"Output - Rec.709"`
- `srgb` → `"Output - sRGB"`
- Default → `"scene_linear"`

### Resolution Detection
- Finds patterns like `4312x2304` or `1920x1080` in paths
- Validates reasonable resolution ranges
- Falls back to production default (4312x2304)

### OCIO Configuration
Proper ACES 1.2 configuration:
```python
colorManagement OCIO
OCIO_config aces_1.2
defaultViewerLUT "OCIO LUTs"
workingSpaceLUT "ACES - ACEScg"
monitorLut "Rec.709 (ACES)"
```

## Undistortion Integration

### Three-Tier Approach:
1. **Visual Indicators**: Adds `StickyNote` and `BackdropNode` with instructions
2. **Automatic Embedding**: Attempts to extract and embed `LensDistortion` nodes
3. **Manual Import**: Provides clear path and instructions for manual import

### Example Generated Instructions:
```
UNDISTORTION AVAILABLE
To apply undistortion:
1. File > Import Script
2. Navigate to: /path/to/undistortion.nk
3. Connect to plate
```

## API Reference

### Correct Ways to Import .nk Files in Nuke:

**Python API (when in Nuke):**
```python
# Method 1: Node paste
nuke.nodePaste('/path/to/script.nk')

# Method 2: Load as toolset
nuke.loadToolset('/path/to/script.nk')

# Method 3: Script source
nuke.scriptSource('/path/to/script.nk')
```

**Static Script Generation:**
- Must read .nk file content and embed nodes directly
- Cannot use Read nodes for .nk files
- Can use Group nodes to organize imported content

## Testing Recommendations

1. **Test with various plate formats**: EXR, JPEG, DPX
2. **Verify frame range detection**: Different padding (####, %04d, %06d)
3. **Check colorspace mapping**: Ensure OCIO configs work
4. **Validate undistortion import**: Manual and automatic methods
5. **Cross-platform testing**: Windows paths with backslashes

## Files Modified

- `nuke_script_generator.py` - Complete rewrite with proper node handling
- Original backed up to: `archived/backup_versions/nuke_script_generator_original.py`

## Impact

This fix resolves critical issues preventing plates from loading correctly in Nuke, especially when combined with undistortion workflows. The generated scripts now follow Nuke's proper node syntax and TCL conventions.