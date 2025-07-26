# PyFFMPEG Test Suite

This directory contains comprehensive tests for the PyFFMPEG video converter application.

## Test Structure

```
tests/
├── conftest.py              # Test configuration and fixtures
├── fixtures/
│   ├── mocks.py             # Mock objects and utilities
│   └── __init__.py
├── unit/
│   ├── test_codec_helpers.py       # CodecHelpers class tests
│   ├── test_progress_tracker.py    # ProgressTracker class tests
│   ├── test_process_manager.py     # ProcessManager class tests
│   ├── test_conversion_controller.py # ConversionController class tests
│   └── __init__.py
├── integration/             # [Future] End-to-end tests
└── README.md
```

## Running Tests

### Prerequisites

Install testing dependencies:
```bash
pip install -r requirements.txt
```

### Run All Tests
```bash
pytest
```

### Run Specific Test Categories
```bash
# Unit tests only
pytest tests/unit/

# Specific component tests
pytest tests/unit/test_codec_helpers.py
pytest tests/unit/test_progress_tracker.py
pytest tests/unit/test_process_manager.py
pytest tests/unit/test_conversion_controller.py

# Tests requiring Qt GUI
pytest -m qt

# Hardware-specific tests
pytest -m hardware
```

### Coverage Report
```bash
pytest --cov=. --cov-report=html
```

## Test Coverage

### Completed Components (High Priority)

1. **CodecHelpers** (170+ tests)
   - ✅ Hardware acceleration detection and fallbacks
   - ✅ Encoder configuration for all codec types
   - ✅ Audio codec passthrough logic
   - ✅ Thread optimization algorithms
   - ✅ Caching mechanisms for expensive operations
   - ✅ RTX 40 series detection for AV1 support
   - ✅ Edge cases and error handling

2. **ProgressTracker** (90+ tests)
   - ✅ FFmpeg output regex parsing
   - ✅ Progress percentage calculations
   - ✅ ETA estimation algorithms
   - ✅ Batch processing coordination
   - ✅ Duration probing with ffprobe
   - ✅ Performance with large datasets

3. **ProcessManager** (110+ tests)
   - ✅ QProcess lifecycle management
   - ✅ Queue processing (FIFO, parallel limits)
   - ✅ Smart timer management with adaptive intervals
   - ✅ Resource cleanup and memory management
   - ✅ Process output handling and buffering
   - ✅ Error handling and timeout management

4. **ConversionController** (80+ tests)
   - ✅ Conversion workflow orchestration
   - ✅ Auto-balance workload distribution
   - ✅ FFmpeg argument construction
   - ✅ Signal emission and coordination
   - ✅ Source file deletion (optional)
   - ✅ Process management integration

### Pending Components (Medium Priority)

5. **Integration Tests** - End-to-end workflows with mocked FFmpeg
6. **Qt Widget Tests** - SettingsPanel and FileListWidget
7. **Hardware Mocking** - Test matrix for different hardware configurations

## Test Features

### Mock Objects
- **MockFFmpegProcess**: Simulates realistic FFmpeg behavior
- **MockGPUDetection**: Various GPU scenarios (RTX40, RTX30, Intel, No GPU)
- **MockEncoderDetection**: Different encoder availability scenarios
- **MockQProcessManager**: Advanced QProcess simulation

### Fixtures
- **temp_video_file**: Temporary test video files
- **mock_ffmpeg_subprocess**: Mocked subprocess calls
- **codec_helpers_with_cache**: Pre-populated cache scenarios
- **conversion_test_data**: Common test scenarios

### Hardware Test Matrix
Tests cover various hardware configurations:
- RTX 4090 with full NVENC support (including AV1)
- RTX 3080 with limited NVENC support (no AV1)
- Intel QSV support scenarios
- Software-only encoding fallbacks

## Key Testing Principles

1. **Isolation**: Each test is independent with proper setup/teardown
2. **Mocking**: External dependencies (FFmpeg, nvidia-smi) are mocked
3. **Coverage**: Edge cases, error conditions, and performance scenarios
4. **Realistic**: Mock data reflects real-world FFmpeg behavior
5. **Fast**: Tests run quickly without actual video processing

## Performance Considerations

- Tests complete in under 30 seconds on typical hardware
- Memory usage is bounded through proper mock cleanup
- No actual video files or FFmpeg processes are created
- Hardware detection is cached to avoid repeated subprocess calls

## Future Enhancements

1. **Integration Tests**: Complete conversion workflows
2. **Performance Benchmarks**: Stress testing with large file batches
3. **UI Tests**: Qt widget interaction testing
4. **Cross-Platform**: Windows/Linux/macOS compatibility tests
5. **Hardware Validation**: Real hardware acceleration testing