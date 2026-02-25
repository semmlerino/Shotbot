# Configuration Validation Guide

**Last Updated**: 2025-10-14
**Test Coverage**: 27 validation tests, 29+ configuration constraints
**Test File**: `tests/unit/test_config.py`

---

## Overview

ShotBot's configuration is validated by automated tests that check constraints and prevent silent misconfigurations. These tests ensure that config changes don't break critical workflows.

### Why Configuration Validation Matters

**Real Bug Example** (Commit a77b8cb → fde59a4):
- **What**: PL plate priority set to 10 (reference-only) instead of 0.5 (primary workflow)
- **Impact**: Turnover plates skipped in production, breaking VFX artist workflows
- **Root Cause**: No validation of plate priority ordering
- **Fix**: Added test_config.py with priority validation tests
- **Prevention**: Test now fails if priorities are misconfigured

---

## Critical Configuration Constraints

### 1. Plate Priorities (TURNOVER_PLATE_PRIORITY)

**Location**: `config.py:258-265`

#### The Rule

```python
FG < PL < BG < COMP < EL < BC < *
```

**Specifically**:
- FG (foreground) = 0
- PL (turnover) = 0.5
- BG (background) = 1
- COMP (composite) = 1.5
- EL (element) = 2
- BC (background clean) >= 10
- * (unknown) = 12

#### Why This Ordering Matters

**Plate Usage Categories**:
1. **Primary Workflow Plates** (FG, PL, BG): Use these for active compositing
2. **Secondary Plates** (COMP, EL): Use if needed for specific elements
3. **Reference-Only** (BC): Do NOT use for compositing (clean background reference)

**Priority System**:
- Lower values = higher priority
- Launcher auto-selects based on priority
- Wrong priorities = wrong plates selected = broken workflow

#### Example Bug Scenario

```python
# WRONG (Bug configuration)
TURNOVER_PLATE_PRIORITY = {
    "FG": 0,
    "PL": 10,   # ❌ Should be 0.5, not 10!
    "BG": 1,
    "BC": 10,
}

# Shot has: FG01, PL01, BG01, BC01
# Expected: Select PL01 (priority 0.5)
# Actual: Selects FG01 (PL has same priority as BC, skipped)
```

#### Tests That Validate This

```python
def test_turnover_plate_priority_ordering():
    """Validate plate priorities maintain correct ordering."""
    priorities = Config.TURNOVER_PLATE_PRIORITY

    # Primary plates (use these)
    assert priorities["FG"] < priorities["PL"]
    assert priorities["PL"] < priorities["BG"]
    assert priorities["BG"] < priorities["COMP"]

    # Reference plates (skip these)
    assert priorities["BC"] > 5

def test_primary_plates_have_low_priority():
    """Ensure primary workflow plates have low (high priority) values."""
    priorities = Config.TURNOVER_PLATE_PRIORITY

    assert priorities["FG"] < 2
    assert priorities["PL"] < 2  # ← Would catch PL=10 bug
    assert priorities["BG"] < 2
```

---

### 2. Path Configuration

#### The Rules

1. **SHOWS_ROOT must be absolute**
   - Prevents ambiguous relative paths
   - Ensures consistent resolution across components

2. **Cache directories must follow pattern**
   - Production: `.shotbot/cache/{category}/`
   - Mock: `.shotbot/cache/mock_{category}/`
   - Test: `.shotbot/cache/test_{category}/`

3. **Terminal FIFO paths must be accessible**
   - Must be writable by user
   - Must not conflict with system paths

#### Tests That Validate This

```python
def test_shows_root_is_absolute_path():
    """Validate SHOWS_ROOT is an absolute path."""
    assert Path(Config.SHOWS_ROOT).is_absolute()

def test_cache_directories_pattern():
    """Validate cache directory patterns."""
    # Check that cache dirs follow expected naming
    assert "cache" in Config.CACHE_DIR.lower()
```

---

### 3. Timeout Configuration

#### The Rules

1. **All timeouts must be positive** (> 0 seconds)
2. **Timeouts must be reasonable** (< 600 seconds = 10 minutes)
3. **Process timeouts must be longer than subprocess timeouts**

#### Critical Timeout Values

| Config Value | Purpose | Default | Valid Range |
|--------------|---------|---------|-------------|
| `SUBPROCESS_TIMEOUT` | Process execution | 30s | 5-300s |
| `CACHE_TTL` | Cache validity | 1800s | 60-3600s |
| `THREADING_TIMEOUT` | Thread join | 30s | 1-120s |

