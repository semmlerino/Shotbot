# Qt Signal Mocking - Quick Reference

## Status: ✅ EXCELLENT (No Critical Issues)

---

## Key Findings

| Finding | Status | Files | Action |
|---------|--------|-------|--------|
| @patch on signal handlers | ✅ NONE FOUND | N/A | Continue current approach |
| Proper disconnect/reconnect | ✅ EXEMPLARY | 3 locations | Document as best practice |
| Implicit cleanup (fixture-based) | ✅ ACCEPTABLE | 21+ locations | Optional: Add explicit cleanup |
| Intentional error testing | ✅ CORRECT | 1 location | No changes needed |

---

## Critical Pattern: EXEMPLARY (test_launcher_panel_integration.py)

**Correct way to mock a signal handler:**

```python
# 1. Save original
original = window.launcher_panel.app_launch_requested.connect(controller.launch_app)

# 2. Disconnect original
window.launcher_panel.app_launch_requested.disconnect(controller.launch_app)

# 3. Connect mock
window.launcher_panel.app_launch_requested.connect(mock_launch_app)

try:
    # 4. Test
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
finally:
    # 5. Cleanup: disconnect mock, reconnect original
    window.launcher_panel.app_launch_requested.disconnect(mock_launch_app)
    window.launcher_panel.app_launch_requested.connect(original)
```

**Why This Matters:**
- Prevents double execution (original + mock both running)
- Ensures only mock executes during test
- Guarantees original is reconnected after test

---

## Anti-Pattern: NEVER DO THIS

```python
# ❌ WRONG - causes double execution
@patch.object(controller, "on_signal_received")
def test_something(mock_handler):
    # BOTH original on_signal_received() AND mock execute!
    # Defeats the entire purpose of mocking
    pass
```

---

## Low-Risk Implicit Cleanup (Acceptable)

For test-local signal connections that don't affect other tests:

```python
# ✅ Acceptable if object is destroyed at test end
model.refresh_started.connect(lambda: signal_order.append("started"))
# Qt cleanup handles disconnection via parent destruction
```

---

## Files to Reference

- **EXEMPLARY:** `/home/gabrielh/projects/shotbot/tests/integration/test_launcher_panel_integration.py:230-256`
- **ACCEPTABLE:** `/home/gabrielh/projects/shotbot/tests/integration/test_launcher_workflow_integration.py:263-266`
- **FULL AUDIT:** `/home/gabrielh/projects/shotbot/QT_SIGNAL_MOCKING_AUDIT.md`

---

## Recommendation

✅ **No action required.** The codebase correctly avoids the critical Qt signal mocking anti-pattern.

Optional: Add a note in `UNIFIED_TESTING_V2.MD` documenting the proper signal mocking pattern (see exemplary file above).

