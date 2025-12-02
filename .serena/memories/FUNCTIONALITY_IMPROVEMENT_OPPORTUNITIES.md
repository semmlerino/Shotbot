# Shotbot Functionality Improvement Opportunities

## Executive Summary

Comprehensive analysis of shotbot identified **8 concrete improvement areas** across error handling, user feedback, workflow automation, and configuration. These gaps don't represent bugs but rather missing convenience features and resilience enhancements that would improve user experience and reliability.

---

## 1. ERROR HANDLING GAPS

### 1.1 Missing Error Recovery for Failed Launches
**Location**: `command_launcher.py`, `launch_app()` method (lines 394-630)

**Issue**: 
- Launch failures don't provide recovery options
- No retry mechanism for transient failures (workspace initialization, package conflicts)
- Failed launches leave the application in an inconsistent state with no way to recover

**Example Scenario**:
```python
# Current behavior:
return self._execute_launch(full_command, app_name, has_rez_wrapper=should_wrap_rez)

# What happens if _execute_launch fails:
# - User sees error notification
# - App is now locked in a state where the shot is selected but the app didn't launch
# - User must manually restart or select a different shot
```

**Recommended Improvement**:
- Add automatic retry with exponential backoff (3 retries max)
- Track consecutive failures and suggest clearing cache/restarting
- Implement rollback mechanism to revert shot context if launch fails
- Show retry dialog instead of just error message

**Impact**: High - Prevents users from getting stuck
**Effort**: Medium - Requires refactoring launch error handling

---

### 1.2 No Validation of Workspace State Before Launch
**Location**: `command_launcher.py`, `_validate_workspace_before_launch()` (lines 899-948)

**Issue**:
- Workspace validation doesn't check for common issues:
  - Missing required subdirectories (maya/, nuke/, 3de/)
  - Insufficient permissions
  - Disk space available
  - VFX database connectivity
- Silent failures leave users confused

**Current Code**:
```python
def _validate_workspace_before_launch(self, workspace_path: str, app_name: str) -> bool:
    # Only checks if path exists - doesn't validate subdirs or permissions
```

**Recommended Improvement**:
- Check for app-specific subdirectories (maya workspace, nuke project, 3de scenes)
- Validate file permissions (read, write, execute)
- Check minimum disk space for expected operations
- Validate environment variables are set (SHOW, SEQUENCE, SHOT)
- Return detailed validation report for debugging

**Impact**: Medium - Improves predictability
**Effort**: Medium - Requires environment introspection code

---

### 1.3 Missing Undo/Recovery for Cache Operations
**Location**: `cache_manager.py` (entire file)

**Issue**:
- Cache clearing is destructive and permanent
- No way to recover deleted cache data
- Users can accidentally clear cache with no recovery option
- Incremental merge of 3DE scenes can hide data without recovery path

**Example**:
```python
# User clicks "Clear Cache" accidentally
cache_manager.clear_cache()  # Irreversible

# Later: user realizes they needed old 3DE scenes from previous session
# No recovery mechanism exists
```

**Recommended Improvement**:
- Implement cache versioning with backups (keep last 3 cache snapshots)
- Add "Undo Clear Cache" option for 60 seconds after clear
- Create cache restore dialog with recovery options
- Archive old cache files instead of deleting them
- Track cache mutations in a journal for debugging

**Impact**: Medium - Improves data safety
**Effort**: High - Requires versioning infrastructure

---

## 2. USER FEEDBACK GAPS

### 2.1 Missing Progress Indicators for Long Operations
**Location**: `main_window.py`, `_initial_load()` method (lines 749-857)

**Issue**:
- Background operations (shot discovery, 3DE scene scanning, thumbnail loading) lack progress feedback
- Users see "Loading..." with no indication of actual progress
- No way to estimate how long operations will take
- Canceled operations still leave UI in partial state

**Current Behavior**:
```python
self._update_status("Loading shots and scenes...")  # No progress percentage
# Background operations proceed with no feedback
# User waits indefinitely without knowing progress
```

**Recommended Improvement**:
- Add progress bar with percentage for long operations
- Show count of completed items (e.g., "Loaded 12/47 3DE scenes")
- Provide ETA based on average item processing time
- Show cancel button for user interruption
- Track and display partial results (show 12 scenes found so far)

**Impact**: High - Improves perceived responsiveness
**Effort**: Medium - Requires progress tracking infrastructure

---

### 2.2 No Notifications for Important Events
**Location**: `main_window.py` (throughout)

