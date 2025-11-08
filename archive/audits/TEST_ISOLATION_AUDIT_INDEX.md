# Test Isolation Audit - Complete Documentation

## Quick Links

- **[Summary Report](TEST_ISOLATION_AUDIT_SUMMARY.txt)** - 2.8 KB, Quick checklist and overview
- **[Full Audit Report](TEST_ISOLATION_AUDIT.md)** - 14 KB, Detailed analysis with code examples
- **[This Index](TEST_ISOLATION_AUDIT_INDEX.md)** - Navigation guide

## Report Contents

### TEST_ISOLATION_AUDIT_SUMMARY.txt
Quick reference format - use this to:
- Get a fast overview of findings
- See violation counts per category
- Check priority ordering (1, 2, 3)
- Find specific line numbers to fix
- Get verification commands

Best for: Quick lookups, CI/CD integration, checklists

### TEST_ISOLATION_AUDIT.md
Full detailed report - use this to:
- Understand root causes of violations
- See code examples showing the problem
- Understand impact on parallel execution
- Learn recommended fixes with code
- Review testing strategies

Best for: In-depth understanding, code reviews, implementation

### Memory File
Location: `.serena/memories/test_isolation_audit_results`
Purpose: Persistent audit findings for future reference

## Violation Summary

| Risk | Category | Count | Files | Action |
|------|----------|-------|-------|--------|
| HIGH | Shared Cache Directories | 10 | 2 | Fix immediately |
| MEDIUM | Global Config Usage | 3 | 1 | Fix soon |
| LOW | MainWindow (false pos.) | 29 | 5 | Docs only |
| PASSED | Module-Level Qt Apps | 0 | - | No action |

## Implementation Checklist

### Phase 1: HIGH Priority (Blocks Parallel Execution)

```bash
# File: tests/unit/test_cache_separation.py
# Lines: 89, 95, 101, 139, 146, 153, 164

- [ ] Read TEST_ISOLATION_AUDIT.md "Category 1" section
- [ ] Update all test functions to use tmp_path + monkeypatch
- [ ] Run verification: pytest tests/unit/test_cache_separation.py -n 2 -v
- [ ] Verify no cache contamination errors
```

### Phase 2: MEDIUM Priority (Best Practices)

```bash
# File: tests/unit/test_launcher_controller.py
# Lines: 172-179 (test_shot), 183-195 (test_scene)

- [ ] Read TEST_ISOLATION_AUDIT.md "Category 2" section
- [ ] Add monkeypatch parameter to fixtures
- [ ] Add tmp_path parameter to fixtures
- [ ] Run verification: pytest tests/unit/test_launcher_controller.py -n 2 -v
- [ ] Verify fixtures work with parallel workers
```

### Phase 3: LOW Priority (Documentation)

```bash
# File: UNIFIED_TESTING_V2.MD

- [ ] Add note about defer_background_loads not existing
- [ ] Document that QTimer mocking is correct approach
- [ ] Add reference to actual mitigation patterns used
```

## Parallel Execution Status

### Before Fixes
```bash
pytest tests/ -n 2
# Result: MAY FAIL - test_cache_separation.py cache contamination
```

### After Fixes
```bash
pytest tests/ -n auto
# Result: PASS - Full parallel-safe execution
```

## Files Involved

### Violations
1. **tests/unit/test_cache_separation.py** (7 violations)
   - Lines: 89, 95, 101, 139, 146, 153, 164
   - Fix: Add tmp_path + monkeypatch

2. **tests/unit/test_launcher_controller.py** (3 violations)
   - Lines: 172-179, 183-195
   - Fix: Add monkeypatch + tmp_path to fixtures

3. **tests/integration/test_*.py** (29 violations)
   - Issue: False positives (parameter doesn't exist)
   - Fix: Documentation only (no code changes)

4. **tests/conftest.py** (0 violations)
   - Status: PASSED ✅

### Documentation
- **UNIFIED_TESTING_V2.MD** - Update guidelines about defer_background_loads

## Detailed Findings

### Violation Types

#### Type 1: CacheManager Without cache_dir (HIGH)
```python
# WRONG
test_manager = CacheManager()  # Uses ~/.shotbot/cache_test (shared!)

# RIGHT
test_manager = CacheManager(cache_dir=tmp_path / "cache")  # Isolated
```

#### Type 2: Config Without Monkeypatch (MEDIUM)
```python
# WRONG
@pytest.fixture
def test_shot() -> Shot:
    return Shot(workspace_path=f"{Config.SHOWS_ROOT}/...")  # Not isolated

# RIGHT
@pytest.fixture
def test_shot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Shot:
    shows_root = tmp_path / "shows"
    monkeypatch.setattr("config.Config.SHOWS_ROOT", str(shows_root))
    return Shot(workspace_path=f"{shows_root}/...")
```

#### Type 3: MainWindow (FALSE POSITIVE)
```python
# "WRONG" (according to guideline)
window = MainWindow()  # Missing defer_background_loads parameter

# REALITY
# Parameter doesn't exist. Tests properly use:
with patch("PySide6.QtCore.QTimer.singleShot"):
    window = MainWindow()  # Disables background timers

# or
mock_get_instance.return_value = TestProcessPool()
window = MainWindow()  # Uses mocked process pool
```

## Testing Verification

After each phase, run:

```bash
# Phase 1: Cache separation
~/.local/bin/uv run pytest tests/unit/test_cache_separation.py -n 2 -v

# Phase 2: Launcher controller
~/.local/bin/uv run pytest tests/unit/test_launcher_controller.py -n 2 -v

# Phase 3: Full suite
~/.local/bin/uv run pytest tests/ -n 2 --maxfail=1 -v

# Final: Full parallel verification
~/.local/bin/uv run pytest tests/ -n auto -v
```

## Key Concepts

### Test Isolation
- Each test must be runnable alone
- Each test must be runnable in any order
- Each test must be runnable on any parallel worker
- No shared state between tests (filesystem, cache, config)

### Parallel Safety Patterns

**Pattern 1: Use tmp_path**
```python
def test_something(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    # Each test gets its own isolated directory
```

**Pattern 2: Use monkeypatch**
```python
def test_something(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("module.GLOBAL_VAR", "test_value")
    # Automatically reverted after test
```

**Pattern 3: Combine both**
```python
def test_something(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("module.CACHE_DIR", tmp_path / "cache")
    # Best practice: isolated filesystem + isolated config
```

## References

- **UNIFIED_TESTING_V2.MD** - Testing guidelines and patterns
- **pytest Documentation** - https://docs.pytest.org/
- **pytest-qt** - Qt testing with pytest
- **xdist** - Parallel test execution

## Audit Metadata

- **Date**: 2025-11-08
- **Scope**: tests/ directory (200+ files)
- **Guidelines**: UNIFIED_TESTING_V2.MD
- **Thoroughness**: Medium (4 categories)
- **Total Violations**: 42
- **Actionable Issues**: 2 (HIGH + MEDIUM)
- **Time to Fix**: ~2-3 hours (LOW effort)

## Next Steps

1. **Read** TEST_ISOLATION_AUDIT_SUMMARY.txt (5 min)
2. **Review** TEST_ISOLATION_AUDIT.md sections for your file
3. **Implement** fixes using provided code examples
4. **Verify** with test commands
5. **Commit** changes
6. **Run full suite** with `-n auto` to confirm

---

*For questions or clarifications, see the detailed audit report or memory file.*
