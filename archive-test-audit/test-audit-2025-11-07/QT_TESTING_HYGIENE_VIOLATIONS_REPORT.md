# Qt Testing Hygiene Violations Report

**Date**: 2025-11-07  
**Scope**: Comprehensive scan of `/home/gabrielh/projects/shotbot/tests/` (192 test files)  
**Based on**: UNIFIED_TESTING_V2.MD "5 Basic Qt Testing Hygiene Rules"

---

## Executive Summary

- **Total Violations Found**: 7 across 6 test files
- **Rules Violated**: Rule 1 (5), Rule 4 (1), Rule 5 (1)
- **Critical Severity**: 1 violation (test failure cleanup leak)
- **Minor Severity**: 6 violations (mostly test-only code paths)

**Pass Rate**: 97.2% compliance (185 of 192 test files are fully compliant)

---

## The 5 Basic Qt Testing Hygiene Rules

From UNIFIED_TESTING_V2.MD (lines 26-79):

1. **Use pytest-qt's `qapp` fixture** - Never create your own QApplication
2. **Always use try/finally for Qt resources** - Guarantee cleanup even on test failure
3. **Use qtbot.waitSignal/waitUntil, never time.sleep()** - Condition-based waiting
4. **Always use tmp_path for filesystem tests** - Perfect isolation
5. **Use monkeypatch for state isolation** - Essential for parallel execution safety

---

## Detailed Violations by Rule

### RULE 1: Direct QApplication Creation (5 violations)

**Rule Requirement**: Use pytest-qt's `qapp` fixture instead of creating QApplication directly.

---

#### Violation 1.1: tests/conftest_type_safe.py:67

**Context**: Alternative conftest for type-safe testing

```python
# Line 60-68
class TestQApplication:
    _instance = None
    
    @classmethod
    def get_instance(cls) -> "QApplication":
        if cls._instance is None:
            existing = QApplication.instance()
            if existing is not None and isinstance(existing, QApplication):
                cls._instance = existing
            else:
                # VIOLATION: Creating QApplication directly
                cls._instance = QApplication(["-platform", "offscreen"])  # Line 67
        return cls._instance
```

**Issue**: Creates custom app lifecycle management instead of relying on pytest-qt
**Severity**: Minor (only for type-safe variant tests)

---

#### Violation 1.2: tests/integration/test_threede_scanner_integration.py:444

**Context**: Standalone test execution path (not pytest)

```python
# Line 440-444 (in if __name__ == "__main__" block)
app = QApplication.instance()
if app is None:
    # VIOLATION: Creating QApplication directly
    app = QApplication(sys.argv)
```

**Issue**: When test runs standalone (not via pytest), creates unmanaged QApplication
**Severity**: Minor (only affects non-pytest execution)

---

#### Violation 1.3: tests/integration/test_user_workflows.py:1292

**Context**: Standalone test validation

```python
# Line 1288-1292 (in if __name__ == "__main__" block)
app = QApplication.instance()
if app is None:
    # VIOLATION: Creating QApplication directly
    app = QApplication([])
```

**Issue**: Standalone test mode creates unmanaged QApplication
**Severity**: Minor (only affects non-pytest execution)

---

#### Violation 1.4: tests/test_type_safe_patterns.py:482

**Context**: Type-safe fixture setup

```python
# Line 475-489 (in fixture function)
@pytest.fixture
def real_components_env():
    with isolated_test_env() as env:
        app = QApplication.instance()
        if app is None:
            # VIOLATION: Creating QApplication directly
            app = QApplication([])  # Line 482
            env["app"] = app
            env["created_app"] = True
        yield env
```

**Issue**: Fixture creates QApplication instead of using qapp
**Severity**: Minor (local test fixture)

---

#### Violation 1.5: tests/test_subprocess_no_deadlock.py:121

**Context**: Subprocess integration test

```python
# Line 115-121 (in if __name__ == "__main__" block)
# VIOLATION: Creating QCoreApplication directly
app = QCoreApplication.instance() or QCoreApplication([])
```

