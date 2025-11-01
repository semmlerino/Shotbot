# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Core Application Architecture

PyFFMPEG is a PySide6-based GUI application for batch video conversion using FFmpeg. The application has been refactored from a monolithic design into focused, composable modules:

### Primary Architecture (Refactored Components)
- **`main_window_refactored.py`**: Simplified main window using component coordination. Reduced from 1393 lines to 371 lines while preserving all functionality through signal-slot architecture.
- **`conversion_controller.py`**: Core conversion logic and process orchestration (219 lines). Handles auto-balance workload between GPU/CPU encoders and conversion workflow management.
- **`settings_panel.py`**: Complete UI controls and settings management (419 lines). Maintains all codec options with comprehensive type safety and validation.
- **`process_monitor.py`**: Real-time process monitoring and progress display (312 lines). Creates and manages process progress widgets with proper lifecycle management.
- **`config.py`**: Centralized configuration constants eliminating magic numbers throughout the codebase. Contains ProcessConfig, UIConfig, LogConfig, EncodingConfig, HardwareConfig, and AppConfig classes.

### Supporting Modules
- **`process_manager.py`**: `ProcessManager` class handles FFmpeg process creation, monitoring, and lifecycle management. Emits signals for UI updates with enhanced timer management.
- **`progress_tracker.py`**: `ProcessProgressTracker` class parses FFmpeg output to calculate progress percentages and ETAs using regex patterns with smoothing algorithms.
- **`codec_helpers.py`**: `CodecHelpers` static class with caching for expensive operations. Provides codec selection, hardware acceleration detection, and encoder configuration utilities.
- **`file_list_widget.py`**: `FileListWidget` extends QListWidget with drag-and-drop support, status tracking, progress display, and comprehensive method implementation.

### Legacy Module
- **`PyMPEG.py`**: Original monolithic main window (1393 lines). Kept for reference but excluded from type checking. Use `main_window_refactored.py` for new development.

### Key Features
- Hardware-accelerated encoding (NVENC, QSV, VAAPI)
- Parallel processing with load balancing between GPU and CPU encoders
- Real-time progress tracking with ETA calculations
- Support for multiple codecs: H.264, HEVC, AV1, ProRes
- Smart buffer mode for performance optimization
- Auto-balance feature for hybrid GPU/CPU encoding workloads

## Development Commands

### Running the Application
```bash
# Run the refactored version (recommended)
python main_window_refactored.py

# Run the legacy version (for comparison)
python PyMPEG.py
```

### Development Environment Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install PySide6
```

### Code Quality and Type Checking
```bash
# Install development tools
pip install ruff basedpyright

# Run linting and formatting from virtual environment
./venv/bin/ruff check .
./venv/bin/ruff format .

# Run type checking (configured for refactored modules only) from virtual environment
./venv/bin/basedpyright --typeshedpath venv/lib/python3.12/site-packages/basedpyright/dist/typeshed-fallback
```

### Dependencies
The application requires:
- Python 3.8+ (developed with 3.12)
- PySide6 (Qt for Python)
- FFmpeg (must be in PATH)
- Optional: nvidia-smi for GPU detection

## Development Hardware Specifications

The application is developed and optimized for the following high-performance system:

### CPU: Intel Core i9-14900HX (2024)
- **Cores**: 24 total (8 P-cores + 16 E-cores)
- **Threads**: 32 threads
- **Base Clock**: P-cores: 2.2 GHz, E-cores: 1.6 GHz
- **Boost Clock**: Up to 5.8 GHz (P-cores), 4.1 GHz (E-cores)
- **Cache**: 36 MB L3 cache
- **TDP**: 55W base, up to 157W under load
- **Architecture**: Raptor Lake-HX Refresh (10nm)

### GPU: NVIDIA GeForce RTX 4090 Laptop
- **CUDA Cores**: 9,728
- **VRAM**: 16 GB GDDR6
- **Memory Interface**: 256-bit
- **Memory Bandwidth**: ~640 GB/s
- **TGP**: 80-175W (175W for maximum performance)
- **Architecture**: Ada Lovelace (5nm)
- **Ray Tracing Cores**: 76
- **Tensor Cores**: 304
- **Capabilities**: AV1 NVENC support, 8K encoding

### Memory & Storage
- **RAM**: 32 GB DDR5
- **Storage**: Dual 2TB SSDs (4TB total)
- **Display**: 18" WQXGA (2560x1600) @ 240Hz, Mini LED

This hardware configuration enables:
- Parallel encoding of multiple 4K/8K streams
- Hardware-accelerated AV1 encoding via RTX 40-series NVENC
- Efficient CPU/GPU workload balancing with auto-balance feature
- High-speed processing with minimal bottlenecks

### Testing Hardware Acceleration
```bash
# Check NVIDIA GPU availability
nvidia-smi -L

# Test FFmpeg encoders
ffmpeg -encoders | grep -E "(nvenc|qsv|vaapi)"

