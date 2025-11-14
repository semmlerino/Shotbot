# FIFO IPC Issues - Exact Code Locations and Snippets

## ISSUE #1: BLOCKING LOCK DURING I/O RETRY LOOP

### File: `persistent_terminal_manager.py`

**Location**: Lines 889-986 (send_command method)

**Problem Section**:
```python
889  |        with self._write_lock:  # ← Lock acquired for entire retry loop
890  |            # ... health check ...
920  |            for attempt in range(max_retries):
921  |                try:
922  |                    fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
923  |                    with os.fdopen(fifo_fd, "wb", buffering=0) as fifo:
924  |                        fifo_fd = None
925  |                        _ = fifo.write(command.encode("utf-8"))
926  |                        _ = fifo.write(b"\n")
927  |
928  |                    self.logger.info(f"Successfully sent command to terminal: {command}")
929  |                    self.command_sent.emit(command)
930  |                    return True
931  |
932  |                except OSError as e:
933  |                    is_last_attempt = attempt >= max_retries - 1
934  |
935  |                    if e.errno == errno.ENOENT:
936  |                        if not is_last_attempt:
937  |                            self.logger.warning(
938  |                                f"FIFO missing, recreating (attempt {attempt + 1}/{max_retries})"
938  |                            )
939  |                            if self._ensure_fifo():
940  |                                time.sleep(_CLEANUP_POLL_INTERVAL_SECONDS)  # ← LOCK HELD!
941  |                                continue
942  |                        self.logger.error(f"Failed to send command after {attempt + 1} attempts: FIFO missing")
943  |
944  |                    elif e.errno == errno.ENXIO:
945  |                        if not is_last_attempt:
946  |                            self.logger.warning(
947  |                                f"No FIFO reader, retrying (attempt {attempt + 1}/{max_retries})"
948  |                            )
949  |                            time.sleep(0.5)  # ← LOCK HELD! (0.5s)
950  |                            continue
951  |                        self.logger.error(...)
952  |
953  |                    elif e.errno == errno.EAGAIN:
954  |                        if not is_last_attempt:
955  |                            backoff: float = 0.1 * (2 ** attempt)  # 0.1s, 0.2s, 0.4s
956  |                            self.logger.warning(
957  |                                f"FIFO buffer full, retrying after {backoff}s..."
958  |                            )
959  |                            time.sleep(backoff)  # ← LOCK HELD! (up to 0.4s)
960  |                            continue
961  |                        self.logger.error(...)
962  |
963  |                    return False
964  |            
965  |            return False  # ← Lock released here after all attempts
```

**Total Blocked Time Possible**:
- Attempt 1: ENOENT → _ensure_fifo() + sleep(0.1) + retry = ~0.1s
- Attempt 2: EAGAIN → sleep(0.2) + retry = 0.2s  
- Attempt 3: EAGAIN → sleep(0.4) = 0.4s
- **Total: ~0.7s per command, with 3 threads = 3+ second total serialization**

---

## ISSUE #2: CONCURRENT FIFO RECREATION RACE

### File: `persistent_terminal_manager.py`

**Location 1 - restart_terminal (holds _restart_lock)**:
Lines 1329-1365