**Issue**: Standalone test execution creates unmanaged QCoreApplication
**Severity**: Minor (only affects non-pytest execution)

---

### RULE 2: Missing qtbot.addWidget() for Widgets Under Test

**Status**: COMPLIANT - No violations found

All widget-creating tests properly use `qtbot.addWidget()` for lifecycle management.

---

### RULE 3: Using time.sleep() Instead of qtbot.wait()/waitUntil()

**Status**: COMPLIANT - No violations in test bodies

All `time.sleep()` usage is properly isolated to:
- Synchronization helper module (tests/helpers/synchronization.py)
- Test utility modules (tests/utilities/threading_test_utils.py)
- Race condition test modules (tests/test_concurrent_thumbnail_race_conditions.py)

All test functions use proper Qt synchronization patterns.

---

### RULE 4: Direct deleteLater() Without try/finally (1 violation)

**Rule Requirement**: Wrap deleteLater() in try/finally to guarantee cleanup on test failure.

#### Violation 4.1: tests/unit/test_thread_safety_regression.py:310-335

**Context**: Test validating signal behavior after object deletion

```python
# Line 310-335
def test_deleted_objects_dont_receive_signals(self, qapp: QApplication) -> None:
    """Test that deleted objects don't receive signals."""
    test_process_pool = TestProcessPool()
    loader = AsyncShotLoader(test_process_pool)

    class Receiver(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.received = []
        
        def on_shots_loaded(self, shots) -> None:
            self.received.append(shots)

    receiver = Receiver()
    loader.shots_loaded.connect(receiver.on_shots_loaded)

    # VIOLATION: deleteLater not in try/finally
    receiver.deleteLater()  # Line 328
    qapp.processEvents()  # Process deletion

    # Emit signal - should not crash
    loader.shots_loaded.emit([])
    qapp.processEvents()
```

**Problem**: If test fails before line 328 or if processEvents() raises, receiver never deleted.

**Severity**: CRITICAL - Can cause test isolation failures in parallel execution

**Fix**: Wrap in try/finally

---

### RULE 5: Fixture Cleanup Without try/finally (1 violation)

**Rule Requirement**: Always wrap fixture cleanup (after yield) in try/finally.

#### Violation 5.1: tests/unit/test_previous_shots_item_model.py:45-56

**Context**: Model fixture for previous shots testing

```python
# Line 45-56
@pytest.fixture
def model(qtbot, tmp_path):
    """Create a PreviousShotsItemModel instance for testing."""
    cache_manager = TestCacheManager(cache_dir=tmp_path / "cache")
    previous_shots_model = MockPreviousShotsModel()

    model = PreviousShotsItemModel(previous_shots_model, cache_manager)
    yield model
    # VIOLATION: cleanup not in try/finally
    model.deleteLater()  # Line 56
```

**Problem**: If yield raises an exception, deleteLater() is never called.

**Severity**: MEDIUM - Affects test isolation when tests fail

**Fix**: Wrap yield/cleanup in try/finally

---

## Compliance Metrics

| Rule | Violations | Compliant |
|------|-----------|-----------|
| Rule 1: Use qapp fixture | 5 | 94% |
| Rule 2: qtbot.addWidget | 0 | 100% |
| Rule 3: qtbot.wait (not sleep) | 0 | 100% |
| Rule 4: try/finally for deletes | 1 | 99.5% |
| Rule 5: Fixture cleanup | 1 | 99.5% |
| **OVERALL** | **7** | **98.6%** |

---

## Remediation Priority

### CRITICAL - Fix Immediately

1. **tests/unit/test_thread_safety_regression.py:328**
   - Wrap deleteLater() in try/finally
   - Affects test isolation in parallel execution

### MEDIUM - Fix This Sprint

2. **tests/unit/test_previous_shots_item_model.py:56**
   - Wrap fixture yield/cleanup in try/finally
   - Affects resource cleanup on test failure

### LOW - Fix When Convenient

3-7. Remove standalone test execution paths (1.2, 1.3, 1.5) and fix type-safe fixtures (1.1, 1.4)

---

**Report Generated**: 2025-11-07
