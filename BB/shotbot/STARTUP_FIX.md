# Startup Fix for Empty Cache

## Problem
When the application started with no cached data (first run or cleared cache), it would show an empty screen indefinitely because:
1. `_initial_load()` only displayed cached data if it existed
2. No fetch was triggered when cache was empty
3. BackgroundRefreshWorker waited 10 minutes before first check

## Root Cause
The cache optimization changes removed the immediate fetch on startup, assuming cached data would always exist. This broke the first-run experience.

## Solution

### 1. Immediate Fetch on Empty Cache
In `_initial_load()`, when no cached data exists:
```python
else:
    self._update_status("Loading shots and scenes...")
    # No cache exists - trigger immediate fetch
    logger.info("No cached data found - fetching fresh shots")
    QTimer.singleShot(0, self._refresh_shots)
```

### 2. Background Worker Immediate Check
Modified `BackgroundRefreshWorker.run()` to check immediately on startup:
```python
def run(self):
    logger.info("Background refresh worker started")
    
    # Do an immediate check on startup (after a short delay to let UI settle)
    self.msleep(2000)  # 2 second delay to let initial load complete
    
    first_run = True
    while not self._stop_requested:
        # Only wait for interval after first run
        if not first_run:
            self.msleep(self._refresh_interval_ms)
        else:
            first_run = False
```

## Impact
- **First Run**: Application now fetches shots immediately when no cache exists
- **Startup Time**: 2-second delay for background worker ensures UI is ready
- **User Experience**: No more empty screen on first launch
- **Cache Benefits**: Still maintains instant loading when cache exists

## Testing
1. Clear cache: `rm -rf ~/.shotbot/cache`
2. Start application
3. Verify shots load within 2-3 seconds
4. Check logs for:
   - "No cached data found - fetching fresh shots"
   - "Background refresh: checking for shot updates"

## Timeline
- **Immediate (0ms)**: Display cached data if available
- **Immediate (0ms)**: Trigger fetch if no cache
- **2 seconds**: Background worker first check
- **10 minutes**: Subsequent background checks