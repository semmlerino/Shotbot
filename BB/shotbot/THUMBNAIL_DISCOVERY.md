# Enhanced Thumbnail Discovery System

## Overview
ShotBot now features an enhanced thumbnail discovery system that automatically finds and uses thumbnails from multiple sources with intelligent fallback mechanisms.

## Thumbnail Sources

### 1. Editorial Thumbnails (Primary)
**Path Pattern:** `/shows/{show}/shots/{sequence}/{shot}/publish/editorial/cutref/v001/jpg/1920x1080/`
- Standard editorial thumbnails
- Usually JPEG files at 1920x1080 resolution
- Quick to load and display

### 2. Turnover Plate Thumbnails (Fallback)
**Path Pattern:** `/shows/{show}/shots/{sequence}/{shot}/publish/turnover/plate/input_plate/{PLATE}/v001/exr/{resolution}/`
- High-quality EXR plate files
- Automatically discovered when editorial thumbnails unavailable
- First frame of sequence used (e.g., .1001.exr or .0001.exr)

## Plate Preference System

When multiple plates are available, the system selects based on priority:

1. **FG Plates** (Foreground) - Highest Priority
   - FG01, FG02, etc.
   - Used for main action/characters

2. **BG Plates** (Background) - Second Priority
   - BG01, BG02, etc.
   - Used for environment/background

3. **Other Plates** - Lowest Priority
   - EL01 (Element plates)
   - Any other plate types found

## Implementation Details

### Key Components

#### PathUtils.find_turnover_plate_thumbnail()
```python
# Discovers and returns best available plate thumbnail
thumbnail = PathUtils.find_turnover_plate_thumbnail(
    shows_root, show, sequence, shot
)
```

#### Shot.get_thumbnail_path()
```python
# Automatically tries editorial first, then turnover plates
thumbnail = shot.get_thumbnail_path()
```

### Cache Management

#### Large EXR Handling
- Detects large EXR files (>10MB)
- Creates smaller JPEG thumbnails (512x512)
- Higher quality setting (95%) for EXR-derived thumbnails
- Graceful handling of high-resolution plates (up to 20000x20000)

#### Performance Optimizations
- Path caching to reduce filesystem checks
- Limited file scanning (first 10 frames)
- Efficient plate priority sorting
- Atomic cache file operations

## Configuration

### config.py Settings
```python
# Plate discovery priorities (lower value = higher priority)
TURNOVER_PLATE_PRIORITY = {
    "FG": 0,  # Foreground plates highest
    "BG": 1,  # Background plates second
    "EL": 2,  # Element plates third
    "*": 3,   # All others lowest
}

# Image format support
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".tiff", ".tif", ".exr"]
```

## Usage Examples

### Automatic Discovery
```python
# Create a shot object
shot = Shot(
    show="jack_ryan",
    sequence="GG_000",
    shot="0050",
    workspace_path="/shows/jack_ryan/shots/GG_000/GG_000_0050"
)

# Get thumbnail (automatically checks both sources)
thumbnail_path = shot.get_thumbnail_path()
if thumbnail_path:
    print(f"Found thumbnail: {thumbnail_path}")
    # Use thumbnail for display...
```

### Direct Turnover Plate Access
```python
# Find turnover plate thumbnail directly
from utils import PathUtils
from config import Config

turnover_thumb = PathUtils.find_turnover_plate_thumbnail(
    Config.SHOWS_ROOT,
    "jack_ryan",
    "GG_000",
    "0050"
)

if turnover_thumb:
    print(f"Plate: {turnover_thumb.parent.parent.parent.parent.name}")
    print(f"Frame: {turnover_thumb.name}")
```

## File Naming Patterns

### Typical EXR Plate Naming
```
{sequence}_{shot}_turnover-plate_{plate}_{colorspace}_v{version}.{frame}.exr

Examples:
- GG_000_0050_turnover-plate_EL01_lin_sgamut3cine_v001.1001.exr
- GF_256_1200_turnover-plate_FG01_aces_v001.1001.exr
```

### Frame Number Detection
- Supports standard frame patterns: .1001.exr, .0001.exr
- Automatically selects lowest frame number
- Regex pattern: `\.(\d{4})\.exr$`

## Troubleshooting

### EXR Files Not Loading
1. **Check Qt imageformats plugin**
   - PySide6 needs imageformats plugin for EXR support
   - Install: `pip install PySide6-essentials`

2. **File Size Issues**
   - Files >25MB may take time to load
   - Cache system creates smaller thumbnails after first load

3. **Permission Errors**
   - Ensure read access to turnover directories
   - Check filesystem permissions

### No Thumbnails Found
1. **Verify Path Structure**
   - Check both editorial and turnover paths exist
   - Confirm plate directories follow naming convention

2. **Check Configuration**
   - Verify SHOWS_ROOT is set correctly
   - Ensure IMAGE_EXTENSIONS includes needed formats

3. **Enable Debug Logging**
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

## Performance Considerations

### Startup Performance
- Cached thumbnails load instantly
- First-time EXR loading may be slower
- 24-hour cache persistence reduces repeated processing

### Memory Management
- Large EXR files processed with care
- Automatic thumbnail scaling to 512x512
- Memory tracking and eviction for cache

### Network/Storage Impact
- Limited to first 10 frames per directory
- Path existence cached for 5 minutes
- Efficient plate discovery with early termination

## Benefits

1. **Automatic Fallback** - Never miss thumbnails when available
2. **High Quality** - Uses best available source (EXR plates)
3. **Performance** - Intelligent caching and optimization
4. **Flexibility** - Configurable plate preferences
5. **Robustness** - Graceful handling of large files and errors

## Future Enhancements

Potential improvements for consideration:
- Support for additional plate locations
- Configurable frame selection (middle frame, last frame)
- HDR thumbnail generation from EXR
- Parallel plate discovery for faster scanning
- User-configurable plate preferences per show