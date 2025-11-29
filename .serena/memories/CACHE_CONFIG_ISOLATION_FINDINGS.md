# Cache/Config Directory Test Isolation Analysis

## Summary
Analyzed test isolation for cache and config directories used in ShotBot test suite. Found several potential state leakage issues and missing cleanup patterns.

## Current Setup

### Directory Structure
- **Config Dir**: `SHOTBOT_CONFIG_DIR` (created in conftest.py:46)
  - Location: `/tmp/shotbot-config-{run_id}-{worker}-{random}`
  - Created per test run, should be cleaned up at session end via atexit

- **Cache Dir**: `SHOTBOT_TEST_CACHE_DIR` (created in conftest.py:51-53)
  - Location: `/tmp/shotbot_test_cache_{worker}`
  - Persistent per worker across multiple test runs
  - Created per-worker, not per-test

### Cleanup Implementation (conftest.py:56-70)
- atexit hook: `_cleanup_test_dirs()` runs at Python exit
- Cleans: `config_dir`, `cache_dir`, `xdg_path`
- Best-effort cleanup (ignores errors)

### Between-Test Cleanup (singleton_isolation.py)
- `reset_caches()` fixture (autouse, runs before every test):
  - Clears disk cache files: `shots.json`, `previous_shots.json`, `threede_scenes.json`, `migrated_shots.json`
  - Also tries clearing `cache_path / "production"` subdirectory (line 112)
  - Clears config files: `custom_launchers.json`, `settings.json`, `window_state.json`
  - Clears OptimizedShotParser pattern cache
  - Clears CacheManager stat cache

## Files/Directories That Can Leak

### 1. **Thumbnails Directory** (PERSISTENT - NOT CLEARED)
- **Location**: `{SHOTBOT_TEST_CACHE_DIR}/thumbnails/`
- **Behavior**: Intentionally NOT cleared between tests
- **Risk**: Images generated in one test persist to next test
- **Note**: SHOTBOT documentation (cache_manager.py:10-14) says "Thumbnails are persistent"
- **Fixture**: `tests/fixtures/caching.py:212-261` has `clean_thumbnails()` fixture for tests that need isolation

### 2. **Production Subdirectory** (SUSPICIOUS)
- **Location**: `{SHOTBOT_TEST_CACHE_DIR}/production/`
- **Status**: Code tries to clean it (singleton_isolation.py:112) but unclear why it exists in tests
- **Files**: Same JSON cache files as root dir
- **Tests creating it**: Not found in explicit test code - may be auto-created by CacheManager
- **Risk**: If tests create files here, they persist between tests because cleanup only works if dir exists

### 3. **XDG Runtime Directory** (CREATED PER WORKER)
- **Location**: `/tmp/xdg-{run_id}-{worker}` (created: conftest.py:38-43)
- **Behavior**: Cleaned at session end via atexit
- **Contents**: Qt-related runtime files
- **Risk**: Per-worker, so shared across multiple tests in same worker

### 4. **Config Directory** (CLEANED BETWEEN TESTS)
- **Location**: `/tmp/shotbot-config-{run_id}-{worker}-{random}`
- **Files cleaned**: custom_launchers.json, settings.json, window_state.json
- **Behavior**: Cleaned before each test via `reset_caches()`
- **Files NOT cleaned**: Any other files created during tests

### 5. **Stat Cache** (IN-MEMORY)
- **Location**: CacheManager._stat_cache (dict)
- **TTL**: 2 seconds (STAT_CACHE_TTL)
- **Risk**: Can leak between fast tests - can cause cache hits on stale data
- **Cleanup**: Cleared in reset_caches() via `_clear_stat_caches()`

## State Leakage Risks

### High Risk
1. **Thumbnails**: Intentionally persistent - test isolation depends on fixture usage
2. **Production subdirectory**: Exists in test tree but unclear lifecycle
3. **QSettings**: Uses test-specific path but unclear if cleaned properly
4. **Stat cache TTL**: 2-second cache can leak between fast tests if reset is slow