**Issue**:
- Users aren't notified of important events:
  - When cache expires and refresh is needed
  - When 3DE scenes are discovered/updated
  - When shot data changes (added/removed)
  - When workspace issues occur
- Silent background operations make app feel unresponsive

**Examples of Missing Notifications**:
```python
# 1. Cache expiration
# Current: silently re-fetches in background
# Better: "Shot cache expired, refreshing..."

# 2. New 3DE scenes discovered
# Current: they just appear
# Better: "Found 5 new 3DE scenes, added to Other 3DE tab"

# 3. Shots migrated to Previous
# Current: happens silently
# Better: "3 completed shots moved to Previous Shots tab"
```

**Recommended Improvement**:
- Emit notifications for:
  - Cache operations (expire, clear, refresh)
  - Data changes (shots added/removed, scenes discovered)
  - Workspace issues (permission denied, path not found)
  - Successful operations (crash recovery completed, settings saved)
- Use toast notifications for non-critical updates
- Use status bar messages with action buttons for important events

**Impact**: Medium - Improves transparency
**Effort**: Low - Mostly existing NotificationManager usage

---

### 2.3 No Visual Feedback for Active Operations
**Location**: `command_launcher.py`, `launch_app()` (lines 394-630)

**Issue**:
- Launch process has multiple steps but no visual indication
- Users don't know which step is executing:
  1. Validating workspace
  2. Finding scene files
  3. Building command
  4. Starting terminal
  5. Verifying application
- No indication that app is still launching (might appear frozen)

**Recommended Improvement**:
- Show step-by-step progress dialog:
  ```
  Launching 3de...
  ✓ Validating workspace
  ✓ Finding latest scene
  > Starting application... [20s elapsed]
  [Cancel]
  ```
- Update status bar with current step
- Show estimated time remaining based on typical launch times
- Allow user to cancel with proper cleanup

**Impact**: Medium - Improves user confidence
**Effort**: Medium - Requires launch refactoring

---

## 3. WORKFLOW INEFFICIENCY GAPS

### 3.1 No Batch Operations
**Location**: `shot_grid.py`, grid view implementations

**Issue**:
- Users can only operate on one shot at a time
- No way to:
  - Select multiple shots and launch them simultaneously
  - Batch recover crash files from multiple shots
  - Batch clear thumbnails for selected shots
  - Open multiple shots in different applications

**Recommended Improvement**:
- Add multi-select mode (Ctrl+Click, Shift+Range)
- Context menu with batch operations:
  - "Open in 3de" (launches all selected in separate terminals)
  - "Recover crashes" (batch recovery)
  - "Clear thumbnails"
  - "Copy shot info" (for reporting)
- Bulk operations progress dialog

**Impact**: Medium - Improves efficiency for power users
**Effort**: High - Requires grid view refactoring

---

### 3.2 No Keyboard Shortcuts for Common Actions
**Location**: `main_window.py`, `_setup_menu()` (lines 524-601)

**Issue**:
- Many common actions lack keyboard shortcuts:
  - No shortcut for quick launcher (Type "3", "N", "M", "R" to launch)
  - No shortcut for opening latest scene
  - No shortcut for switching tabs
  - No shortcut for filter/search
  - No shortcut for recover crashes

**Current Shortcuts**:
```python
refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)  # F5 ✓
increase_size_action.setShortcut(QKeySequence.StandardKey.ZoomIn)  # Ctrl++ ✓
# Missing many others
```

**Recommended Improvement**:
- Add global key press handler for quick launch:
  - "3" → Launch 3DE (if shot selected)
  - "N" → Launch Nuke
  - "M" → Launch Maya
  - "R" → Launch RV
  - "C" → Recover crashes
- Add shortcuts for tab switching:
  - Alt+1 → My Shots
  - Alt+2 → Other 3DE
  - Alt+3 → Previous Shots
- Add shortcut for search/filter (Ctrl+F)
- Display shortcut hints in UI

**Impact**: High - Significantly improves power user efficiency
**Effort**: Low - Mostly Qt KeyPress handling

---

### 3.3 No Session/Template System for Common Workflows
**Location**: Configuration system (config.py)

**Issue**:
- Every launch requires manual option selection
- No way to save launch templates:
  - "3DE with latest tracking file"
  - "Nuke with latest plate"
  - "Maya with playblast settings"
- Users must repeat the same selections every day

**Recommended Improvement**:
- Create launch templates/presets:
  ```
  Templates:
  - "3DE Standard" (open latest, auto-backup)
  - "Nuke Review" (open latest, create new file)
  - "Maya Finalize" (open latest, frame range, etc.)
  - Custom... [user creates custom template]
  ```