```python
1329 |    with self._restart_lock:
1330 |        self.logger.info("Restarting terminal...")
1331 |        
1332 |        # Close existing terminal
1333 |        _ = self.close_terminal()
1334 |        time.sleep(_TERMINAL_RESTART_DELAY_SECONDS)
1335 |        
1336 |        # Close dummy writer FD before cleaning up FIFO
1337 |        self._close_dummy_writer_fd()
1338 |        
1339 |        # ATOMIC FIFO REPLACEMENT
1340 |        temp_fifo = f"{self.fifo_path}.{os.getpid()}.tmp"
1341 |        
1342 |        parent_dir = Path(self.fifo_path).parent
1343 |        parent_dir.mkdir(parents=True, exist_ok=True)
1344 |        
1345 |        # Clean up old FIFO
1346 |        if Path(self.fifo_path).exists():
1347 |            try:
1348 |                Path(self.fifo_path).unlink()  # ← Delete old FIFO
1349 |                parent_fd = os.open(str(parent_dir), os.O_RDONLY)
1350 |                try:
1351 |                    os.fsync(parent_fd)
1352 |                finally:
1353 |                    os.close(parent_fd)
1354 |                self.logger.debug(f"Removed stale FIFO at {self.fifo_path}")
1355 |            except OSError as e:
1356 |                self.logger.warning(f"Could not remove stale FIFO: {e}")
1357 |        
1358 |        # [RACE WINDOW - send_command could run here]
1359 |        
1360 |        try:
1361 |            os.mkfifo(temp_fifo, 0o600)  # ← Create new temp FIFO
1362 |            os.rename(temp_fifo, self.fifo_path)  # ← Atomically rename to final
1363 |            self.logger.debug(f"Atomically created FIFO at {self.fifo_path}")
1364 |        except OSError as e:
1365 |            ...
```

**Location 2 - send_command (does NOT hold _restart_lock)**:
Lines 920-941

```python
920 |            for attempt in range(max_retries):
921 |                try:
922 |                    fifo_fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
923 |                    # ← No _restart_lock held!
924 |                    # If restart_terminal deleted FIFO between check and open:
925 |                    # os.open returns ENOENT
926 |                
927 |                except OSError as e:
928 |                    if e.errno == errno.ENOENT:
929 |                        if not is_last_attempt:
930 |                            if self._ensure_fifo():  # ← Creates NEW FIFO
931 |                                # Now we have FIFO, but restart might overwrite it!
```

**Race Window**:
```
Line 1348: restart unlinks FIFO
Line 1350-1354: fsync (several microseconds)
    [send_command runs here]
    Line 930: _ensure_fifo() creates new FIFO
    Line 922: os.open() succeeds
    [Context switch back to restart]
Line 1361: os.mkfifo(temp_fifo) creates ANOTHER FIFO
Line 1362: os.rename(temp_FIFO, final_FIFO) OVERWRITES send_command's FIFO
```

---

## ISSUE #3: STALE PID FILE ACCUMULATION

### File: `terminal_dispatcher.sh`

**Location**: Lines 306-313

```bash
306 |                        if is_gui_app "$cmd"; then
307 |                            log_info "Executing GUI command (backgrounded): $cmd"
308 |                            echo "[Auto-backgrounding GUI application]"
309 |                            eval "$cmd &"
310 |                            gui_pid=$!
311 |                            sleep 0.5
312 |                            log_info "Launched GUI app with PID: $gui_pid"
313 |
314 |                            # Write PID file for process verification (Phase 2)
315 |                            app_name=$(extract_app_name "$cmd")
316 |                            if [[ -n "$app_name" ]]; then
317 |                                timestamp=$(date '+%Y%m%d_%H%M%S')
318 |                                pid_file="$PID_DIR/${app_name}_${timestamp}.pid"
319 |                                echo "$gui_pid" > "$pid_file"  # ← Files accumulate forever
320 |                                log_info "Wrote PID file: $pid_file"
321 |                                echo "✓ Launched in background (PID: $gui_pid, file: $pid_file)"
322 |                            else
323 |                                echo "✓ Launched in background (PID: $gui_pid)"
324 |                            fi
```

**Result After 30 Days of Use** (assuming 10 launches/day):
```bash
$ ls /tmp/shotbot_pids/ | wc -l
300  # 300 stale PID files

$ du -sh /tmp/shotbot_pids/
12K  # Filesystem overhead
```

**Performance Impact**:
```python
# In launch/process_verifier.py lines 117-135
pid_files = list(Path(self.PID_FILE_DIR).glob(f"{app_name}_*.pid"))
# With 300 files, glob() scans and returns all
# Then we iterate and read each one
```