### Medium Risk
1. **Pattern cache**: OptimizedShotParser._PATTERN_CACHE - cleared but could leak if test crashes before cleanup
2. **Per-worker XDG dir**: Shared across ~100+ tests in serial runs
3. **Config files**: Cleared before test, but any test-created files not in known list will persist

### Low Risk
1. **JSON cache files**: Explicitly cleared before each test
2. **Session atexit cleanup**: Should work but relies on Python exiting normally

## Missing Cleanup Patterns

### 1. **Unknown Files in Config Dir**
- Only clears 3 known files
- Any other files created by tests will persist
- Example: If a test creates `custom_state.json`, it won't be cleaned

### 2. **Production Subdirectory Cleanup is Conditional**
- Code at singleton_isolation.py:112 checks `if not subdir.exists()` before cleaning
- If cache_path / "production" directory doesn't exist, no error
- But if tests create it, it might not get fully cleaned in all cases

### 3. **No Cleanup of Qt Resources**
- QSettings location set via `QSettings.setPath()` in test fixtures
- These directories might not be in SHOTBOT_TEST_CACHE_DIR
- Could leak between tests using different settings paths

### 4. **Singleton State Not Disk-Persistent**
- Singletons reset before test (reset_singletons fixture)
- But stat_cache in CacheManager is per-instance and resets when _instance=None
- Could cause issues if singleton is recreated mid-test

## Tests Most Vulnerable to State Leakage

### 1. **tests/integration/test_e2e_real_components.py**
- Uses real CacheManager with real cache operations
- Creates "real_cache_dir" fixtures per test
- But monkeypatches SHOTBOT_TEST_CACHE_DIR within test
- Could leave artifacts in global cache dir if test crashes

### 2. **tests/unit/test_cache_separation.py**
- Explicitly tests cache isolation between modes
- Comments note: "can't test production mode directly"
- Uses cache_dir / "production" subdirectory references

### 3. **Any test using `caching_enabled` fixture**
- Creates isolated cache dir but might persist config state
- Restores env var but test-created files remain

### 4. **Tests with Qt widgets**
- Auto-enable cleanup_state_heavy fixture
- But XDG_RUNTIME_DIR is per-worker, not per-test
- Multiple tests share same Qt runtime state

## Recommendations for Improvement

### Immediate (High Priority)
1. **Audit production subdirectory usage**
   - Why do tests need cache_path / "production"?
   - Is it created automatically by CacheManager?
   - Should it be in test cache hierarchy at all?

2. **Add "unknown file" cleanup to reset_caches()**
   ```python
   # Clear ALL files in config dir, not just known ones
   for f in config_path.glob("*"):
       if f.is_file():
           f.unlink(missing_ok=True)
   ```

3. **Document thumbnail persistence explicitly**
   - Add warning comment to reset_caches()
   - List which fixtures require clean_thumbnails

### Medium Priority
1. **Investigate stat_cache leakage**
   - Run fast tests and measure cache hit rate
   - Consider lowering STAT_CACHE_TTL to 0.5s or disabling in tests

2. **Make XDG_RUNTIME_DIR per-test, not per-worker**
   - Would require pytest fixture instead of conftest setup
   - Would add overhead but prevent cross-test state leakage

3. **Verify QSettings isolation**
   - Check if setPath() calls are properly cleaned
   - Ensure all test settings use SHOTBOT_CONFIG_DIR

### Low Priority
1. **Convert atexit cleanup to pytest session-scoped fixture**
   - More reliable than atexit (always runs, even on crash)
   - Can report errors instead of silently ignoring

2. **Add state validation after cleanup**
   - Snapshot expected state before test
   - Compare after cleanup to detect leakage

## Files to Clean Up in /tmp

Currently exist:
- `shotbot-config-solo-master-*` (empty, ready to delete)
- `shotbot_test_*` (cache dirs with thumbnails subdirs)

These can be safely removed - should be created fresh per test run.