# Probe media file duration (used by progress tracker)
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 input.mp4
```

## Code Architecture Notes

### Refactored Architecture Benefits
The modular architecture provides several advantages:
- **Separation of Concerns**: Each class has a single, well-defined responsibility
- **Type Safety**: Comprehensive type hints with 0 basedpyright errors across all refactored modules
- **Maintainability**: Configuration centralized in `config.py` eliminates magic numbers
- **Performance**: Caching in `CodecHelpers` and adaptive timer management reduce system overhead
- **Testability**: Focused classes with clear interfaces enable easier unit testing

### Signal-Slot Communication
The application uses Qt's signal-slot pattern extensively for loose coupling:
- `ConversionController` emits `conversion_started`, `conversion_finished`, `log_message`, and `progress_updated`
- `SettingsPanel` emits `settings_changed` and `auto_balance_toggled`
- `ProcessManager` emits `output_ready`, `process_finished`, and `update_progress` signals
- `ProcessMonitor` emits `widget_created`, `widget_removed`, and `progress_updated`
- UI updates are batched using adaptive `QTimer` intervals for performance optimization

### Progress Tracking System
Progress calculation uses regex parsing of FFmpeg output:
- `TIME_RE = re.compile(r'time=(\d{2}):(\d{2}):(\d{2}\.\d{2})')` for time progress
- `FPS_RE = re.compile(r'fps=\s*(\d+)')` for frames per second
- ETA smoothing using weighted moving averages with configurable window sizes

### Hardware Acceleration Detection
`CodecHelpers` class provides cached hardware detection:
- RTX 40-series detection for AV1 NVENC support using `detect_rtx40_series()`
- Fallback chain: NVENC → QSV → VAAPI → software encoding
- Auto-balance distributes files between GPU (70%) and CPU (30%) based on system capabilities
- Caching prevents repeated expensive subprocess calls to `nvidia-smi` and `ffmpeg -encoders`

### Thread Optimization
Thread allocation managed by `CodecHelpers.optimize_threads_for_codec()`:
- NVENC encoders: 2 threads (minimal CPU usage)
- Single CPU job: 0 (auto-detect, uses all threads)
- Parallel CPU jobs: `(cpu_count() or ProcessConfig.OPTIMAL_CPU_THREADS) // cpu_jobs` (evenly distributed with None safety)

### Error Handling and Reliability
The application includes comprehensive error handling:
- All subprocess calls use `ProcessConfig.SUBPROCESS_TIMEOUT` (30s) to prevent hangs
- MPEGTS timing issues automatically trigger `-fflags +genpts` flag
- Process failures are tracked and displayed in the UI with status indicators
- Hardware acceleration gracefully falls back to software encoding on detection failures
- Process state race conditions resolved with `QProcess.waitForStarted()`
- Guaranteed resource cleanup prevents memory leaks

## UI Components and Architecture

### Refactored MainWindow Layout (`main_window_refactored.py`)
- **Left Panel**: File list with drag-and-drop support and settings panel
- **Right Panel**: Tabbed interface with active processes and conversion log
- **Control Bar**: Start/stop buttons with visual state feedback
- **Progress Bar**: Overall conversion progress with ETA display
- **Status Bar**: Real-time status updates and conversion statistics

### Component Responsibilities
- **SettingsPanel**: Manages all codec options, threading controls, and hardware acceleration settings with type-safe validation
- **ProcessMonitor**: Creates individual monitoring widgets for each active process with automatic cleanup
- **ConversionController**: Orchestrates the conversion workflow and auto-balance logic
- **FileListWidget**: Handles file management with status tracking (pending, processing, completed, failed)

### Process Monitoring System
Each encoding process gets its own dedicated widget displaying:
- File name and codec type with visual indicators
- Progress bar with percentage completion and color-coded status
- FPS counter and processing speed metrics
- ETA calculation with smoothed time estimates
- Condensed log output for debugging with size limits

## Configuration and State Management

### Centralized Configuration (`config.py`)
All constants are centralized to eliminate magic numbers:
- **ProcessConfig**: Timeouts, threading limits, parallel processing constraints
- **UIConfig**: Timer intervals, widget delays, activity thresholds
- **LogConfig**: Memory limits, truncation sizes, history management
- **EncodingConfig**: Quality settings, presets, audio bitrates
- **HardwareConfig**: GPU detection, RTX model lists, capability thresholds
- **AppConfig**: Application metadata, window dimensions, settings keys

### QSettings Storage
Application state is persisted using Qt's QSettings with backwards compatibility:
- Window geometry and splitter positions
- Last used directory for file selection
- User preferences (delete source files, hardware decode options, etc.)
- Settings panel maintains compatibility with original key names

### Performance Optimizations
- **Adaptive Timers**: UI update intervals adjust based on activity (250ms-1000ms)
- **Smart Buffer Mode**: Reduces UI update frequency during intensive processing
- **Process Output Batching**: Prevents UI blocking during FFmpeg output parsing
- **Memory Management**: Rolling log buffers with configurable size limits (`LogConfig`)
- **Hardware Detection Caching**: Expensive operations cached in `CodecHelpers` static variables

## Type Safety and Code Quality

### Type Checking Configuration
The project uses basedpyright for comprehensive type checking:
- Configured in `pyrightconfig.json` with `typeCheckingMode: "basic"`
- Includes only refactored modules, excludes legacy `PyMPEG.py`
- Custom typeshed path for WSL compatibility: `--typeshedpath venv/lib/python3.12/site-packages/basedpyright/dist/typeshed-fallback`
- Achieved **perfect type safety**: 0 errors, 0 warnings, 0 notes across all modules

### Type Annotations Standards
All refactored modules include comprehensive type hints:
- Optional widget types: `Optional[QWidget]` with assertion guards
- Signal type declarations: `Signal(str)`, `Signal(dict)`, `Signal()`
- Method parameter and return types for all public APIs
- Qt enum access: `Qt.ItemDataRole.UserRole` instead of `Qt.UserRole`

### Code Quality Practices
- **Ruff Integration**: Configured for linting and formatting with automatic fixes
- **Configuration Centralization**: All magic numbers extracted to `config.py` classes
- **Error Handling**: Specific exception types instead of bare `except:` blocks
- **Resource Management**: Guaranteed cleanup with proper widget deletion and subprocess timeouts