#### Tests That Validate This

```python
def test_timeout_values_are_positive():
    """Ensure all timeout values are positive."""
    assert Config.SUBPROCESS_TIMEOUT > 0
    assert Config.CACHE_TTL > 0
    assert Config.THREADING_TIMEOUT > 0

def test_timeout_values_are_reasonable():
    """Ensure timeouts aren't absurdly large."""
    assert Config.SUBPROCESS_TIMEOUT < 600  # 10 minutes max
```

---

### 4. Memory Configuration

#### The Rules

1. **Memory limits must be positive**
2. **Memory pressure thresholds must be ordered correctly**:
   - LOW < MEDIUM < HIGH < CRITICAL
3. **Cache size limits must be reasonable**

#### Memory Thresholds

```python
MEMORY_PRESSURE_THRESHOLDS = {
    "LOW": 0.5,      # 50% memory usage
    "MEDIUM": 0.7,   # 70% memory usage
    "HIGH": 0.85,    # 85% memory usage
    "CRITICAL": 0.95 # 95% memory usage
}
```

#### Tests That Validate This

```python
def test_memory_pressure_thresholds_are_ordered():
    """Validate memory thresholds are ordered correctly."""
    thresholds = Config.MEMORY_PRESSURE_THRESHOLDS

    assert thresholds["LOW"] < thresholds["MEDIUM"]
    assert thresholds["MEDIUM"] < thresholds["HIGH"]
    assert thresholds["HIGH"] < thresholds["CRITICAL"]
```

---

### 5. Thread Configuration

#### The Rules

1. **Thread counts must be positive** (>= 1)
2. **Worker threads must be reasonable** (1-32 typical)
3. **Polling intervals must be positive** (> 0 ms)

#### Tests That Validate This

```python
def test_thread_counts_are_positive():
    """Ensure thread count configuration is valid."""
    assert Config.MAX_WORKER_THREADS > 0
    assert Config.OPTIMAL_CPU_THREADS >= 1

def test_threading_config_worker_threads_are_reasonable():
    """Worker threads should be reasonable (not 1000+)."""
    assert Config.MAX_WORKER_THREADS < 100
```

---

## Running Configuration Validation Tests

### Quick Validation

```bash
# Run all config validation tests
uv run pytest tests/unit/test_config.py -v

# Expected output:
# 27 passed in ~2.1s
```

### Specific Test Categories

```bash
# Plate priority tests only (6 tests)
uv run pytest tests/unit/test_config.py::TestPlatePriorityValidation -v

# Path configuration tests (4 tests)
uv run pytest tests/unit/test_config.py::TestPathConfigurationValidation -v

# Timeout tests (3 tests)
uv run pytest tests/unit/test_config.py::TestTimeoutConfigurationValidation -v

# Memory tests (3 tests)
uv run pytest tests/unit/test_config.py::TestMemoryConfigurationValidation -v

# Thread tests (3 tests)
uv run pytest tests/unit/test_config.py::TestThreadConfigurationValidation -v
```

### Running Tests Before Config Changes

**Workflow**:
1. Make config changes
2. Run validation: `uv run pytest tests/unit/test_config.py -v`
3. If tests pass → proceed with commit
4. If tests fail → fix config to satisfy constraints

---

## Test Categories

### 1. Plate Priority Validation (6 tests)

**Tests**:
- `test_turnover_plate_priority_ordering` - Order constraints
- `test_primary_plates_have_low_priority` - Primary plates < 2
- `test_reference_plates_have_high_priority` - BC >= 10
- `test_all_priority_values_are_numeric` - Type validation
- `test_undistortion_plate_priority_consistency` - Cross-config validation
- `test_plate_priority_order_legacy_compatibility` - Backward compatibility

**What Gets Validated**:
- FG < PL < BG < COMP < EL < BC ordering
- Primary plates (FG, PL, BG) all < 2
- Reference plates (BC) >= 10
- All values are numeric (not strings, None, etc.)

**Would Catch**: PL=10 bug, accidentally swapped priorities, typos

---

### 2. Path Configuration Validation (4 tests)

**Tests**:
- `test_shows_root_is_absolute_path` - SHOWS_ROOT validation
- `test_cache_directories_are_valid` - Cache path patterns
- `test_terminal_fifo_path_validation` - Terminal paths
- `test_path_completeness` - All required paths defined

