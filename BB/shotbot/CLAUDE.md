# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ShotBot is a PySide6-based GUI application for VFX shot browsing and application launching. It integrates with VFX pipeline tools using the `ws` (workspace) command to list and navigate shots. The application provides a visual interface for artists to browse shots, view thumbnails, and launch VFX applications in the correct shot context.

## Commands

### Running the Application
```bash
# Using virtual environment (recommended)
source venv/bin/activate
python shotbot.py

# Or in rez environment
rez env PySide6_Essentials pillow Jinja2 -- python3 shotbot.py

# Debug mode for verbose logging
SHOTBOT_DEBUG=1 python shotbot.py
```

### Testing
**IMPORTANT**: Always use the `run_tests.py` script, never run pytest directly:

```bash
# Run all tests
python run_tests.py

# Run specific test file
python run_tests.py tests/unit/test_shot_model.py

# Run specific test method
python run_tests.py tests/unit/test_shot_model.py::TestShot::test_shot_creation

# Run with coverage report
python run_tests.py --cov

# Run tests matching a pattern
python run_tests.py -k "test_cache"
```

### Code Quality
```bash
# Activate virtual environment first
source venv/bin/activate

# Format code with ruff
ruff format .

# Check for linting issues
ruff check .

# Fix linting issues automatically
ruff check --fix .

# Type checking
basedpyright
```

### Setting Up Development Environment
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install runtime dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -r requirements-dev.txt
```

## Architecture

### Core System Design

The application follows a Model-View architecture with Qt's signal-slot mechanism for loose coupling:

1. **Data Layer**: Models (`shot_model.py`, `threede_scene_model.py`) handle data fetching and caching
2. **View Layer**: Grid widgets (`shot_grid.py`, `threede_shot_grid.py`) display thumbnails
3. **Control Layer**: Launchers (`command_launcher.py`, `launcher_manager.py`) execute applications
4. **Cache Layer**: `cache_manager.py` manages persistent caching with TTL

### Key Components

#### Main Application
- **`shotbot.py`**: Entry point and application initialization
- **`main_window.py`**: Main window with tabbed interface, integrates all components
- **`config.py`**: Centralized configuration constants (paths, timeouts, defaults)

#### Shot Management
- **`shot_model.py`**: Parses `ws -sg` output, manages shot list with caching
- **`shot_grid.py`**: Thumbnail grid for "My Shots" tab
- **`shot_info_panel.py`**: Displays current shot details and thumbnail
- **`thumbnail_widget.py`**: Individual thumbnail with selection effects

#### 3DE Scene Discovery
- **`threede_scene_finder.py`**: Recursive .3de file discovery in user directories
- **`threede_scene_model.py`**: Model for 3DE scenes with user exclusion
- **`threede_shot_grid.py`**: Grid widget for "Other 3DE scenes" tab
- **`threede_scene_worker.py`**: Background worker thread for scene discovery

#### Custom Launcher System
- **`launcher_manager.py`**: Business logic for custom launchers with thread safety
- **`launcher_dialog.py`**: UI for creating/editing custom launchers
- **`launcher_config.py`**: Configuration for launcher templates
- **`LauncherWorker`**: QThread-based worker for non-blocking command execution
- **`terminal_launcher.py`**: Terminal-based command execution

#### Utilities
- **`utils.py`**: Centralized utilities for path operations, validation, and caching
- **`cache_manager.py`**: TTL-based caching with QPixmap resource cleanup
- **`log_viewer.py`**: Command history viewer
- **`raw_plate_finder.py`**: Discovers raw plate sequences
- **`undistortion_finder.py`**: Finds undistortion .nk files

### Critical Implementation Details

#### Workspace Command (`ws`)
The `ws` command is a **shell function**, not an executable. Must use interactive bash:
```python
subprocess.run(["/bin/bash", "-i", "-c", "ws -sg"], ...)
```

#### QSettings Storage
QByteArray to hex string conversion for geometry storage:
```python
# Correct: Use .data().decode('ascii')
hex_string = byte_array.data().decode('ascii')
# NOT: str(byte_array) or byte_array.hex()
```

#### Thread Safety in LauncherManager
The custom launcher system uses thread-safe process management:
- `threading.RLock()` protects `_active_processes` dictionary
- Unique process keys with timestamp + UUID prevent collisions
- `LauncherWorker` QThread for non-blocking execution

#### Change Detection
`refresh_shots()` returns a tuple for efficient UI updates:
```python
success, has_changes = shot_model.refresh_shots()
if success and has_changes:
    # Update UI only when needed