---

## ISSUE #4: HEARTBEAT TIMEOUT RACE

### File: `persistent_terminal_manager.py`

**Location**: Lines 569-600 (_send_heartbeat_ping method)

```python
569 | def _send_heartbeat_ping(self, timeout: float = ...) -> bool:
570 |     """Send heartbeat and wait for response."""
571 |     
572 |     # Send heartbeat command
573 |     if not self._send_command_direct("__HEARTBEAT__"):
574 |         return False
574 |     
575 |     # Wait for response
576 |     start_time = time.time()
577 |     while time.time() - start_time < timeout:
578 |         if Path(self.heartbeat_path).exists():  # ← Check
579 |             try:
580 |                 with open(self.heartbeat_path) as f:  # ← Could fail
581 |                     response = f.read().strip()
582 |                 if response == "PONG":
583 |                     return True
584 |             except (FileNotFoundError, OSError) as e:  # ← File deleted between check and open
585 |                 self.logger.debug(f"Heartbeat file missing: {e}")
586 |         time.sleep(0.1)
587 |     
588 |     return False  # Timeout
```

**Race Condition**:
```
Python thread (health check)           Bash dispatcher
                                       Line 283: echo "PONG" > "${HEARTBEAT_FILE}.tmp"
                                       [Written but not moved yet]
Line 578: exists() → True
                                       [Context switch]
                                       Old file: line 283 `mv "${HEARTBEAT_FILE}.tmp"`
                                       File is now the new one
Line 580: open() → Opens file
                                       [Dispatcher cleanup runs]
                                       rm -f "$HEARTBEAT_FILE"  # Deletes just after open
Line 581: read() → FileNotFoundError
                                       [File deleted while we're reading!]
Line 585: Catches exception, continues looping
```

---

## ISSUE #5: FIFO PERMISSION ISSUES

### File: `persistent_terminal_manager.py`

**Location**: Lines 301-303 (_ensure_fifo method)

```python
301 |             os.mkfifo(self.fifo_path, 0o600)  # Only user can read/write
302 |             self.logger.debug(f"Created FIFO at {self.fifo_path}")
303 |         except OSError as e:
```

**Problem**: No verification that permissions are actually 0o600

```bash
# What might happen on some systems:
$ mkfifo -m 0o600 /tmp/test.fifo
$ stat -c "%a" /tmp/test.fifo
600  # Good, correct

# But with certain umasks:
$ umask 0o077
$ mkfifo -m 0o600 /tmp/test.fifo  
$ stat -c "%a" /tmp/test.fifo
600  # Still good (umask doesn't affect mkfifo -m when explicit mode given)

# However, on some systems, umask CAN affect mkfifo mode:
$ umask 0o022
$ mkfifo -m 0o666 /tmp/test.fifo
$ stat -c "%a" /tmp/test.fifo  
644  # Effective mode = 0o666 & ~0o022 = 0o644
```

**Recommendation**: Add explicit verification:
```python
os.mkfifo(self.fifo_path, 0o600)
# Verify permission
stat_info = Path(self.fifo_path).stat()
actual_mode = stat.S_IMODE(stat_info.st_mode)
if actual_mode != 0o600:
    os.chmod(self.fifo_path, 0o600)  # Force correct permissions
```

---

## ISSUE #6: ZOMBIE REAPER SUBPROCESS LEAK

### File: `terminal_dispatcher.sh`

**Location**: Lines 208-218

```bash
208 | # Start background zombie reaper to prevent accumulation
209 | (
210 |     while true; do
211 |         # Non-blocking wait for any child process
212 |         wait -n 2>/dev/null
213 |         # Small sleep to avoid busy-wait when no children
214 |         sleep 0.1
215 |     done
216 | ) &
217 | REAPER_PID=$!
218 |
```

**Problem**: REAPER_PID is captured but NEVER used

