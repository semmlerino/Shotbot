#!/bin/bash
set -o pipefail  # Enable pipefail to capture correct exit codes in pipelines
# ShotBot Terminal Dispatcher
# Reads commands from FIFO and executes them in the same terminal session

FIFO="${1:-/tmp/shotbot_commands.fifo}"
HEARTBEAT_FILE="/tmp/shotbot_heartbeat.txt"
DEBUG_LOG="$HOME/.shotbot/logs/dispatcher_debug.log"
PID_DIR="/tmp/shotbot_pids"

# Ensure log directory exists
mkdir -p "$(dirname "$DEBUG_LOG")"

# Create PID directory for process verification
mkdir -p "$PID_DIR"

# Debug mode flag (set SHOTBOT_TERMINAL_DEBUG=1 to enable)
# Default to enabled for investigating corruption issues
DEBUG_MODE=${SHOTBOT_TERMINAL_DEBUG:-1}

# Log function
log_debug() {
    if [ "$DEBUG_MODE" = "1" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [DEBUG] $*" >> "$DEBUG_LOG"
    fi
}

log_info() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $*" >> "$DEBUG_LOG"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >> "$DEBUG_LOG"
}

# Signal handling for cleanup and logging
cleanup_and_exit() {
    local exit_code=$1
    local reason=$2
    log_info "Dispatcher exiting: $reason (exit code: $exit_code)"
    # Clean up heartbeat file
    rm -f "$HEARTBEAT_FILE"
    # Close persistent FIFO file descriptor if open
    exec 3<&- 2>/dev/null || true
    exit "$exit_code"
}

# Trap EXIT and errors to log shutdown reason
# FIX: Removed ERR trap - user commands can legitimately fail (e.g., command not found)
# ERR trap would cause dispatcher to exit on ANY non-zero exit code, breaking all future launches
trap 'cleanup_and_exit 0 "Normal EXIT signal"' EXIT
trap 'cleanup_and_exit 130 "Caught SIGINT (Ctrl+C)"' INT
trap 'cleanup_and_exit 143 "Caught SIGTERM"' TERM

# Log startup
log_info "========================================="
log_info "Dispatcher starting"
log_info "PID: $$"
log_info "FIFO: $FIFO"
log_info "Heartbeat: $HEARTBEAT_FILE"
log_info "Debug log: $DEBUG_LOG"
log_info "Shell: $SHELL"
log_info "PATH: $PATH"

# Check if ws function is available
if type ws >/dev/null 2>&1; then
    log_info "ws function is available"
else
    log_error "WARNING: ws function not found!"
fi
log_info "========================================="

# Create FIFO if it doesn't exist
if [ ! -p "$FIFO" ]; then
    mkfifo "$FIFO" 2>/dev/null || {
        log_error "Could not create FIFO at $FIFO"
        echo "Error: Could not create FIFO at $FIFO"
        exit 1
    }
    log_info "Created FIFO at $FIFO"
fi

# Set up terminal appearance
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    ShotBot Command Terminal                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Ready for commands from ShotBot UI..."
echo "Terminal will remain open for all commands."
echo ""