```

#### Resource Management
- QPixmap cleanup in `cache_manager.py` prevents memory leaks
- 30-second subprocess timeout prevents hangs
- Proper QThread cleanup with `quit()` and `wait()`

### Signal-Slot Communication

Key signals used throughout the application:
- `shot_model.shots_updated`: Emitted when shot list changes
- `launcher_manager.command_started/finished/output`: Launcher execution events
- `threede_worker.scene_found/scan_progress/scan_finished`: 3DE discovery events
- `thumbnail_widget.shot_selected/shot_double_clicked`: User interaction

### Caching Strategy

- **Shot List**: 30-minute TTL, refreshes every 5 minutes if changed
- **Thumbnails**: Permanent cache, QPixmap resources cleaned up on deletion
- **3DE Scenes**: 30-minute TTL with background refresh
- **Path Validation**: 60-second TTL to reduce filesystem checks

## Common Development Tasks

### Adding a New Application Launcher
Edit the `APPS` dictionary in `config.py`:
```python
APPS = {
    "3de": "3de",
    "nuke": "nuke",
    "maya": "maya",
    "your_app": "your_command",  # Add here
}
```

### Creating a Custom Launcher
Use the `LauncherManager` API:
```python
launcher = CustomLauncher(
    id="my_launcher",
    name="My Tool",
    command="my_command {shot_name}",
    icon="path/to/icon.png"
)
manager.create_launcher(launcher)
```

### Debugging Issues

1. **Enable debug logging**: `SHOTBOT_DEBUG=1 python shotbot.py`
2. **Check process output**: View command history in log viewer
3. **Test workspace command**: `bash -i -c "ws -sg"` in terminal
4. **Verify paths**: Check `utils.py` path validation with debug mode

## Testing Guidelines

### Test Organization
- `tests/unit/`: Unit tests for individual components
- `tests/integration/`: Integration tests for component interactions
- `run_tests.py`: Test runner with proper Qt initialization

### Writing Tests
```python
# Use pytest-qt fixtures
def test_shot_model(qtbot):
    model = ShotModel()
    qtbot.addWidget(model)  # Ensures cleanup
    
    # Test with signals
    with qtbot.waitSignal(model.shots_updated, timeout=1000):
        model.refresh_shots()
