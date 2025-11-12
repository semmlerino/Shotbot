# Critical Fixes Guide - Immediate Action Items

## Overview
This guide provides step-by-step fixes for the 2 critical issues identified in the code review that should be addressed immediately.

---

## Issue #1: Process Cleanup Assertion Error
**File**: `/home/gabrielh/projects/shotbot/launcher/worker.py`
**Lines**: 208-237
**Risk**: Silent exception masking during process cleanup failure

### Current Problem Code
```python
def _cleanup_process(self) -> None:
    """Clean up process resources with force kill fallback."""
    if self._process:
        # ... code ...
        except Exception as e:
            # Type guard: process is guaranteed non-None here
            assert self._process is not None  # ← CAN FAIL!
            self.logger.critical(
                f"Failed to clean up process {self._process.pid} for '{self.launcher_id}': {e}"
            )
```

**Why This Is Wrong**:
- The assertion assumes `_process` is non-None, but the variable could be set to None in another thread
- If the assertion fails, it raises `AssertionError` instead of logging the original exception
- This masks the real error that occurred during cleanup

### Fix (Copy-Paste Ready)

Replace lines 231-237 with:

```python
        except Exception as cleanup_error:
            # Process may have been set to None by another path
            # Log safely regardless of process state
            process_pid = self._process.pid if self._process else "unknown"
            self.logger.critical(
                f"Failed to clean up launcher '{self.launcher_id}' "
                f"(PID: {process_pid}): {cleanup_error}"
            )
            # Note: DO NOT set self._process = None here
            # Retain reference for external monitoring/debugging if needed
```

### Verification
After applying the fix, run:
```bash
~/.local/bin/uv run pytest tests/unit/test_launcher_worker.py -v
```

---

## Issue #2: Silent Data Corruption in Cache
**File**: `/home/gabrielh/projects/shotbot/cache_manager.py`
**Lines**: 148-163
**Risk**: Incomplete scene data written to cache

### Current Problem Code
```python
def _scene_to_dict(scene: object) -> ThreeDESceneDict:
    """Convert ThreeDEScene object or dict to ThreeDESceneDict."""
    if isinstance(scene, dict):
        # Double cast defeats type checking - no validation!
        return cast("ThreeDESceneDict", cast("object", scene))
    return cast("_HasToDict", scene).to_dict()
```

**Why This Is Wrong**:
- Casting a dict to `ThreeDESceneDict` without validation
- If required fields are missing, silent data corruption occurs
- Cache operations will fail with cryptic errors later when accessing missing fields

### Fix (Copy-Paste Ready)

Replace lines 148-163 with:

```python
def _scene_to_dict(scene: object) -> ThreeDESceneDict:
    """Convert ThreeDEScene object or dict to ThreeDESceneDict.
    
    Args:
        scene: ThreeDEScene object with to_dict() method or ThreeDESceneDict
    
    Returns:
        ThreeDESceneDict with all required fields
        
    Raises:
        ValueError: If dict is missing required fields
        AttributeError: If object doesn't have to_dict() method
    """
    if isinstance(scene, dict):
        # Validate required fields before accepting dict
        required_fields = {"show", "sequence", "shot", "path", "status"}
        missing = required_fields - set(scene.keys())
        if missing:
            raise ValueError(
                f"Scene dict missing required fields: {missing}. "
                f"Got fields: {set(scene.keys())}"
            )
        return cast(ThreeDESceneDict, scene)
    
    # Assume ThreeDEScene object with to_dict method
    if not hasattr(scene, "to_dict"):
        raise AttributeError(
            f"Scene object {type(scene)} does not have to_dict() method"
        )
    return cast("_HasToDict", scene).to_dict()
```

### Verification
After applying the fix, run:
```bash
~/.local/bin/uv run pytest tests/unit/test_launcher_models.py -v
~/.local/bin/uv run pytest tests/unit/test_optimized_cache_scenarios.py -v
```

Test that invalid cache entries are rejected:
```bash
~/.local/bin/uv run python -c "
from cache_manager import _scene_to_dict
try:
    # Should raise ValueError for missing fields
    _scene_to_dict({'show': 'test', 'sequence': 'seq', 'shot': 'shot'})
except ValueError as e:
    print(f'✓ Correctly caught: {e}')
"
```

---

## Quick Fix Checklist

- [ ] Fix Issue #1 in launcher/worker.py (process cleanup)
- [ ] Fix Issue #2 in cache_manager.py (_scene_to_dict validation)
- [ ] Run unit tests for both files
- [ ] Run full test suite: `~/.local/bin/uv run pytest tests/ -n auto --dist=loadgroup`
- [ ] Run type checker: `~/.local/bin/uv run basedpyright`
- [ ] Run linter: `~/.local/bin/uv run ruff check .`
- [ ] Commit with message: `fix: Address critical process cleanup and cache validation issues`

---

## Testing the Fixes

### Test Process Cleanup Fix
```bash
# Run worker-specific tests
~/.local/bin/uv run pytest tests/unit/test_launcher_worker.py::TestLauncherWorker::test_cleanup_on_timeout -v

# Run process manager tests
~/.local/bin/uv run pytest tests/unit/test_launcher_process_manager.py -v
```

### Test Cache Validation Fix
```bash
# Run cache tests
~/.local/bin/uv run pytest tests/unit/test_optimized_cache_scenarios.py::TestCacheValidation -v -k "scene"

# Run launcher model tests
~/.local/bin/uv run pytest tests/unit/test_launcher_models.py -v
```

### Full Integration Test
```bash
# Run complete test suite
~/.local/bin/uv run pytest tests/ -n auto --dist=loadgroup --tb=short

# Check type safety
~/.local/bin/uv run basedpyright launcher/worker.py cache_manager.py
```

---

## Additional Notes

### Why These Are Critical

1. **Process Cleanup Issue**:
   - Can mask real errors during process termination
   - May leave zombie processes if cleanup fails silently
   - Affects all launcher execution paths

2. **Cache Validation Issue**:
   - Can corrupt cache with incomplete data
   - Breaks downstream scene operations silently
   - Affects all 3DE scene cache operations

### Prevention in Future

1. Add pre-commit hook to catch assertions in except blocks:
```bash
grep -n "assert.*#.*Type guard" launcher/worker.py  # Should return nothing
```

2. Add validation layer for all cache writes:
```python
# Before writing cache
cache_data = _scene_to_dict(scene)  # Validates automatically
cache_manager.write_cache(cache_data)
```

3. Use mypy/basedpyright with strict mode to catch double-casts:
```bash
~/.local/bin/uv run basedpyright --outputjson | grep -i "cast"
```

---

## Questions?

If you run into issues applying these fixes:
1. Check the line numbers in your editor (may have changed)
2. Verify imports are correct (cast, etc.)
3. Run type checker after each fix
4. Check test output for specific failures