```bash
# Current code: no cleanup handler
trap 'cleanup_and_exit 0 "Normal EXIT signal"' EXIT
trap 'cleanup_and_exit 130 "Caught SIGINT"' INT
trap 'cleanup_and_exit 143 "Caught SIGTERM"' TERM

# cleanup_and_exit function (lines 37-46):
cleanup_and_exit() {
    local exit_code=$1
    local reason=$2
    log_info "Dispatcher exiting: $reason (exit code: $exit_code)"
    rm -f "$HEARTBEAT_FILE"
    exec 3<&- 2>/dev/null || true
    # ← NO kill $REAPER_PID!
    exit "$exit_code"
}
```

**Result**: When dispatcher exits, reaper becomes orphaned:
```
PID 1 (init)
└── REAPER_PID (infinite while loop, sleep 0.1)
    └── Running forever!
```

---

## ISSUE #9: NON-ATOMIC PID FILE WRITE

### File: `terminal_dispatcher.sh`

**Location**: Lines 319 (inside dispatch loop)

```bash
315 |                            app_name=$(extract_app_name "$cmd")
316 |                            if [[ -n "$app_name" ]]; then
317 |                                timestamp=$(date '+%Y%m%d_%H%M%S')
318 |                                pid_file="$PID_DIR/${app_name}_${timestamp}.pid"
319 |                                echo "$gui_pid" > "$pid_file"  # ← NOT ATOMIC!
320 |                                log_info "Wrote PID file: $pid_file"
```

**Comparison with Heartbeat (which IS atomic)**:
```bash
# Line 283 (ATOMIC - correct):
echo "PONG" > "${HEARTBEAT_FILE}.tmp" && mv "${HEARTBEAT_FILE}.tmp" "$HEARTBEAT_FILE"

# Line 319 (NON-ATOMIC - problematic):
echo "$gui_pid" > "$pid_file"
```

**Race Between Writes and Reads**:
```
Dispatcher echo (writing PID)          ProcessVerifier (process_verifier.py lines 117-135)
1. open("nuke_20251114_123456.pid")
2. write("12345") - partial write!
3. [File now contains "12345" but not yet flushed to disk]
4. [Context switch]
                                       1. glob() finds "nuke_20251114_123456.pid"
                                       2. open and read → "12345"
                                       3. psutil.Process(12345)
                                       4. "Process 12345 doesn't exist!" ← WRONG!
5. [Resume dispatcher]
6. write("\\n")
7. close() and flush to disk
```

---

## ISSUE #10: NO VALIDATION OF EXTRACTED APP NAME

### File 1: `terminal_dispatcher.sh`

**Location**: Lines 152-201 (extract_app_name function)

```bash
152 | extract_app_name() {
153 |     local cmd="$1"
154 |     
155 |     # If command contains bash -ilc with quotes, extract inner command
156 |     if [[ "$cmd" =~ bash[[:space:]]+-[^\"]*\"(.*)\" ]]; then
157 |         local inner_cmd="${BASH_REMATCH[1]}"
158 |         
159 |         if [[ "$inner_cmd" == *"&&"* ]]; then
160 |             local last_segment="${inner_cmd##*&&}"
161 |             last_segment="${last_segment#"${last_segment%%[![:space:]]*}"}"  # Trim space
162 |             local actual_cmd="${last_segment%% *}"  # First word
163 |             
164 |             case "$actual_cmd" in
165 |                 nuke|maya|rv|3de|houdini|katana|mari|clarisse)
166 |                     echo "$actual_cmd"  # ← Extracted name
167 |                     return 0
168 |             esac
169 |         fi
170 |     fi
171 |     
172 |     # Handle ws <workspace> && <command> format
173 |     if [[ "$cmd" =~ ws[[:space:]]+[^[:space:]]+[[:space:]]+\&\&[[:space:]]+(.+) ]]; then
174 |         local after_ws="${BASH_REMATCH[1]}"
174 |         local exe="${after_ws%% *}"
175 |         
176 |         case "$exe" in
177 |             nuke|maya|rv|3de|houdini|katana|mari|clarisse)
178 |                 echo "$exe"  # ← Extracted name
179 |                 return 0
180 |         esac
181 |     fi
182 |     
183 |     # Fallback: check first word
184 |     local first_word="${cmd%% *}"
185 |     case "$first_word" in
186 |         nuke|maya|rv|3de|houdini|katana|mari|clarisse)
187 |             echo "$first_word"  # ← Extracted name
188 |             return 0
189 |     esac
190 |     
191 |     echo ""  # ← Returns empty string if extraction fails!
192 |     return 1
```