```

### Common Test Issues
- **Qt platform errors**: Always use `run_tests.py`, not direct pytest
- **Timeouts**: WSL requires xvfb plugin disabled (handled by runner)
- **Signal testing**: Use `qtbot.waitSignal()` for async operations

## Performance Considerations

### UI Responsiveness
- Background workers for long operations (3DE scanning, shot refresh)
- Adaptive timer intervals based on activity
- Thumbnail loading happens asynchronously

### Memory Management
- QPixmap cache cleanup prevents leaks
- Process output buffering with line-by-line reading
- TTL-based path validation cache reduces filesystem access

### Concurrent Operations
- Thread-safe launcher management with RLock
- Multiple launchers can run simultaneously
- Worker threads for non-blocking operations

## Recent Enhancements

### Custom Launcher System (Latest)
- Thread-safe concurrent launcher execution
- Worker threads prevent UI freezing
- Unique process tracking with timestamp + UUID keys
- Comprehensive process state management
- Real-time output streaming from launched applications

### 3DE Scene Discovery
- Flexible recursive search (no path requirements)
- Intelligent plate name extraction from any path structure
- Automatic user exclusion (current user filtered out)
- Background scanning with progress reporting

### Code Quality Improvements
- Comprehensive error handling and logging
- Resource management with guaranteed cleanup
- Centralized utilities in `utils.py`
- Type hints and documentation throughout
- Performance optimizations with caching

## Critical Fixes (2025-08-07)

### Raw Plate Finder Enhancements
- **Flexible plate discovery**: Now supports FG01, BG01, bg01, and any plate naming pattern
- **Dynamic color space detection**: Automatically detects color spaces from actual files (aces, lin_sgamut3cine, etc.)
- **Priority-based selection**: Configurable plate priorities (BG01 > FG01 by default)
- **Performance optimization**: Pre-compiled regex patterns outside loops
- **BREAKING CHANGE**: `PathUtils.build_raw_plate_path()` now returns base path without plate name

### UI Freezing Prevention
- **Non-blocking folder opening**: Uses `QRunnable` worker thread to prevent UI freezing
- **Proper file:/// URL generation**: Fixed URL format for all platforms
- **Error handling**: Graceful fallback to system commands if Qt method fails
- **Cross-platform support**: Works on Linux, macOS, and Windows

### 3DE Scene Improvements
- **Deduplication**: Shows only one 3DE scene per shot (latest by mtime)
- **Persistent caching**: Cache properly refreshes TTL and persists across restarts
- **Smart selection**: Prioritizes scenes by modification time and plate type

### Type Safety and Compatibility
- **Python 3.8 compatibility**: Fixed type annotations (tuple → Tuple)
- **Optimized pattern matching**: Pre-computed uppercase pattern sets for O(1) lookup
- **Improved error handling**: Added proper exception handling for filesystem operations

## Critical Fixes (2025-08-12)

### Nuke Script Generator Colorspace Fix
- **Colorspace Quoting Issue**: Fixed critical bug where colorspace values containing spaces were not properly quoted in generated Nuke scripts
- **Root Cause**: Colorspace names like "Input - Sony - S-Gamut3.Cine - Linear" were inserted as unquoted strings (`colorspace Input - Sony - S-Gamut3.Cine - Linear`), causing Nuke to parse them as multiple arguments
- **Solution**: Properly quote colorspace values in Read node templates (`colorspace "Input - Sony - S-Gamut3.Cine - Linear"`)
- **VFX Pipeline Impact**: This fix is critical for production workflows using modern ACES colorspaces with complex naming conventions that include spaces and special characters
- **Error Prevention**: Eliminates "no such knob" errors that would prevent Nuke scripts from loading correctly with auto-detected colorspaces

#### Technical Details
The fix addresses script generation in two methods:
```python
# Before (problematic)
colorspace {colorspace}

# After (fixed)  
colorspace "{colorspace}"
```

This ensures that colorspace values detected from plate paths (such as ACES, Sony S-Gamut3.Cine, etc.) are properly handled as single string parameters in the generated .nk files. The fix maintains backward compatibility with simple colorspace names while enabling support for modern VFX pipeline colorspace naming conventions.

#### Additional Improvements
- **Temporary File Management**: Added automatic cleanup tracking for generated .nk files to prevent disk space leaks
- **Security Enhancement**: Shot name sanitization to prevent path traversal attacks in temporary file creation
- **Resource Management**: Proper file handle cleanup with exit handlers for robust temporary file management

## Type System Improvements (2025-08-08)

### Enhanced Type Safety Architecture
ShotBot now features comprehensive type safety with complete type annotations across all modules. The type system improvements provide better IDE support, runtime safety, and maintainable code.

#### Key Type System Features:
- **NamedTuple Migration**: Replaced ambiguous tuple returns with self-documenting NamedTuple types
- **Union Type Safety**: Flexible APIs accepting both str and Path objects with proper type guards
- **Optional Type Handling**: Comprehensive handling of nullable Qt widget types
- **Generic Type Constraints**: Proper type bounds for container types and callable interfaces
- **Protocol-Based Design**: Duck typing interfaces for extensible component architecture

### RefreshResult NamedTuple
The `RefreshResult` type replaces tuple returns for better type safety and code clarity:

```python
# Before: Ambiguous tuple return
def refresh_shots() -> tuple[bool, bool]:
    # Which bool means what?
    return success, has_changes

# After: Self-documenting NamedTuple
class RefreshResult(NamedTuple):
    success: bool      # Operation completed successfully
    has_changes: bool  # Shot list actually changed

def refresh_shots() -> RefreshResult:
    return RefreshResult(success=True, has_changes=False)

# Usage with tuple unpacking or attribute access
result = shot_model.refresh_shots()
success, has_changes = result  # Tuple unpacking still works
if result.success and result.has_changes:  # Clear attribute access
    update_ui()
