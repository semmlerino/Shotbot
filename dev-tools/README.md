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

- **`run_optimization_tests.py`** - Compatibility wrapper for a maintained optimization-focused regression subset
- **`run_thread_safety_tests.py`** - Compatibility wrapper for maintained thread-safety suites
- **`run_type_check.py`** - Wrapper for the canonical lint and type-check commands

## Usage

These scripts are intended for development and debugging purposes. They are not part of the regular application workflow and should not be imported by the main application code.

Most maintained scripts can be run from the project root directory:

```bash
cd /mnt/c/CustomScripts/Python/shotbot
uv run python dev-tools/<script_name>.py
```

The three `run_*` wrappers above are compatibility entrypoints around the current
tooling. Prefer the canonical commands in `README.md` and `UNIFIED_TESTING_V2.md`
when you want the full, documented workflow.

## Note

These scripts were moved from the project root to reduce clutter and clearly separate development tools from production code.
