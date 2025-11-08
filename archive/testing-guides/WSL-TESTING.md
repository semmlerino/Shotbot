# WSL Testing Guide for ShotBot

## Performance Characteristics
- Filesystem operations on `/mnt/c` are 10-100x slower than native Linux
- Test collection alone can take 60+ seconds
- Solution: Categorize tests and use optimized runners

## Test Categorization for WSL

```python
# Mark tests with speed categories
import pytest

@pytest.mark.fast  # < 100ms
def test_pure_logic():
    """Fast unit test with no I/O."""
    pass

@pytest.mark.slow  # > 1s
def test_filesystem_heavy():
    """Integration test with file operations."""
    pass

@pytest.mark.critical  # Must pass regardless of speed
def test_core_functionality():
    """Essential functionality test."""
    pass
```

## WSL Test Runner Configuration

```python
# run_tests_wsl.py usage patterns

# Quick validation (2 seconds)
# Uses: NO pytest, direct imports only
python3 quick_test.py

# Fast tests only (~30 seconds)
# Runs: @pytest.mark.fast tests
python3 run_tests_wsl.py --fast

# Critical tests only
# Runs: @pytest.mark.critical tests
python3 run_tests_wsl.py --critical

# Single file (minimal I/O)
python3 run_tests_wsl.py --file tests/unit/test_utils.py

# Pattern matching
python3 run_tests_wsl.py -k test_shot_model

# Full suite in batches (best for WSL)
python3 run_tests_wsl.py --all
```

## WSL-Optimized pytest.ini

```ini
# pytest_wsl.ini - Optimized for WSL filesystem
[tool:pytest]
# Disable plugins that cause excessive I/O
addopts = 
    -q                    # Quiet output
    -ra                   # Show all test outcomes
    --maxfail=1          # Stop on first failure
    -p no:cacheprovider  # Disable cache (slow on WSL)
    -p no:warnings       # Disable warning collection
    --tb=short           # Shorter tracebacks

# Only collect from tests directory
testpaths = tests

# Disable doctest collection (slow)
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

## Batching Strategy for Large Test Suites

```python
def run_tests_in_batches(test_files, batch_size=10):
    """Run tests in batches to avoid WSL timeouts."""
    batches = [test_files[i:i+batch_size] 
               for i in range(0, len(test_files), batch_size)]
    
    for i, batch in enumerate(batches, 1):
        print(f"Running batch {i}/{len(batches)}")
        result = pytest.main([
            "-q",
            "--tb=short",
            "--maxfail=3",
        ] + batch)
        
        if result != 0:
            print(f"Batch {i} failed")
            return result
    
    return 0
```

## WSL Performance Tips

1. **Use tmpfs for test artifacts**
   ```python
   @pytest.fixture
   def fast_tmp(tmp_path_factory):
       """Use /tmp (usually tmpfs) instead of /mnt/c."""
       return tmp_path_factory.mktemp("test", numbered=True, 
                                      base_tmp=Path("/tmp"))
   ```

2. **Minimize test collection**
   ```python
   # Explicit file listing is faster than discovery
   pytest tests/unit/test_shot_model.py tests/unit/test_utils.py
   ```

3. **Disable unnecessary pytest features**
   ```python
   # In conftest.py
   def pytest_configure(config):
       if os.environ.get("WSL_DISTRO_NAME"):
           config.option.verbose = 0
           config.option.capture = "no"
   ```