```

### Type-Safe Path Handling
Utilities accept flexible path types while maintaining type safety:

```python
# Union types for flexible API
def find_files_by_extension(
    directory: Union[str, Path],
    extensions: Union[str, List[str]],
    limit: Optional[int] = None,
) -> List[Path]:
    # Handles both string and Path objects seamlessly
    
# Usage examples
files1 = FileUtils.find_files_by_extension("/tmp", "txt")
files2 = FileUtils.find_files_by_extension(Path("/tmp"), ["jpg", "png"])
```

### Typed Properties and Configuration
Configuration properties use proper type annotations with delegation:

```python
class CacheManager(QObject):
    @property
    def CACHE_THUMBNAIL_SIZE(self) -> int:
        """Type-safe access to configuration values."""
        return Config.CACHE_THUMBNAIL_SIZE
    
    @property  
    def CACHE_EXPIRY_MINUTES(self) -> int:
        """Returns cache TTL with proper type annotation."""
        return Config.CACHE_EXPIRY_MINUTES
```

### Signal Type Declarations
Qt signals include proper type information:

```python
class ShotModel(QObject):
    # Typed signals for better IDE support
    shots_updated = Signal()           # No parameters
    shot_selected = Signal(str)        # Single string parameter
    progress_updated = Signal(dict)    # Dictionary parameter
```

## Type Checking Configuration

### basedpyright Setup
The project uses basedpyright for comprehensive type checking:

```bash
# Install basedpyright
pip install basedpyright

# Run type checking
basedpyright

# With WSL compatibility
basedpyright --typeshedpath venv/lib/python3.12/site-packages/basedpyright/dist/typeshed-fallback
```

### Type Checking Commands
```bash
# Activate virtual environment
source venv/bin/activate

# Full type check with zero errors target
basedpyright --typeCheckingMode=basic

# Check specific module
basedpyright main_window.py

# Generate type coverage report
basedpyright --stats
```

### Development Workflow Integration
```bash
# Pre-commit type checking
basedpyright && ruff check . && ruff format .

# CI/CD pipeline integration
- name: Type Check
  run: |
    source venv/bin/activate
    basedpyright --typeCheckingMode=basic
```

## Type Safety Best Practices

### NamedTuple vs DataClass
- **NamedTuple**: For immutable return types and simple data containers
- **DataClass**: For mutable objects with methods and complex initialization

```python
# NamedTuple for operation results
class RefreshResult(NamedTuple):
    success: bool
    has_changes: bool

# DataClass for complex entities  
@dataclass
class Shot:
    show: str
    sequence: str
    shot: str
    workspace_path: str
```

### Optional Type Patterns
Proper handling of nullable Qt objects:

```python
class MainWindow(QMainWindow):
    def __init__(self, cache_manager: Optional[CacheManager] = None):
        self.cache_manager = cache_manager or CacheManager()
        
    def get_selected_shot(self) -> Optional[Shot]:
        # Clear return type for nullable results
        if not self.current_shot:
            return None
        return self.current_shot
```

### Union Type Design
Flexible APIs with clear type constraints:

```python
# Accept multiple path types
PathType = Union[str, Path]

def build_path(base_path: PathType, *segments: str) -> Path:
    # Type-safe path construction
    path = Path(base_path)  # Handles both str and Path
    return path / Path(*segments)
```

## Type Documentation Standards

### Google Style Type Documentation
All type-annotated methods include comprehensive docstrings:

```python
def find_files_by_extension(
    directory: Union[str, Path],
    extensions: Union[str, List[str]], 
    limit: Optional[int] = None,
) -> List[Path]:
    """Find files with specific extensions in a directory.
    
    Args:
        directory: Directory path to search. Accepts both string paths
            and pathlib.Path objects for flexibility.
        extensions: File extension(s) to match. Can be a single extension
            string or list of extensions. Leading dots are optional.
        limit: Maximum number of matching files to return. If None,
            returns all matching files.
            
    Returns:
        List[Path]: List of pathlib.Path objects for all matching files.
            Returns empty list if directory doesn't exist.
            
    Examples:
        >>> files = FileUtils.find_files_by_extension("/tmp", "txt")
        >>> images = FileUtils.find_files_by_extension(
        ...     Path("/images"), ["jpg", "jpeg", "png"], limit=10
        ... )
    """
