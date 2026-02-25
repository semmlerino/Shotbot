# Pytest-xdist Parallel Testing Guide

## Summary of Changes

### ✅ Fixed Issues
1. **Removed `-p no:xdist`** from pytest.ini which was disabling the plugin
2. **Installed pytest-xdist** for parallel test execution support
3. **Increased timeout** from 60s to 120s for better stability
4. **Applied optimized configuration** based on best practices

## How to Use pytest-xdist

### Basic Commands

```bash
# Automatic CPU detection (uses physical cores)
pytest -n auto

# Use all logical cores (includes hyperthreading)
pytest -n logical

# Specify exact number of workers
pytest -n 4

# Disable parallel execution
pytest -n 0
```

### Distribution Strategies

```bash
# Default: load balancing
pytest -n auto --dist load

# Group by module/class (better for fixture reuse)
pytest -n auto --dist loadscope

# Group by file (all tests in a file run together)
pytest -n auto --dist loadfile

# Group by xdist_group mark
pytest -n auto --dist loadgroup

# Work stealing (good for uneven test durations)
pytest -n auto --dist worksteal
```

### Best Practices for WSL

```bash
# Fast feedback loop
pytest -m fast -n auto --tb=short

# Integration tests (use fewer workers)
pytest tests/integration -n 2

# Debug mode (disable parallel)
pytest -n 0 -vv --tb=long
```

## Performance Considerations

### When Parallel Helps
- **Large test suites** with many independent tests
- **CPU-bound tests** that don't share resources
- **Well-isolated tests** without shared state

### When Parallel Hurts
- **Small test files** (overhead > benefit)
- **I/O heavy tests** in WSL (filesystem bottleneck)
- **Tests with shared resources** (databases, files)
- **Tests with poor isolation** (global state)

## Current Issues Discovered

### 1. Test Isolation Problems
Some tests fail in parallel but pass serially:
- `test_property_based.py` tests have isolation issues
- Likely due to shared filesystem or global state

### 2. WSL Performance
- Parallel execution can be **slower** on WSL due to filesystem overhead
- Small test files don't benefit from parallelization
- Worker startup overhead is significant

### 3. Recommended Settings

For **development** (fast feedback):
```bash
pytest -m "fast and unit" -x --tb=short
```

For **CI/full runs**:
```bash
pytest -n auto --dist loadscope --maxfail=5
```

For **debugging**:
```bash
pytest -n 0 -vv --tb=long --capture=no
```

## Configuration Highlights

The new `pytest.ini` includes:
- **Timeout**: 120s (up from 60s)
- **Progress output**: Shows test progress
- **Duration reporting**: Shows 20 slowest tests
- **Smart markers**: fast, slow, unit, integration
- **Parallel ready**: Just add `-n auto` when needed

## Troubleshooting

### Tests fail in parallel but pass serially
- Check for shared state or resources
- Use `@pytest.mark.xdist_group` to keep related tests together
- Consider `--dist loadfile` to keep file tests together

### Parallel execution is slower
- Try fewer workers: `-n 2` or `-n 3`
- Use `--dist loadscope` for better fixture reuse
- Consider running only non-I/O tests in parallel

### Worker crashes or timeouts
- Increase timeout: `--timeout=300`
- Limit workers: `--max-worker-restart=4`
- Check for Qt thread safety issues

## Next Steps

1. **Fix test isolation issues** in property-based tests
2. **Mark I/O-heavy tests** to run serially
3. **Optimize worker count** for WSL (likely 2-4 workers)
4. **Consider pytest-xdist hooks** for better control:
   ```python
   # conftest.py
   def pytest_xdist_auto_num_workers(config):
       """Limit workers in WSL environment"""
       import platform
       if 'microsoft' in platform.uname().release.lower():
           return 2  # WSL detected, use fewer workers
       return 'auto'
   ```

## Commands Cheat Sheet

```bash
# Install
pip install pytest-xdist

# Quick test
pytest -n auto -m fast

# Full suite with progress
pytest -n auto --dist loadscope

# Integration tests (fewer workers)
pytest tests/integration -n 2

# Debug failing test
pytest path/to/test.py::TestClass::test_method -n 0 -vv

# Show worker output
pytest -n auto -s

# Limit test failures
pytest -n auto --maxfail=5
```