- Save templates with keyboard shortcuts or quick menu
- Allow template configuration (rename, edit, delete)
- Store in settings file for persistence

**Impact**: Medium - Improves repetitive workflow efficiency
**Effort**: Medium - Requires template config system

---

## 4. DATA SYNCHRONIZATION GAPS

### 4.1 Stale Data Without Active Polling
**Location**: `refresh_orchestrator.py` (main refresh coordination)

**Issue**:
- Cache TTL is 30 minutes but users don't know when refresh happens
- Shots list becomes stale without indication
- 3DE scene cache never automatically refreshes (persistent, requires manual refresh)
- Users might work with outdated data without realizing

**Current Behavior**:
```python
DEFAULT_TTL_MINUTES = 30  # Shots cache
# After 30 minutes, cache expires but users aren't notified
# Next refresh happens on demand or on app restart
```

**Recommended Improvement**:
- Add visible cache age indicator in status bar:
  ```
  "Loaded 47 shots [cached 12m ago] [Refresh]"
  ```
- Show warning when cache reaches 25 minutes old
- Implement smart auto-refresh:
  - Refresh when cache reaches 80% TTL
  - Batch refresh requests (refresh multiple things at once)
  - Background refresh without blocking UI
- Notify user when 3DE cache is stale (> 7 days old)

**Impact**: Medium - Improves data freshness awareness
**Effort**: Medium - Requires cache age tracking

---

### 4.2 No Conflict Detection for Concurrent Changes
**Location**: `cache_manager.py` (cache write operations)

**Issue**:
- If multiple instances of shotbot run, cache can be corrupted
- No detection of concurrent writes to cache files
- No versioning to detect stale reads
- Merged scene cache can lose data if multiple instances write simultaneously

**Recommended Improvement**:
- Implement optimistic concurrency with version numbers:
  ```json
  {
    "version": 3,
    "timestamp": "2025-11-30T10:30:00Z",
    "shots": [...],
    "_metadata": {"source_app_id": "shotbot-abc123"}
  }
  ```
- Detect stale reads and warn user
- Implement atomic writes with checksums
- Log concurrent write attempts for debugging

**Impact**: Low - Only affects multi-instance scenarios
**Effort**: Medium - Requires versioning infrastructure

---

## 5. CONFIGURATION GAPS

### 5.1 Hardcoded Values Should Be User-Configurable
**Location**: Various files with hardcoded constants

**Issue**:
- Many parameters are hardcoded that should be configurable:
  - Thumbnail size ranges (MIN: 100, MAX: 400)
  - Cache TTL (30 minutes)
  - Session pool sizes
  - Refresh intervals
  - Auto-recovery features
  - Rez environment wrapping mode

**Hardcoded Values**:
```python
# cache_manager.py
DEFAULT_TTL_MINUTES = 30  # Should be configurable
THUMBNAIL_SIZE = 256      # Should be user preference
THUMBNAIL_QUALITY = 85    # Should be user preference

# process_pool_manager.py
REAP_INTERVAL_MS = 2000   # Should be configurable

# config.py
DEFAULT_WINDOW_WIDTH = 1400  # Should be persistent
DEFAULT_WINDOW_HEIGHT = 900
```

**Recommended Improvement**:
- Move to settings dialog under "Advanced" tab
- Add user-configurable options:
  - Cache TTL and refresh behavior
  - Thumbnail size ranges and quality
  - Auto-refresh intervals
  - Rez wrapping behavior
  - Process pool size
  - Log verbosity level
- Validate values on change
- Provide presets (Conservative, Standard, Aggressive)

**Impact**: Low - Nice-to-have for advanced users
**Effort**: Medium - Requires settings dialog extension

---

### 5.2 No Migration Path for Configuration Changes
**Location**: `settings_manager.py`

**Issue**:
- If app settings format changes, users must manually reconfigure
- Old settings are silently ignored without warning
- No way to export/import settings for team sharing
- Settings are not documented or discoverable

**Recommended Improvement**:
- Implement settings schema versioning
- Auto-migrate old settings to new format
- Add import/export functionality
- Provide settings documentation in Help menu
- Show migration warnings for breaking changes

**Impact**: Low - Only matters for future changes
**Effort**: Low - Uses existing export/import code

---

## 6. NOTIFICATION/ALERT GAPS

### 6.1 No Warnings for Destructive Operations
**Location**: `cache_manager.py`, `shot_model.py`

**Issue**:
- Destructive operations proceed without confirmation:
  - Clear cache (deletes all cached data)
  - Recover crashes (modifies 3DE files)
  - Migrate shots (moves to Previous Shots)