```

### Module Documentation
Each module includes comprehensive type system information:

```python
"""Module docstring with type safety information.

Type Safety:
    This module uses comprehensive type annotations with Optional types for
    nullable Qt widgets and proper signal type declarations. All public methods
    include full type hints for parameters and return values.
    
Examples:
    Type-safe usage patterns:
        >>> from module import TypedClass
        >>> instance = TypedClass(param="value")
        >>> result: ResultType = instance.method()
"""
```

The type system improvements provide a solid foundation for maintaining code quality and preventing runtime errors through static analysis.

## Practical Type Safety Examples

### Working with RefreshResult
The RefreshResult NamedTuple provides clear, type-safe operation results:

```python
# In shot_model.py
def refresh_shots(self) -> RefreshResult:
    try:
        # Execute workspace command and parse results
        success = self._fetch_shots_from_workspace()
        has_changes = self._detect_changes()
        return RefreshResult(success=success, has_changes=has_changes)
    except Exception as e:
        logger.error(f"Shot refresh failed: {e}")
        return RefreshResult(success=False, has_changes=False)

# In main_window.py - handling results
def on_refresh_shots(self):
    result = self.shot_model.refresh_shots()
    
    # Tuple unpacking (backwards compatible)
    success, has_changes = result
    
    # Or attribute access (more explicit)
    if result.success:
        self.status_bar.showMessage("Shots refreshed successfully")
        if result.has_changes:
            self.shot_grid.update_shots(self.shot_model.get_shots())
            logger.info(f"Updated UI with {len(self.shot_model.get_shots())} shots")
        else:
            logger.debug("Shot list unchanged, skipping UI update")
    else:
        self.status_bar.showMessage("Failed to refresh shots")
        QMessageBox.warning(self, "Refresh Error", "Unable to fetch shot data")
```

### Type-Safe Path Operations
Union types enable flexible path handling while maintaining type safety:

```python
# In utils.py - accepting both str and Path
def build_thumbnail_path(
    shows_root: Union[str, Path], 
    show: str, 
    sequence: str, 
    shot: str
) -> Path:
    """Type-safe path construction with flexible input types."""
    base = Path(shows_root) if isinstance(shows_root, str) else shows_root
    return base / show / "shots" / sequence / shot / "publish" / "editorial"

# Usage examples - both work identically
thumbnail_path1 = PathUtils.build_thumbnail_path("/shows", "project", "seq01", "shot01")
thumbnail_path2 = PathUtils.build_thumbnail_path(Path("/shows"), "project", "seq01", "shot01")

# Type checker ensures Path return type
assert isinstance(thumbnail_path1, Path)
assert isinstance(thumbnail_path2, Path)
```

### Qt Widget Type Safety
Proper Optional handling for nullable Qt widgets:

```python
class MainWindow(QMainWindow):
    def __init__(self, cache_manager: Optional[CacheManager] = None):
        super().__init__()
        # Type-safe default parameter handling
        self.cache_manager = cache_manager or CacheManager()
        
        # Optional widget references with proper typing
        self.current_shot_widget: Optional[QWidget] = None
        self.progress_dialog: Optional[QProgressDialog] = None
    
    def show_shot_details(self, shot: Shot) -> None:
        """Display shot details with type-safe widget handling."""
        # Clean up existing widget
        if self.current_shot_widget is not None:
            self.current_shot_widget.deleteLater()
            self.current_shot_widget = None
            
        # Create new widget with proper type annotation
        details_widget: QWidget = self._create_shot_details_widget(shot)
        self.current_shot_widget = details_widget
        self.setCentralWidget(details_widget)
    
    def get_selected_shot(self) -> Optional[Shot]:
        """Get currently selected shot with clear nullable return."""
        if hasattr(self, 'shot_grid') and self.shot_grid.current_selection:
            return self.shot_grid.current_selection
        return None  # Explicit None for clarity
