# Global State Isolation Audit - Start Here

## Overview

This audit identified **9 high-risk violations** and **4+ medium-risk violations** in the test suite that can cause cross-test contamination, particularly in parallel test execution with `pytest-xdist`.

## Three-Step Quick Start

### Step 1: Understand the Problem (2 minutes)

Read: [GLOBAL_STATE_ISOLATION_QUICK_SUMMARY.txt](./GLOBAL_STATE_ISOLATION_QUICK_SUMMARY.txt)

This file contains:
- Quick summary of violations
- Exact line numbers and file locations
- Impact assessment
- Recommended actions by priority

### Step 2: Review Full Analysis (10 minutes)

Read: [GLOBAL_STATE_ISOLATION_REPORT.md](./GLOBAL_STATE_ISOLATION_REPORT.md)

This file contains:
- Root cause analysis
- Cross-test contamination scenarios
- Detailed recommendations by priority level
- Monkeypatch usage patterns (safe vs unsafe)
- Success criteria and verification checklist

### Step 3: Deep Dive into Details (20 minutes)

Read: [GLOBAL_STATE_ISOLATION_VIOLATIONS_INDEX.md](./GLOBAL_STATE_ISOLATION_VIOLATIONS_INDEX.md)

This file contains:
- Violation details organized by file
- Line-by-line code examples
- Pattern analysis
- Execution order vulnerability demonstrations
- Specific file changes required

---

## Executive Summary

### What Was Found

**9 Critical Violations** - Direct modifications to `os.environ` without proper cleanup:
- 5 violations in `tests/integration/test_cross_component_integration.py` (lines 253, 607, 679, 772, 812)
- 2 violations in `tests/integration/test_feature_flag_switching.py` (lines 136, 187)
- 1 violation in `tests/integration/test_feature_flag_switching.py` (lines 93-96)

**4+ Medium Violations** - Config.SHOWS_ROOT access without verified isolation:
- `tests/unit/test_main_window.py` (10 occurrences)
- `tests/unit/test_base_shot_model.py` (3 occurrences)
- Other unit tests (multiple occurrences)

### Why It Matters

Current state:
- 2,296+ tests passing with serial execution
- Potential failures with parallel execution (`pytest-xdist`)
- Test results depend on execution order
- Cross-test environment pollution possible

After fixes:
- 100% test isolation guaranteed
- Safe parallel execution with any `-n` value
- Order-independent, reproducible test runs
- No cross-test environment pollution

### The Problem in 30 Seconds

```python
# ❌ BAD - Found 8 times
def test_something():
    os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"  # Sets but never restores!
    # ... test code ...
    # Environment variable persists for next test!

# ✅ GOOD - Use this instead
def test_something(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", "1")  # Auto-restores!
    # ... test code ...
    # Auto-cleaned up when test ends
```

---

## Critical Violations (Immediate Action Required)

### Violation 1: Unprotected Environment Variable in test_cross_component_integration.py

**Files**: `tests/integration/test_cross_component_integration.py`
**Lines**: 253, 607, 679, 772, 812
**Pattern**: `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"` with no cleanup
**Impact**: Sets flag that affects all subsequent tests
**Severity**: HIGH

**Fix**:
```python
# Before: ❌
def test_selection_propagates_across_tabs(self, qapp, qtbot, tmp_path):
    os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"

# After: ✅
def test_selection_propagates_across_tabs(self, qapp, qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", "1")
```

### Violation 2: Unprotected Environment Variable in test_feature_flag_switching.py

**Files**: `tests/integration/test_feature_flag_switching.py`
**Lines**: 136, 187
**Pattern**: `os.environ["SHOTBOT_USE_LEGACY_MODEL"] = ...` without proper cleanup
**Impact**: Flag state affects subsequent tests
**Severity**: HIGH

**Fix**: Apply same pattern as above - use `monkeypatch.setenv()`

### Violation 3: Missing Integration Test Isolation

**Issue**: No `tests/integration/conftest.py` exists to provide autouse isolation
**Impact**: Integration tests can pollute unit tests and each other
**Severity**: HIGH

**Fix**: Create `tests/integration/conftest.py` with autouse isolation fixture

---

## What Each Report Contains

### GLOBAL_STATE_ISOLATION_QUICK_SUMMARY.txt (4 KB)
- At-a-glance violation summary
- Exact line numbers
- Recommended fixes by priority
- Impact assessment
- Cross-test contamination scenarios

**Use this if you**: Need quick reference or are presenting findings

### GLOBAL_STATE_ISOLATION_REPORT.md (12 KB)
- Root cause analysis
- Full technical details
- Monkeypatch usage patterns
- Contamination scenarios with code examples
- Recommendations by priority (Critical → Low)
- Success criteria and verification checklist

