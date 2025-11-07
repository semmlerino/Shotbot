# Debug Guide for Shotbot

This guide explains how to diagnose and debug issues with Shotbot, including crashes, hangs, and performance problems.

## Quick Start

### Enable Verbose Debug Logging

```bash
# Option 1: Environment variable
export SHOTBOT_DEBUG_VERBOSE=1
python shotbot.py

# Option 2: Using debug wrapper script
./run_debug.sh

# Option 3: Debug diagnostic script
python debug_crash_verbose.py
```

## Debug Logging Levels

### Standard Debug Mode
Enable with `SHOTBOT_DEBUG=1`:
- Basic debug information
- Command execution logs
- Error details

### Verbose Debug Mode
Enable with `SHOTBOT_DEBUG_VERBOSE=1`:
- **ProcessPoolManager**: Session lifecycle, pool management, command routing
- **PersistentBashSession**: Initialization steps, buffer I/O, marker tracking
- **ShotModel**: Workspace command execution, parsing details
- **MainWindow**: Startup sequence, component initialization
- Detailed timing information
- File descriptor tracking
- Buffer state logging

## Debug Scripts

### `debug_crash_verbose.py`
Comprehensive diagnostic script that tests all components in isolation:
- ProcessPoolManager initialization
- Qt application creation
- Command execution
- ShotModel operations
- MainWindow initialization
- Performance metrics

Usage:
```bash
python debug_crash_verbose.py
# Creates timestamped log file: debug_crash_YYYYMMDD_HHMMSS.log
```

### `run_debug.sh`
Wrapper script to run Shotbot with full debug logging:
```bash
./run_debug.sh
# Output goes to console and shotbot_debug_YYYYMMDD_HHMMSS.log
```

## Common Issues and Debug Steps

### 1. Application Hangs on Startup

**Symptoms**: Application freezes after starting, no UI appears

**Debug Steps**:
1. Enable verbose logging: `SHOTBOT_DEBUG_VERBOSE=1 python shotbot.py`
2. Look for "Creating session" messages - should only appear on first command
3. Check for "Session initialized successfully" messages
4. Verify Qt initialization completes

**Key Log Messages**:
```
LAZY INIT: Creating 3 sessions for pool type: workspace
Session initialized successfully (non-blocking)
MainWindow initialization completed successfully
```

### 2. Pipe Buffer Deadlock

**Symptoms**: Commands timeout, processes hang

**Debug Steps**:
1. Check for timeout messages in logs
2. Look for buffer read operations that don't complete
3. Verify marker messages are found

**Key Log Messages**:
```
[session_id] Waiting for initialization marker: SHOTBOT_INIT_xxxxx
[session_id] Found marker, command complete
[session_id] Timeout reached after X.XXs
```

### 3. Qt/Subprocess Conflicts

**Symptoms**: Crashes during Qt initialization

**Debug Steps**:
1. Verify lazy initialization is working
2. Check file descriptor numbers before/after subprocess creation
3. Ensure sessions are created AFTER Qt init

**Key Log Messages**:
```
Pool structure created, no sessions yet (lazy init)
QApplication created: <PySide6.QtWidgets.QApplication...>
This is the FIRST use of workspace pool - creating sessions now
```

### 4. Command Execution Failures

**Symptoms**: Commands fail or return empty results

**Debug Steps**:
1. Check ProcessPoolManager cache hit/miss
2. Verify session selection and health
3. Look for command send/receive confirmation

**Key Log Messages**:
```
Cache MISS for command: ws -sg... - will execute
Selected session workspace_0 (index 0/3)
Session workspace_0 is alive and ready
Command sent to stdin and flushed
```

## Performance Analysis

### View Metrics
The debug diagnostic script shows performance metrics:
```
ProcessPoolManager metrics:
  Subprocess calls: 2
  Cache hits: 0
  Cache misses: 2
  Average response time: 1234.56ms
  workspace pool: 3 sessions
    - workspace_0: alive=True, commands=1, idle=5.2s
```

### Session Health
Monitor session status in verbose logs:
- Session creation time
- Commands executed per session
- Idle time
- Restart attempts

## Log File Locations

- **Debug diagnostic**: `debug_crash_YYYYMMDD_HHMMSS.log`
- **Shotbot debug**: `shotbot_debug_YYYYMMDD_HHMMSS.log`
- **Standard logs**: `~/.shotbot/logs/`

## Environment Variables

| Variable | Values | Description |
|----------|--------|-------------|
| `SHOTBOT_DEBUG` | 0/1 | Enable basic debug logging |
| `SHOTBOT_DEBUG_VERBOSE` | 0/1 | Enable verbose debug logging |
| `QT_DEBUG_PLUGINS` | 0/1 | Debug Qt plugin loading |
| `QT_LOGGING_RULES` | `*.debug=true` | Enable Qt debug output |

## Reporting Issues

When reporting issues, please include:
1. Output from `debug_crash_verbose.py`
2. Log file with `SHOTBOT_DEBUG_VERBOSE=1` enabled
3. System information (OS, Python version, Qt version)
4. Steps to reproduce the issue

## Advanced Debugging

### GDB Debugging
```bash
gdb python3
(gdb) run shotbot.py
(gdb) bt  # Get backtrace on crash
```

### Strace System Calls
```bash
strace -f -e trace=process python3 shotbot.py
```

### Python Profiling
```bash
python -m cProfile -o profile.stats shotbot.py
python -m pstats profile.stats
```

## Fix History

### Linux Startup Hang (2025-08-12)
- **Issue**: Application hung during startup on Linux
- **Cause**: Pipe buffer deadlock and Qt/subprocess file descriptor conflicts
- **Fix**: Implemented lazy session initialization
- **Verification**: Sessions now created on first use, not during module import