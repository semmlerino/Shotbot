#!/bin/bash
# ShotBot Terminal Dispatcher
# Reads commands from FIFO and executes them in the same terminal session

FIFO="${1:-/tmp/shotbot_commands.fifo}"

# Create FIFO if it doesn't exist
if [ ! -p "$FIFO" ]; then
    mkfifo "$FIFO" 2>/dev/null || {
        echo "Error: Could not create FIFO at $FIFO"
        exit 1
    }
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

# Debug mode flag (set SHOTBOT_TERMINAL_DEBUG=1 to enable)
# Default to enabled for investigating corruption issues
DEBUG_MODE=${SHOTBOT_TERMINAL_DEBUG:-1}

# Signal handling for defense in depth
# Ignore signals from backgrounded jobs to prevent read loop interruption
trap '' SIGCHLD SIGHUP SIGPIPE

# Open FIFO with persistent file descriptor to eliminate race conditions
# This keeps a reader always present, preventing ENXIO errors in Python's _is_dispatcher_running()
# Without this, there's a race window between loop iterations where no reader exists
exec 3< "$FIFO"

# Main command loop
while true; do
    # Read command from persistent FIFO file descriptor
    if read -r cmd <&3; then
        # Skip empty commands
        if [ -z "$cmd" ]; then
            continue
        fi

        # Enhanced debug logging
        if [ "$DEBUG_MODE" = "1" ]; then
            echo "" >&2
            echo "[DEBUG] ========================================" >&2
            echo "[DEBUG] Received command from FIFO" >&2
            echo "[DEBUG] Command: $cmd" >&2
            echo "[DEBUG] Command length: ${#cmd} chars" >&2
            echo "[DEBUG] First 50 chars: ${cmd:0:50}" >&2
            echo "[DEBUG] Shell: $SHELL" >&2
            echo "[DEBUG] PATH: $PATH" >&2
            # Check if ws function is available
            if type ws >/dev/null 2>&1; then
                echo "[DEBUG] ws function is available" >&2
            else
                echo "[DEBUG] WARNING: ws function not found!" >&2
            fi
            echo "[DEBUG] ========================================" >&2
            echo "" >&2
        fi

        # Command sanity checks
        cmd_length=${#cmd}
        if [ "$cmd_length" -lt 3 ]; then
            echo "" >&2
            echo "[ERROR] Command too short ($cmd_length chars): '$cmd'" >&2
            echo "[ERROR] Skipping potentially corrupted command" >&2
            continue
        fi

        # Check for obviously corrupted commands (no letters)
        if ! echo "$cmd" | grep -q '[a-zA-Z]'; then
            echo "" >&2
            echo "[ERROR] Command contains no letters: '$cmd'" >&2
            echo "[ERROR] Skipping corrupted command" >&2
            continue
        fi
        
        # Check for special commands
        if [ "$cmd" = "EXIT_TERMINAL" ]; then
            echo ""
            echo "Terminal closed by ShotBot."
            # Close persistent FIFO file descriptor
            exec 3<&-
            exit 0
        fi
        
        if [ "$cmd" = "CLEAR_TERMINAL" ]; then
            clear
            echo "╔══════════════════════════════════════════════════════════════╗"
            echo "║                    ShotBot Command Terminal                   ║"
            echo "╚══════════════════════════════════════════════════════════════╝"
            echo ""
            continue
        fi
        
        # Strip trailing & patterns added by command_launcher.py
        # CRITICAL FIX for double-backgrounding bug
        # Must preserve closing quotes for rez commands
        original_cmd="$cmd"
        if [[ "$cmd" == *' &"' ]]; then
            # Rez command ending with ' &"'
            # Strip ' &"' and restore the closing quote
            cmd="${cmd% &\"}\""
        elif [[ "$cmd" == *' &' ]]; then
            # Direct command ending with ' &'
            cmd="${cmd% &}"
        elif [[ "$cmd" == *'&' ]]; then
            # Edge case ending with '&' (no space)
            cmd="${cmd%&}"
        fi

        # Debug logging to verify stripping
        if [ "$DEBUG_MODE" = "1" ]; then
            if [ "$original_cmd" != "$cmd" ]; then
                echo "[DEBUG] Stripped trailing & pattern" >&2
                echo "[DEBUG] Original: $original_cmd" >&2
                echo "[DEBUG] Stripped: $cmd" >&2
            else
                echo "[DEBUG] No & pattern to strip" >&2
            fi
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
            echo "[Auto-backgrounding GUI application]"
            if [ "$DEBUG_MODE" = "1" ]; then
                echo "[DEBUG] Executing GUI command: $cmd &" >&2
            fi
            eval "$cmd &"
            # Give a moment for the app to start
            sleep 0.5
            echo "✓ Launched in background (PID: $!)"
        else
            # Execute command normally (blocking for non-GUI commands)
            if [ "$DEBUG_MODE" = "1" ]; then
                echo "[DEBUG] Executing non-GUI command: $cmd" >&2
            fi
            eval "$cmd"
            exit_code=$?
            if [ $exit_code -eq 0 ]; then
                echo ""
                echo "✓ Command completed successfully"
            else
                echo ""
                echo "✗ Command exited with code: $exit_code"
            fi
        fi
        
    fi
done