**Use this if you**: Need to understand the "why" and "how to fix"

### GLOBAL_STATE_ISOLATION_VIOLATIONS_INDEX.md (12 KB)
- Detailed violation locations by file
- Line-by-line code examples
- Pattern analysis and categorization
- Execution order vulnerability demonstrations
- Specific file changes required

**Use this if you**: Need exact locations and code patterns to fix

---

## Priority of Fixes

### Priority 1 - CRITICAL (Do This Week)

**8 unprotected os.environ assignments**
- Files: test_cross_component_integration.py (5), test_feature_flag_switching.py (2)
- Fix: Add `monkeypatch` parameter, use `monkeypatch.setenv()`
- Time estimate: 30 minutes

**Create tests/integration/conftest.py**
- File: tests/integration/conftest.py (NEW)
- Fix: Add autouse isolation fixture
- Time estimate: 15 minutes

### Priority 2 - HIGH (Do This Month)

**Verify Config.SHOWS_ROOT isolation**
- Files: test_main_window.py, test_base_shot_model.py, others
- Check: All tests have `monkeypatch` parameter
- Time estimate: 1-2 hours

**Run verification tests**
- Serial: `pytest tests/`
- Parallel: `pytest tests/ -n 2`
- Shuffled: `pytest tests/ --random-order`
- Time estimate: 30 minutes

### Priority 3 - MEDIUM (Ongoing)

**Standardize environment handling**
- Pattern: All tests use monkeypatch or @patch.dict
- Never: Direct `os.environ["VAR"] = "value"`
- Scope: All new tests going forward

---

## How to Apply Fixes

### Fix Type 1: Replace Direct Assignment

```python
# File: test_cross_component_integration.py, line 253
# BEFORE (❌):
def test_selection_propagates_across_tabs(
    self,
    qapp: QApplication,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    os.environ["SHOTBOT_USE_LEGACY_MODEL"] = "1"

# AFTER (✅):
def test_selection_propagates_across_tabs(
    self,
    qapp: QApplication,
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # ADD
) -> None:
    monkeypatch.setenv("SHOTBOT_USE_LEGACY_MODEL", "1")  # REPLACE
```

Apply to lines: 253, 607, 679, 772, 812 in test_cross_component_integration.py
Apply to lines: 136, 187 in test_feature_flag_switching.py

### Fix Type 2: Create Integration Conftest

Create file: `tests/integration/conftest.py`

```python
"""Integration test fixtures and configuration."""

import os
from typing import Generator

import pytest


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Auto-isolate environment variables in integration tests.
    
    Prevents cross-test contamination from os.environ modifications
    in integration tests that create MainWindow instances.
    """
    # Save original environment
    original_env = dict(os.environ)
    
    yield
    
    # Restore after test - this ensures even if tests don't use monkeypatch,
    # we still restore the environment
    os.environ.clear()
    os.environ.update(original_env)
```

---

## Verification Steps

After applying fixes:

```bash
# 1. Run tests serially (slowest, most stable)
~/.local/bin/uv run pytest tests/ --maxfail=5 -v

# 2. Run tests in parallel (faster, good stress test)
~/.local/bin/uv run pytest tests/ -n 2 --maxfail=5 -v

# 3. Run tests in random order (detects order dependencies)
~/.local/bin/uv run pytest tests/ --random-order --maxfail=5 -v

# All three must pass with zero failures
```

---

## Related Documentation

- **UNIFIED_TESTING_V2.MD** - Complete testing guidelines and best practices
- **pyproject.toml** - Pytest configuration (pytest.ini equivalent)

---

## Questions?

Refer to the specific report files:
1. **Quick answer?** → GLOBAL_STATE_ISOLATION_QUICK_SUMMARY.txt
2. **Understanding?** → GLOBAL_STATE_ISOLATION_REPORT.md
3. **Exact locations?** → GLOBAL_STATE_ISOLATION_VIOLATIONS_INDEX.md

---

## Audit Metadata

- **Audit Date**: November 7, 2025
- **Scope**: `/home/gabrielh/projects/shotbot/tests/`
- **Search Depth**: Medium (focused on Config and os.environ patterns)
- **Files Analyzed**: 53 test files
- **Violations Found**: 9 HIGH, 4+ MEDIUM
- **Reports Generated**: 3 comprehensive documents

---

**Next Step**: Read [GLOBAL_STATE_ISOLATION_QUICK_SUMMARY.txt](./GLOBAL_STATE_ISOLATION_QUICK_SUMMARY.txt)
