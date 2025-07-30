# ShotBot Testing Guide

## Test Setup

### Running Tests

```bash
# Run all tests
./venv/bin/python run_tests.py

# Run specific test file
./venv/bin/python run_tests.py tests/unit/test_shot_model.py

# Run with coverage
./venv/bin/python run_tests.py --cov

# Run specific test
./venv/bin/python run_tests.py tests/unit/test_shot_model.py::TestShot::test_shot_creation
```

### Test Organization

```
tests/
├── __init__.py
├── conftest.py          # Shared fixtures
├── unit/                # Unit tests
│   ├── __init__.py
│   ├── test_shot_model.py
│   └── test_command_launcher.py
└── integration/         # Integration tests
    └── __init__.py
```

## Current Test Coverage

| Module | Coverage | Status |
|--------|----------|--------|
| shot_model.py | 99% | ✅ Complete |
| command_launcher.py | 100% | ✅ Complete |
| config.py | N/A | ✅ No tests needed (constants only) |
| log_viewer.py | 0% | ⏳ TODO |
| thumbnail_widget.py | 0% | ⏳ TODO |
| shot_grid.py | 0% | ⏳ TODO |
| main_window.py | 0% | ⏳ TODO |
| shotbot.py | 0% | ⏳ TODO |

**Total Coverage: 24%**

## Key Testing Principles

1. **Minimal Mocking**: Use real implementations where possible
   - Real temp directories for file tests
   - Only mock external dependencies (subprocess, Qt signals)

2. **Test Actual Behavior**: Tests adapted to match implementation
   - Read the code first, write tests second
   - Don't change code to make tests pass unless there's a bug

3. **Early Testing**: Run tests frequently during development

## Known Issues

### WSL/pytest-xvfb Compatibility
- pytest-xvfb causes timeouts in WSL
- Solution: Disabled via `-p no:xvfb` in pytest.ini

### Test Execution
- Must use `python run_tests.py` instead of direct pytest
- This ensures proper path setup and plugin configuration

## Next Steps

1. Widget tests (log_viewer, thumbnail_widget)
2. Integration tests (shot_grid, main_window)
3. Consider property-based testing for edge cases
4. Add performance benchmarks for thumbnail loading