```

### Signal/Slot Type Safety
Type-annotated signals provide better IDE support and runtime validation:

```python
class ShotModel(QObject):
    # Typed signal declarations
    shots_updated = Signal()                    # No parameters
    shot_selected = Signal(str)                 # Shot name
    progress_updated = Signal(int)              # Progress percentage  
    error_occurred = Signal(str, str)           # Error type, message
    
    def emit_progress(self, percentage: int) -> None:
        """Type-safe signal emission."""
        assert 0 <= percentage <= 100, f"Invalid progress: {percentage}"
        self.progress_updated.emit(percentage)
    
    def connect_signals(self, main_window: 'MainWindow') -> None:
        """Type-safe signal connections."""
        # Connect with proper type checking
        self.shots_updated.connect(main_window.on_shots_updated)
        self.shot_selected.connect(main_window.on_shot_selected)
        self.progress_updated.connect(main_window.update_progress_bar)
        self.error_occurred.connect(main_window.handle_error)

# In MainWindow class
def on_shot_selected(self, shot_name: str) -> None:
    """Handle shot selection with type-safe parameter."""
    logger.info(f"Shot selected: {shot_name}")
    shot = self.shot_model.get_shot_by_name(shot_name)
    if shot is not None:
        self.show_shot_details(shot)

def update_progress_bar(self, percentage: int) -> None:
    """Update progress bar with type validation."""
    if hasattr(self, 'progress_bar'):
        self.progress_bar.setValue(percentage)
```

### Cache Manager Type Safety
Type-safe caching with proper resource management:

```python
class CacheManager(QObject):
    def cache_thumbnail(
        self, 
        shot: Shot, 
        image_path: Union[str, Path]
    ) -> Optional[QPixmap]:
        """Cache thumbnail with type-safe path handling and resource management.
        
        Args:
            shot: Shot object for cache key generation
            image_path: Path to source image (str or Path accepted)
            
        Returns:
            Optional[QPixmap]: Cached pixmap or None if caching failed
        """
        try:
            # Convert to Path for consistent handling
            source_path = Path(image_path)
            if not source_path.exists():
                logger.warning(f"Source image not found: {source_path}")
                return None
            
            # Generate cache key from shot data
            cache_key = f"{shot.show}_{shot.sequence}_{shot.shot}"
            
            # Load and cache pixmap with memory tracking
            pixmap = QPixmap(str(source_path))
            if not pixmap.isNull():
                self._memory_usage_bytes += pixmap.sizeInBytes()
                self._cached_pixmaps[cache_key] = pixmap
                logger.debug(f"Cached thumbnail for {cache_key}: {pixmap.size()}")
                return pixmap
            
            return None
            
        except Exception as e:
            logger.error(f"Thumbnail caching failed: {e}")
            return None
    
    def get_cached_thumbnail(self, shot: Shot) -> Optional[QPixmap]:
        """Retrieve cached thumbnail with type-safe return."""
        cache_key = f"{shot.show}_{shot.sequence}_{shot.shot}"
        return self._cached_pixmaps.get(cache_key)
```

### Development Workflow Integration
Complete type checking workflow for development:

```bash
#!/bin/bash
# development_check.sh - Comprehensive development workflow

echo "🔍 Running comprehensive code quality checks..."

# Activate virtual environment
source venv/bin/activate

# 1. Type checking with basedpyright (zero errors target)
echo "📝 Type checking..."
basedpyright --typeCheckingMode=basic
if [ $? -ne 0 ]; then
    echo "❌ Type checking failed"
    exit 1
fi

# 2. Linting with ruff
echo "🔧 Linting..."  
ruff check .
if [ $? -ne 0 ]; then
    echo "❌ Linting failed"
    exit 1
fi

# 3. Format checking
echo "🎨 Format checking..."
ruff format --check .
if [ $? -ne 0 ]; then
    echo "❌ Format checking failed - run 'ruff format .' to fix"
    exit 1
fi

# 4. Run tests with proper Qt setup
echo "🧪 Running tests..."
python run_tests.py
if [ $? -ne 0 ]; then
    echo "❌ Tests failed"
    exit 1
fi

echo "✅ All checks passed! Code is ready for commit."
```

This comprehensive type safety system ensures code reliability, improves development experience, and enables confident refactoring while maintaining backwards compatibility.