# Linting and Type Checking Fix Plan
*Generated: 2025-08-26*

## Current State
- **Linting**: 146 remaining issues (775 auto-fixed)
- **Type Checking**: 2,070 errors, 650 warnings, 18,505 notes
- **Risk Level**: LOW - Application currently works despite issues

## Prioritized Fix Plan

### 🔴 PHASE 1: CRITICAL (15 minutes)
**Must fix to prevent runtime crashes**

1. **Fix Undefined Names (F821)**
   - `test_thumbnail_processor_thread_safety.py:647` - psutil not imported
   - Action: Add `psutil` to requirements-dev.txt OR use alternative method
   
2. **Fix Bare Except Clauses (E722)**
   - 6 instances total in:
     - `persistent_bash_session_refactored.py:324, 327`
     - Other locations
   - Action: Replace `except:` with `except Exception:` minimum

3. **Quick Verification**
   ```bash
   python3 test_app_startup.py
   python3 shotbot.py  # Quick launch test
   ```

### 🟠 PHASE 2: CORE STABILITY (1 hour)
**Fix core modules for reliability**

1. **persistent_bash_session.py**
   - Remove unused debug_utils imports
   - Fix type annotations for subprocess types
   - Ensure proper Optional handling

2. **process_pool_manager.py**
   - Remove unused fcntl import (line 18)
   - Fix unused debug_utils imports
   - Verify singleton pattern types

3. **Test Core Functionality**
   ```bash
   python3 test_shot_refresh.py
   pytest tests/unit/test_process_pool_manager.py -xvs
   ```

### 🟡 PHASE 3: AUTOMATED CLEANUP (30 minutes)
**Bulk fixes with automation**

1. **Remove Unused Imports**
   ```bash
   ruff check --fix --unsafe-fixes --select F401
   git diff  # Review changes
   ```

2. **Fix Unused Variables**
   ```bash
   ruff check --fix --select F841
   ```

3. **Fix F-strings Without Placeholders**
   ```bash
   ruff check --fix --select F541
   ```

### 🟢 PHASE 4: TYPE IMPROVEMENTS (2+ hours)
**Systematic type safety - Optional**

1. **Qt Enum Pattern Fix**
   - Search: `Qt\.([A-Z][a-zA-Z]+)(?!\.[A-Z])`
   - Review each for enum vs constant
   - Example: `Qt.UserRole` → `Qt.ItemDataRole.UserRole`

2. **Common Type Patterns**
   ```python
   # Before
   widget = self.some_widget  # Type unknown
   
   # After  
   widget: Optional[QWidget] = self.some_widget
   assert widget is not None
   ```

3. **Add Type Ignores Where Needed**
   ```python
   # For incomplete PySide6 stubs
   palette.setColor(QPalette.Window, color)  # type: ignore[attr-defined]
   ```

### 🔵 PHASE 5: CONFIGURATION (10 minutes)
**Improve tooling setup**

1. **Create .ruff.toml**
   ```toml
   [tool.ruff]
   line-length = 100
   target-version = "py38"
   
   [tool.ruff.lint]
   select = ["E", "F", "I"]
   ignore = ["E501"]  # Line length (use formatter)
   
   [tool.ruff.lint.per-file-ignores]
   "tests/*" = ["F401", "F841"]  # Allow unused in tests
   ```

2. **Update pyrightconfig.json**
   - Add more temporary file patterns to exclude
   - Consider `reportUnknownMemberType = false` for PySide6 issues

## What NOT to Fix

### ❌ Skip These
1. **Test file type errors** - Already excluded, low value
2. **3rd party library issues** - PySide6 incomplete stubs
3. **Working deprecated code** - If it works, don't break it
4. **Generated files** - Exclude in config instead

### ⚠️ Be Careful With
1. **"Unused" code that might be used dynamically**
2. **Exception handlers without understanding context**
3. **Type changes that could break runtime behavior**
4. **Removing imports that might be used in string eval()**

## Success Metrics

✅ **Phase 1-2 Complete When:**
- No F821 (undefined name) errors
- No E722 (bare except) errors  
- App starts successfully
- Shot refresh works

✅ **Phase 3 Complete When:**
- <100 linting errors remain
- No obvious unused imports in core modules
- Code is cleaner but still works

✅ **Phase 4-5 Complete When:**
- <500 type errors (from 2,070)
- Core modules have proper types
- Configuration prevents future issues

## Quick Commands

```bash
# Activate environment
source venv/bin/activate

# Check current state
ruff check . --statistics
basedpyright --stats

# Test application
python3 test_app_startup.py
python3 shotbot.py

# Aggressive fix
ruff check --fix --unsafe-fixes

# Type check only core modules
basedpyright persistent_bash_session.py process_pool_manager.py main_window.py shot_model.py
```

## Estimated Timeline
- **Minimum (Critical only)**: 15 minutes
- **Recommended (Phase 1-3)**: 2 hours
- **Complete (All phases)**: 4+ hours

## Risk Assessment
- **Current Risk**: LOW - App works despite issues
- **During Fixes**: MEDIUM - Could break working code
- **After Phase 1-2**: LOW - Critical issues resolved
- **After Complete**: VERY LOW - Clean, maintainable code