- No confirmation dialogs
- No undo capability

**Recommended Improvement**:
- Add confirmation dialogs:
  ```
  "Clear Cache?"
  "This will delete all cached shots and scenes.
   You can re-fetch by clicking Refresh.
   [Cancel] [Clear Cache]"
  ```
- Show what will be deleted/affected
- Provide undo option for 60 seconds after operation
- Log destructive operations for audit trail

**Impact**: Medium - Improves data safety
**Effort**: Low - Mostly UI changes

---

### 6.2 No Alerts for App Launch Timeouts
**Location**: `command_launcher.py`, `process_executor.py`

**Issue**:
- App launch verification has timeout but no user notification
- If app fails to start, user waits silently
- No indication of what went wrong (permission, crash, missing, etc.)
- Duplicate launch attempts can spawn multiple instances

**Current Code**:
```python
# Timeout occurs but no user feedback
_ = self._on_app_verification_timeout()  # Silent
```

**Recommended Improvement**:
- Show dialog when app launch times out:
  ```
  "3DE Launch Timeout"
  "3DE did not start within 30 seconds.
   
   Possible causes:
   - Application is starting (might appear later)
   - Workspace path is invalid
   - System permissions issue
   
   [Retry] [Cancel] [View Log]"
  ```
- Prevent duplicate launches during verification
- Show application event log for debugging
- Suggest troubleshooting steps

**Impact**: Medium - Improves user confidence
**Effort**: Low - Mostly notification changes

---

## 7. UNDO/RECOVERY MECHANISM GAPS

### 7.1 No Undo for Filtering Actions
**Location**: `shot_grid.py`, filter implementations

**Issue**:
- Apply filter → accidentally clear search → can't easily restore filter
- No way to undo a show filter change
- Navigation back-button would be helpful

**Recommended Improvement**:
- Implement filter history:
  - Back arrow to restore previous filter
  - Breadcrumb showing applied filters
  - Quick filter presets (My Favorites, Recent, etc.)

**Impact**: Low - Low-frequency issue
**Effort**: Low - Mostly UI changes

---

### 7.2 No Recovery Info for Failed Operations
**Location**: Throughout launch and refresh code

**Issue**:
- Failed operations don't provide recovery information
- No "View Details" button for errors
- Error messages are vague (e.g., "Launch failed")
- No access to system logs

**Recommended Improvement**:
- Error dialogs with:
  - Detailed error message
  - "View Log" button to open relevant log section
  - Suggested solutions
  - "Report Bug" button with pre-filled info

**Impact**: Medium - Improves debugging
**Effort**: Medium - Requires error dialog refactoring

---

## 8. MISSING FEATURES SUMMARY TABLE

| Feature | Priority | Impact | Effort | Status |
|---------|----------|--------|--------|--------|
| **Retry mechanism for failed launches** | High | High | Medium | Not implemented |
| **Progress indicators for background ops** | High | High | Medium | Partial (no %) |
| **Keyboard shortcuts (3, N, M, R)** | High | High | Low | Not implemented |
| **Event notifications (important)** | High | Medium | Low | Partial |
| **Workspace validation (permissions, dirs)** | Medium | Medium | Medium | Partial |
| **Cache age indicator** | Medium | Medium | Low | Not implemented |
| **Error recovery suggestions** | Medium | Medium | Low | Not implemented |
| **Batch operations** | Medium | Medium | High | Not implemented |
| **Launch templates/presets** | Medium | Medium | Medium | Not implemented |
| **User-configurable settings** | Low | Low | Medium | Partial |
| **Cache versioning/undo** | Low | Medium | High | Not implemented |
| **Concurrent write detection** | Low | Low | Medium | Not implemented |

---

## Recommendations by Priority

### QUICK WINS (Low effort, High impact)
1. Add keyboard shortcuts for app launching (3, N, M, R)
2. Show cache age in status bar
3. Add error recovery suggestions in dialogs
4. Implement app launch timeout notifications

### MEDIUM EFFORT
1. Progress indicators with percentage and ETA
2. Workspace validation for common issues
3. Event notifications for data changes
4. Retry mechanism with exponential backoff
5. Launch template system

### STRATEGIC INVESTMENTS
1. Cache versioning and undo capability
2. Batch operations support
3. Concurrent write detection
4. Settings migration system

---

## Implementation Notes

- Most changes can be made incrementally without breaking changes
- Existing `NotificationManager` and `ProgressManager` can be leveraged
- Keyboard shortcuts can use existing Qt infrastructure
- Settings changes require SettingsManager extension