# Function to detect if command is a GUI app
# Improved to extract actual executable from complex command chains
is_gui_app() {
    local cmd="$1"

    # Extract the final executable from rez/bash wrapper chains
    # Example: "rez env 3de -- bash -ilc \"ws /path && 3de -open /file\""
    # Should detect "3de" not "rez"

    # If command contains bash -ilc with quotes, extract the inner command
    if [[ "$cmd" =~ bash[[:space:]]+-[^\"]*\"(.*)\" ]]; then
        local inner_cmd="${BASH_REMATCH[1]}"

        # Extract the last command after && if present (handles multiple &&)
        # Use bash string manipulation to get the last segment after the last &&
        if [[ "$inner_cmd" == *"&&"* ]]; then
            # Get everything after the last &&
            local last_segment="${inner_cmd##*&&}"
            # Trim leading whitespace
            last_segment="${last_segment#"${last_segment%%[![:space:]]*}"}"
            # Extract first word (the command)
            local actual_cmd="${last_segment%% *}"

            # Check if this is a GUI app
            case "$actual_cmd" in
                nuke|maya|rv|3de|houdini|katana|mari|clarisse)
                    return 0
                    ;;
            esac
        fi
    fi

    # Fallback: Check if command starts with known GUI executables
    # This handles direct invocations without wrappers
    case "$cmd" in
        nuke\ *|maya\ *|rv\ *|3de\ *|houdini\ *|katana\ *|mari\ *|clarisse\ *)
            return 0
            ;;
    esac

    return 1
}

# Function to extract app name from command for PID file naming
# Returns the GUI app name (nuke, 3de, maya, etc.) or empty string
extract_app_name() {
    local cmd="$1"

    # If command contains bash -ilc with quotes, extract the inner command
    if [[ "$cmd" =~ bash[[:space:]]+-[^\"]*\"(.*)\" ]]; then
        local inner_cmd="${BASH_REMATCH[1]}"

        # Extract the last command after && if present
        if [[ "$inner_cmd" == *"&&"* ]]; then
            local last_segment="${inner_cmd##*&&}"
            last_segment="${last_segment#"${last_segment%%[![:space:]]*}"}"
            local actual_cmd="${last_segment%% *}"

            # Check if this is a known GUI app
            case "$actual_cmd" in
                nuke|maya|rv|3de|houdini|katana|mari|clarisse)
                    echo "$actual_cmd"
                    return 0
                    ;;
            esac
        fi
    fi

    # Fallback: Extract from direct invocations
    local first_word="${cmd%% *}"
    case "$first_word" in
        nuke|maya|rv|3de|houdini|katana|mari|clarisse)
            echo "$first_word"
            return 0
            ;;
    esac

    echo ""
    return 1
}

# Signal handling for defense in depth
# Ignore signals from backgrounded jobs to prevent read loop interruption
trap '' SIGCHLD SIGHUP SIGPIPE

# Open FIFO with persistent file descriptor to avoid reader gap race conditions
# Using FD 3 for persistent read access - this eliminates windows where no reader exists
log_info "Opening FIFO with persistent file descriptor"
exec 3< "$FIFO"

# Main command loop
# Using persistent FD 3 to read commands, avoiding race conditions where
# no reader exists between iterations (which would cause ENXIO errors on writes)
log_info "Entering main command loop"
while true; do
    # Read command from persistent FD 3
    # This keeps the FIFO open continuously, ensuring writes never fail with ENXIO
    if read -r cmd <&3; then
        # Skip empty commands
        if [ -z "$cmd" ]; then
            log_debug "Skipping empty command"
            continue
        fi

        # Log command received
        log_debug "Received command: $cmd (${#cmd} chars)"

        # Command sanity checks
        cmd_length=${#cmd}
        if [ "$cmd_length" -lt 3 ]; then
            log_error "Command too short ($cmd_length chars): '$cmd'"
            echo "" >&2
            echo "[ERROR] Command too short ($cmd_length chars): '$cmd'" >&2
            echo "[ERROR] Skipping potentially corrupted command" >&2
            continue
        fi

        # Check for obviously corrupted commands (no letters)
        if ! echo "$cmd" | grep -q '[a-zA-Z]'; then
            log_error "Command contains no letters: '$cmd'"
            echo "" >&2
            echo "[ERROR] Command contains no letters: '$cmd'" >&2
            echo "[ERROR] Skipping corrupted command" >&2
            continue
        fi

        # Check for special commands
        if [ "$cmd" = "EXIT_TERMINAL" ]; then
            log_info "Received EXIT_TERMINAL command"
            echo ""
            echo "Terminal closed by ShotBot."
            exit 0
        fi

        if [ "$cmd" = "CLEAR_TERMINAL" ]; then
            log_info "Received CLEAR_TERMINAL command"
            clear
            echo "╔══════════════════════════════════════════════════════════════╗"
            echo "║                    ShotBot Command Terminal                   ║"
            echo "╚══════════════════════════════════════════════════════════════╝"
            echo ""
            continue
        fi

        # Heartbeat responder
        if [ "$cmd" = "__HEARTBEAT__" ]; then
            log_debug "Received heartbeat ping, sending PONG"
            echo "PONG" > "$HEARTBEAT_FILE"
            continue
        fi

        # Display command being executed
        echo ""
        echo "────────────────────────────────────────────────────────────────"
        echo "▶ $(date '+%H:%M:%S') | Executing:"
        echo "  $cmd"
        echo "────────────────────────────────────────────────────────────────"
        echo ""

        # Execute command with dispatcher-controlled backgrounding
        # GUI apps are backgrounded here, after stripping any & from command_launcher.py
        if is_gui_app "$cmd"; then
            log_info "Executing GUI command (backgrounded): $cmd"
            echo "[Auto-backgrounding GUI application]"
            eval "$cmd &"
            gui_pid=$!
            # Give a moment for the app to start
            sleep 0.5
            log_info "Launched GUI app with PID: $gui_pid"

            # Write PID file for process verification (Phase 2)
            app_name=$(extract_app_name "$cmd")
            if [[ -n "$app_name" ]]; then
                timestamp=$(date '+%Y%m%d_%H%M%S')
                pid_file="$PID_DIR/${app_name}_${timestamp}.pid"
                echo "$gui_pid" > "$pid_file"
                log_info "Wrote PID file: $pid_file"
                echo "✓ Launched in background (PID: $gui_pid, file: $pid_file)"
            else
                echo "✓ Launched in background (PID: $gui_pid)"
            fi
        else
            # Execute command normally (blocking for non-GUI commands)
            log_info "Executing non-GUI command: $cmd"
            eval "$cmd"
            exit_code=$?
            if [ $exit_code -eq 0 ]; then
                log_info "Command completed successfully (exit code: 0)"
                echo ""
                echo "✓ Command completed successfully"
            else
                log_error "Command failed with exit code: $exit_code"
                echo ""
                echo "✗ Command exited with code: $exit_code"
            fi
        fi

    else
        # Read from FIFO failed
        log_error "Failed to read from FIFO (EOF or error)"
        echo "" >&2
        echo "[ERROR] Lost connection to FIFO" >&2
        break
    fi
done

# If we exit the loop, something went wrong
log_error "Exited main command loop unexpectedly"
cleanup_and_exit 1 "Exited command loop unexpectedly"