**What Gets Validated**:
- Absolute paths used (not relative)
- Cache directories follow naming conventions
- Terminal paths don't conflict with system paths
- All expected path configs are present

**Would Catch**: Relative path usage, typos in cache dirs, missing paths

---

### 3. Timeout Configuration Validation (3 tests)

**Tests**:
- `test_timeout_values_are_positive` - All timeouts > 0
- `test_timeout_values_are_reasonable` - No absurd values
- `test_threading_config_timeout_validity` - Thread-specific timeouts

**What Gets Validated**:
- All timeouts > 0 seconds
- All timeouts < 600 seconds (10 min)
- Thread join timeouts are reasonable

**Would Catch**: Negative timeouts, typos (30000 instead of 30), missing values

---

### 4. Application Configuration Validation (4 tests)

**Tests**:
- `test_app_config_completeness` - All keys present
- `test_window_dimensions_are_positive` - Width/height > 0
- `test_window_dimension_constraints` - Min <= default <= max
- `test_thumbnail_size_constraints` - Thumbnail size ranges

**What Gets Validated**:
- AppConfig class has all required fields
- Window dimensions are positive integers
- Thumbnail sizes are within valid ranges
- Min/default/max values are properly ordered

**Would Catch**: Missing config keys, negative dimensions, invalid ranges

---

### 5. Memory Configuration Validation (3 tests)

**Tests**:
- `test_memory_limits_are_positive` - All limits > 0
- `test_memory_pressure_thresholds_are_ordered` - LOW < MEDIUM < HIGH < CRITICAL
- `test_cache_size_limits_are_positive` - Cache limits valid

**What Gets Validated**:
- Memory limits are positive numbers
- Pressure thresholds are ordered correctly
- Cache size limits are reasonable

**Would Catch**: Negative memory limits, reversed thresholds, absurd cache sizes

---

### 6. Thread Configuration Validation (3 tests)

**Tests**:
- `test_thread_counts_are_positive` - Thread counts >= 1
- `test_threading_config_worker_threads_are_reasonable` - Not 1000+
- `test_polling_intervals_are_valid` - Intervals > 0

**What Gets Validated**:
- Thread pools have at least 1 thread
- Worker threads are reasonable (< 100)
- Polling intervals are positive

**Would Catch**: Zero thread count, absurd thread pools, negative intervals

---

### 7. File Extension Configuration Validation (2 tests)

**Tests**:
- `test_file_extensions_have_leading_dot` - Extensions start with "."
- `test_thumbnail_extensions_are_lightweight` - Reasonable thumbnail formats

**What Gets Validated**:
- File extensions have leading dots (".jpg", not "jpg")
- Thumbnail formats are efficient (JPG, PNG, not BMP)

**Would Catch**: Missing dots, inefficient formats

---

### 8. Progress Configuration Validation (2 tests)

**Tests**:
- `test_progress_intervals_are_positive` - Update intervals > 0
- `test_batch_size_constraints` - Batch sizes reasonable

**What Gets Validated**:
- Progress update intervals are positive
- Batch sizes are within reasonable ranges

**Would Catch**: Negative intervals, absurd batch sizes

---

## Making Safe Configuration Changes

### Step-by-Step Process

1. **Identify what needs changing**
   - Example: Need to adjust subprocess timeout

2. **Locate config value**
   ```bash
   grep -n "SUBPROCESS_TIMEOUT" config.py
   ```

3. **Make the change**
   ```python
   # config.py
   SUBPROCESS_TIMEOUT: ClassVar[int] = 60  # Changed from 30 to 60
   ```

4. **Run validation tests**
   ```bash
   uv run pytest tests/unit/test_config.py -v
   ```

5. **Verify tests pass**
   - If pass: Proceed to commit
   - If fail: Review error, fix config, repeat

6. **Test manually** (optional but recommended)
   ```bash
   uv run python shotbot_mock.py
   ```

7. **Commit with clear message**
   ```bash
   git commit -m "config: Increase subprocess timeout to 60s for large files"
   ```

---

## Adding New Configuration Values

### Process

1. **Add value to config.py**
   ```python
   # config.py
   NEW_FEATURE_TIMEOUT: ClassVar[int] = 45
   ```

