# Shotbot Logging Investigation Report

## Issue Found and Fixed

### Root Cause
The logging was not working correctly because the root logger level was set to `INFO`, which filtered out all `DEBUG` messages before they could reach the handlers, even when `SHOTBOT_DEBUG=1` was set.

### The Problem
In `shotbot.py`, the setup_logging() function had:
```python
root_logger.setLevel(logging.INFO)  # This was the issue
```

This meant that even though:
- The file handler was set to `DEBUG` level
- The console handler was set to `DEBUG` level when `SHOTBOT_DEBUG=1`
- Module loggers were trying to emit DEBUG messages

All DEBUG messages were being filtered out at the root logger level before reaching any handlers.

### The Fix
Changed line 36 in `shotbot.py`:
```python
root_logger.setLevel(logging.DEBUG)  # Set to DEBUG to allow all messages through
```

Now the root logger passes all messages through, and the individual handlers control what level they display based on their own settings.

## How Logging Works Now

1. **File Logging**: Always logs at DEBUG level to `~/.shotbot/logs/shotbot.log`
2. **Console Logging**: 
   - Without `SHOTBOT_DEBUG=1`: Only shows WARNING and above
   - With `SHOTBOT_DEBUG=1`: Shows all levels including DEBUG

## Verification

After the fix:
- Log file receives all messages (DEBUG and above)
- Console shows DEBUG messages when `SHOTBOT_DEBUG=1` is set
- Module loggers throughout the codebase can now emit DEBUG messages successfully

## Debug Messages Available

The codebase has extensive debug logging in place:
- Path validation and caching (utils.py)
- 3DE scene discovery process (threede_scene_finder.py)
- Thumbnail loading (thumbnail_widget_base.py)
- Cache operations (cache_manager.py)
- Configuration loading (launcher_config.py)
- And many more...

These debug messages will now be visible when running with `SHOTBOT_DEBUG=1`.