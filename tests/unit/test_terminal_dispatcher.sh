#!/bin/bash
# Tests for terminal_dispatcher.sh
# This tests the bash script behavior, particularly the GUI app detection

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Find the dispatcher script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DISPATCHER_SCRIPT="$PROJECT_ROOT/terminal_dispatcher.sh"

if [ ! -f "$DISPATCHER_SCRIPT" ]; then
    echo -e "${RED}ERROR: Could not find terminal_dispatcher.sh at $DISPATCHER_SCRIPT${NC}"
    exit 1
fi

# Source the is_gui_app function from the dispatcher script
# Extract just the function definition for testing
eval "$(sed -n '/^is_gui_app()/,/^}/p' "$DISPATCHER_SCRIPT")"

# Test helper functions
test_start() {
    local test_name="$1"
    TESTS_RUN=$((TESTS_RUN + 1))
    echo -n "Test $TESTS_RUN: $test_name ... "
}

test_pass() {
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo -e "${GREEN}PASS${NC}"
}

test_fail() {
    local message="$1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    echo -e "${RED}FAIL${NC}"
    echo "  $message"
}

assert_true() {
    local cmd="$1"
    local description="$2"

    if $cmd; then
        return 0
    else
        test_fail "$description"
        return 1
    fi
}

assert_false() {
    local cmd="$1"
    local description="$2"

    if ! $cmd; then
        return 0
    else
        test_fail "$description"
        return 1
    fi
}

# ============================================================================
# GUI App Detection Tests
# ============================================================================

echo "Testing GUI app detection in terminal_dispatcher.sh"
echo "===================================================="
echo

# Test 1: Direct 3DE command should be detected as GUI
test_start "Direct 3DE command is GUI app"
if is_gui_app "3de -open /path/to/file.3de"; then
    test_pass
else
    test_fail "Expected 3de command to be detected as GUI app"
fi

# Test 2: Direct nuke command should be detected as GUI
test_start "Direct nuke command is GUI app"
if is_gui_app "nuke /path/to/script.nk"; then
    test_pass
else
    test_fail "Expected nuke command to be detected as GUI app"
fi

# Test 3: Direct maya command should be detected as GUI
test_start "Direct maya command is GUI app"
if is_gui_app "maya -file /path/to/scene.ma"; then
    test_pass
else
    test_fail "Expected maya command to be detected as GUI app"
fi

# Test 4: Rez wrapper with 3DE should be detected as GUI (extracts inner command)
test_start "Rez wrapper with 3DE is GUI app"
if is_gui_app 'rez env 3de -- bash -ilc "ws /shows/jack_ryan/shots/TB_090/TB_090_0020 && 3de -open /shows/jack_ryan/shots/TB_090/TB_090_0020/user/gabriel-h/mm/3de/mm-default/scenes/scene/FG01/TB_090_0020_mm_default_FG01_scene_v002.3de"'; then
    test_pass
else
    test_fail "Expected rez wrapper with 3de to be detected as GUI app"
fi

# Test 5: Rez wrapper with nuke should be detected as GUI
test_start "Rez wrapper with nuke is GUI app"
if is_gui_app 'rez env nuke -- bash -ilc "ws /path && nuke /path/script.nk"'; then
    test_pass
else
    test_fail "Expected rez wrapper with nuke to be detected as GUI app"
fi

# Test 6: Rez wrapper with maya should be detected as GUI
test_start "Rez wrapper with maya is GUI app"
if is_gui_app 'rez env maya -- bash -ilc "ws /path && maya -file /path/scene.ma"'; then
    test_pass
else
    test_fail "Expected rez wrapper with maya to be detected as GUI app"
fi

# Test 7: Plain echo command should NOT be GUI
test_start "Echo command is NOT GUI app"
if ! is_gui_app "echo test"; then
    test_pass
else
    test_fail "Expected echo command to NOT be GUI app"
fi

# Test 8: ls command should NOT be GUI
test_start "ls command is NOT GUI app"
if ! is_gui_app "ls -la /path"; then
    test_pass
else
    test_fail "Expected ls command to NOT be GUI app"
fi

# Test 9: ws workspace command should NOT be GUI
test_start "ws command is NOT GUI app"
if ! is_gui_app "ws /shows/jack_ryan/shots/TB_090/TB_090_0020"; then
    test_pass
else
    test_fail "Expected ws command to NOT be GUI app"
fi

# Test 10: Rez env alone (no GUI app after &&) should NOT be GUI
test_start "Rez env without GUI app is NOT GUI app"
if ! is_gui_app 'rez env python -- bash -ilc "python --version"'; then
    test_pass
else
    test_fail "Expected rez env python to NOT be GUI app"
fi

# Test 11: RV command should be detected as GUI
test_start "RV command is GUI app"
if is_gui_app "rv /path/to/sequence.####.exr"; then
    test_pass
else
    test_fail "Expected rv command to be detected as GUI app"
fi

# Test 12: Houdini command should be detected as GUI
test_start "Houdini command is GUI app"
if is_gui_app "houdini /path/to/scene.hip"; then
    test_pass
else
    test_fail "Expected houdini command to be detected as GUI app"
fi

# Test 13: Complex rez wrapper with multiple commands, last being GUI
test_start "Complex rez wrapper with GUI at end"
if is_gui_app 'rez env 3de -- bash -ilc "export FOO=bar && ws /path && 3de -open /file.3de"'; then
    test_pass
else
    test_fail "Expected complex rez command with 3de at end to be GUI app"
fi

# Test 14: Rez wrapper with only env setup (no GUI) should NOT be GUI
test_start "Rez wrapper with only environment setup is NOT GUI"
if ! is_gui_app 'rez env mypackage -- bash -ilc "ws /path"'; then
    test_pass
else
    test_fail "Expected rez with only ws command to NOT be GUI app"
fi

# ============================================================================
# Summary
# ============================================================================

echo
echo "===================================================="
echo "Test Summary:"
echo "  Total:  $TESTS_RUN"
echo -e "  ${GREEN}Passed: $TESTS_PASSED${NC}"
if [ $TESTS_FAILED -gt 0 ]; then
    echo -e "  ${RED}Failed: $TESTS_FAILED${NC}"
else
    echo "  Failed: 0"
fi
echo "===================================================="

if [ $TESTS_FAILED -gt 0 ]; then
    exit 1
else
    exit 0
fi