2. **Add validation test**
   ```python
   # tests/unit/test_config.py
   def test_new_feature_timeout_is_valid():
       """Validate new feature timeout."""
       assert Config.NEW_FEATURE_TIMEOUT > 0
       assert Config.NEW_FEATURE_TIMEOUT < 600
   ```

3. **Run tests to verify**
   ```bash
   uv run pytest tests/unit/test_config.py -v
   ```

4. **Document in this file** (add to relevant section)

---

## Troubleshooting Test Failures

### Test: test_turnover_plate_priority_ordering

**Failure**: `AssertionError: assert 10 < 1`

**Cause**: PL priority is 10 (should be 0.5)

**Fix**:
```python
# config.py
TURNOVER_PLATE_PRIORITY = {
    "FG": 0,
    "PL": 0.5,  # ← Change from 10 to 0.5
    "BG": 1,
    # ...
}
```

---

### Test: test_timeout_values_are_positive

**Failure**: `AssertionError: assert -1 > 0`

**Cause**: Timeout set to -1 (invalid)

**Fix**: Change to positive value (typical: 30-60 seconds)

---

### Test: test_window_dimensions_are_positive

**Failure**: `AssertionError: assert 0 > 0`

**Cause**: Window dimension is 0 or negative

**Fix**: Set to reasonable value (e.g., 800x600 minimum)

---

### Test: test_memory_pressure_thresholds_are_ordered

**Failure**: `AssertionError: assert 0.85 < 0.7`

**Cause**: Thresholds are out of order

**Fix**: Ensure LOW < MEDIUM < HIGH < CRITICAL

---

## Common Configuration Mistakes

### 1. String Instead of Number

```python
# WRONG
SUBPROCESS_TIMEOUT = "30"  # String, not int

# RIGHT
SUBPROCESS_TIMEOUT = 30  # Integer
```

**Caught By**: `test_all_priority_values_are_numeric`

---

### 2. Swapped Min/Max Values

```python
# WRONG
MIN_THUMBNAIL_SIZE = 300
MAX_THUMBNAIL_SIZE = 100

# RIGHT
MIN_THUMBNAIL_SIZE = 100
MAX_THUMBNAIL_SIZE = 300
```

**Caught By**: `test_thumbnail_size_constraints`

---

### 3. Missing Leading Dot

```python
# WRONG
THUMBNAIL_EXTENSIONS = ["jpg", "png"]

# RIGHT
THUMBNAIL_EXTENSIONS = [".jpg", ".png"]
```

**Caught By**: `test_file_extensions_have_leading_dot`

---

### 4. Unreasonable Values

```python
# WRONG
MAX_WORKER_THREADS = 10000  # Way too many

# RIGHT
MAX_WORKER_THREADS = 8  # Reasonable
```

**Caught By**: `test_threading_config_worker_threads_are_reasonable`

---

## Related Documentation

- **Plate Workflow**: See `docs/NUKE_PLATE_WORKFLOW.md` for plate priority usage
- **Testing**: See `UNIFIED_TESTING_V2.MD` for test patterns and execution
- **Source Code**: See `config.py` for all configuration values
- **Tests**: See `tests/unit/test_config.py` for validation implementation

---

## Best Practices

### DO:
- ✅ Run validation tests before committing config changes
- ✅ Add validation tests for new config values
- ✅ Use descriptive config names (not `TIMEOUT1`, `TIMEOUT2`)
- ✅ Document why specific values were chosen
- ✅ Keep related configs together in the file

### DON'T:
- ❌ Commit config changes without running tests
- ❌ Use magic numbers without defining constants
- ❌ Mix units (use seconds everywhere, not mix seconds/milliseconds)
- ❌ Hard-code values that should be in config
- ❌ Ignore test failures ("I'll fix it later")

---

## FAQ

**Q: Why do we validate configuration with tests?**
A: Silent misconfigurations (like PL=10) can break workflows. Tests catch these before they reach production.

**Q: Can I skip validation tests if I'm "just tweaking a number"?**
A: No. The PL=10 bug was "just tweaking a number" and broke production. Always run tests.

**Q: What if I need a config value that breaks existing tests?**
A: Update the tests to match new requirements, but be explicit about why constraints changed.

**Q: How long does validation take?**
A: ~2.1 seconds for all 27 tests. Worth it to prevent production bugs.

**Q: Can I add config values without tests?**
A: Technically yes, but you're creating technical debt. Add the test.

---

**Remember**: The 5 minutes spent running validation tests can save hours debugging production issues.
