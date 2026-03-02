# Development Tools

This directory contains development and analysis scripts that are not part of the core ShotBot application.

## Code Transformation Scripts

- **`apply_logging_mixin.py`** - Automates conversion from old logging pattern to LoggingMixin
- **`apply_threading_fixes.py`** - Applies threading safety fixes across codebase

## Code Analysis Scripts

- **`check_python311_compat.py`** - Comprehensive Python 3.11 compatibility checker
- **`check_test_antipatterns.py`** - Detects testing antipatterns and issues
- **`debug_shot_names.py`** - Debug utility for shot name parsing issues

## Performance Analysis Scripts

- **`profile_startup_performance.py`** - Application startup performance profiling
- **`thumbnail_bottleneck_profiler.py`** - Comprehensive thumbnail processing performance analysis
- **`regex_optimization_summary.py`** - Regex performance optimization analysis

## Standalone Test Runners

- **`run_optimization_tests.py`** - Performance optimization test suite
- **`run_thread_safety_tests.py`** - Thread safety validation tests
- **`run_type_check.py`** - Type checking validation runner

## Usage

These scripts are intended for development and debugging purposes. They are not part of the regular application workflow and should not be imported by the main application code.

Run from the project root directory:

```bash
cd /path/to/shotbot
uv run python dev-tools/script_name.py
```

## Note

These scripts were moved from the project root to reduce clutter and clearly separate development tools from production code.