**Location**: Lines 307-324 (where app_name is used)

```bash
315 |                            app_name=$(extract_app_name "$cmd")  # ← Could be empty!
316 |                            if [[ -n "$app_name" ]]; then  # ← Check for non-empty
317 |                                timestamp=$(date '+%Y%m%d_%H%M%S')
318 |                                pid_file="$PID_DIR/${app_name}_${timestamp}.pid"  # ← Filename has "__"!
319 |                                echo "$gui_pid" > "$pid_file"
320 |                                echo "✓ Launched in background (PID: $gui_pid, file: $pid_file)"
321 |                            else  # ← If extraction failed
322 |                                echo "✓ Launched in background (PID: $gui_pid)"
323 |                                # ← NO PID FILE CREATED!
324 |                            fi
```

### File 2: `launch/process_verifier.py`

**Location**: Lines 94-150 (_extract_app_name method and wait_for_process)

```python
094 | def _is_gui_app(self, command: str) -> bool:
095 |     """Check if command is a GUI application."""
096 |     # ... complex regex ...
097 |     return app_name in ['nuke', 'maya', '3de', 'rv', ...]
098 |
099 | def wait_for_process(self, command: str, ...) -> tuple[bool, str]:
100 |     """Wait for launched process to start and verify."""
101 |     
102 |     # Check if GUI app
103 |     if not self._is_gui_app(command):
104 |         return True, "Non-GUI command (no verification needed)"
105 |     
106 |     # Extract app name
107 |     app_name = self._extract_app_name(command)  # ← Could fail
108 |     if not app_name:
109 |         return True, "Could not extract app name (skipping verification)"
110 |         # ← Returns SUCCESS even though verification was SKIPPED!
```

**Problem**: Silent failure
```
Scenario:
1. Command: "badscript /path/to/nuke"  (script that launches nuke)
2. is_gui_app() → False (doesn't match regex)
3. wait_for_process() → Returns (True, "Non-GUI command")
4. Process verification SKIPPED, process never verified
5. User thinks app started when it might have crashed silently!
```

---

## Summary of All 10 Issues

| # | File | Lines | Issue | Severity |
|---|------|-------|-------|----------|
| 1 | persistent_terminal_manager.py | 889-986 | Lock held during sleeps | HIGH |
| 2 | persistent_terminal_manager.py | 1329-1365, 920-941 | FIFO race between restart and send | MEDIUM |
| 3 | terminal_dispatcher.sh | 306-313 | PID files accumulate forever | LOW |
| 4 | persistent_terminal_manager.py | 569-600 | Heartbeat file TOCTOU race | MEDIUM |
| 5 | persistent_terminal_manager.py | 301-303 | No permission verification | LOW |
| 6 | terminal_dispatcher.sh | 208-218, 37-46 | Zombie reaper not cleaned up | LOW |
| 7 | ~~persistent_terminal_manager.py~~ | ~~355-392~~ | ~~Double-open FD~~ | SAFE |
| 8 | terminal_dispatcher.sh | 41-42 | Stale heartbeat file | LOW |
| 9 | terminal_dispatcher.sh | 319 | Non-atomic PID write | MEDIUM |
| 10 | terminal_dispatcher.sh + process_verifier.py | 152-201, 99-109 | No app name validation | LOW |

