# CRITICAL: You're Running Old Cached Code!

## The Problem
Your application is crashing because it's running OLD cached Python bytecode (.pyc files) that don't match the current source code. The logs prove this - they show messages that no longer exist in the current code.

## Evidence
- Log shows: `"No cached data found - fetching fresh shots"` 
- Actual code: `"No cached data found - background worker will fetch shots shortly"`
- Found and cleaned **1626 .pyc files** causing the issue

## IMMEDIATE FIX REQUIRED

### Step 1: Stop the Application
```bash
# Kill any running instances
pkill -f shotbot
```

### Step 2: Clean ALL Python Cache
```bash
cd /mnt/c/CustomScripts/Python/PyFFMPEG/BB/shotbot

# Remove ALL cached Python files
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
find . -type f -name "*.pyo" -delete 2>/dev/null

# Also clean any user-specific cache
rm -rf ~/.cache/shotbot 2>/dev/null
```

### Step 3: Restart with Fresh Code
```bash
# Activate virtual environment
source venv/bin/activate

# Force Python to not create cache files for this run
export PYTHONDONTWRITEBYTECODE=1

# Run the application
python3 shotbot.py
```

## Why This Happened
1. Python was running cached bytecode (.pyc files) from OLD version
2. The refactoring changed method signatures but cache wasn't cleared
3. BackgroundRefreshWorker crashed trying to access `self.shot_model` which no longer exists

## The Fix Applied
- Removed concurrent refresh attempts
- Made BackgroundRefreshWorker thread-safe (only emits signals)
- All Qt object access now on main thread
- Worker no longer stores Qt object references

## Verification
After cleaning cache and restarting, you should see these NEW log messages:
- ✅ `"No cached data found - background worker will fetch shots shortly"`
- ✅ `"Background refresh: requesting update check"`
- ✅ `"Processing background refresh request"`

NOT the old ones:
- ❌ `"No cached data found - fetching fresh shots"`
- ❌ `"Background refresh: checking for shot updates"`

## Prevention
Add to your .bashrc or .zshrc:
```bash
alias shotbot='PYTHONDONTWRITEBYTECODE=1 python3 /path/to/shotbot.py'
```

Or add to shotbot.py at the very top:
```python
import sys
sys.dont_write_bytecode = True
```