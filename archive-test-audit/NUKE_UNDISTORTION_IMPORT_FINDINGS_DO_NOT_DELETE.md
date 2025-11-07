# Nuke Undistortion Import Findings

## Date: 2025-08-20

## Problem Statement
When "include undistortion node" is checked in the ShotBot application, the undistortion nodes are not being imported into the generated Nuke script. Instead, only a StickyNote with the file path appears.

## Root Cause Analysis

### Initial Issue
The original `_import_undistortion_nodes()` function was failing to parse undistortion .nk files properly, resulting in an empty string return and fallback to creating only a StickyNote reference.

### Key Discovery
Through research into Nuke's file formats and TCL scripting, I discovered that Nuke .nk files can exist in two distinct formats:

1. **Standalone Script Format**
   - Complete .nk files with Root node
   - Full script structure
   - Used for complete Nuke projects

2. **Copy/Paste Format** 
   - Node snippets that start with `set cut_paste_input [stack 0]`
   - Used when copying/pasting nodes between scripts
   - Contains TCL stack operations for node connections
   - **This is the format used by undistortion export files**

### Why the Parser Was Failing

The original parser was designed for standalone scripts and had several limitations:

1. **Didn't recognize copy/paste format markers**
   - Missed `set cut_paste_input [stack 0]` 
   - Didn't handle `push $cut_paste_input` references
   - Didn't understand TCL stack operations

2. **Limited node type recognition**
   - Only looked for specific predefined node types
   - Rigid pattern matching requiring exact formatting
   - Missed many common Nuke node types

3. **Poor error handling**
   - Generic exception handling masked real issues
   - No differentiation between format types
   - Insufficient logging for debugging

## Research Findings

### Nuke TCL Scripting System

Nuke uses TCL (Tool Command Language) as its scripting foundation. Key concepts:

1. **Stack-Based Node Connections**
   - Nodes are connected via a stack system
   - Order in the file determines connections
   - `push` and `pop` operations manage the stack

2. **Copy/Paste Format Structure**
   ```tcl
   set cut_paste_input [stack 0]
   version 16.0 v4
   push $cut_paste_input
   NodeName {
     inputs 1
     name NodeName1
     xpos 0
     ypos -200
   }
   ```

3. **TCL Commands in Copy/Paste Format**
   - `set cut_paste_input [stack 0]` - Initializes input stack reference
   - `push $cut_paste_input` - References the input connection point
   - `push 0` - Pushes disconnected input
   - `version X.X vX` - Specifies Nuke version

### Proper Node Import Methods in Nuke

Research revealed three main approaches for importing nodes:

1. **Inside Nuke (Python API)**
   ```python
   nuke.nodePaste("/path/to/nodes.nk")
   ```

2. **Inside Nuke (TCL)**
   ```tcl
   source "/path/to/nodes.nk"
   ```

3. **External Script Generation** (our use case)
   - Must parse and convert copy/paste format to embedded nodes
   - Cannot use Nuke API as we're generating scripts outside Nuke

## Solution Implemented

### New Copy/Paste Format Parser

Created `_import_undistortion_nodes_copy_paste_format()` function that:

1. **Detects Format Type**
   - Checks for `set cut_paste_input` in first 10 lines
   - Falls back to standard parser if not copy/paste format

2. **Handles TCL Stack Operations**
   - Strips out copy/paste specific commands
   - Removes `push $cut_paste_input` and `push 0`
   - Preserves actual node definitions

3. **Processes Nodes Correctly**
   - Uses flexible regex pattern matching
   - Handles any node type (not just predefined list)
   - Adjusts ypos values for proper positioning
   - Ensures first node connects to plate input

4. **Enhanced Error Handling**
   - Specific handling for different error types
   - Detailed logging at each step
   - Clear success/failure reporting

### Implementation Details

#### Format Detection
```python
is_copy_paste_format = False
for line in lines[:10]:
    if "set cut_paste_input" in line:
        is_copy_paste_format = True
        break
```

#### Node Pattern Matching
```python
node_match = re.match(r'^([A-Za-z][A-Za-z0-9_]*)\s*\{', stripped)
if node_match:
    node_type = node_match.group(1)
    # Process node...
```

#### Connection Handling
```python
# For first node, ensure proper connection
if nodes_found == 1 and "inputs 0" not in node_text:
    node_text = re.sub(r'inputs\s+\d+', 'inputs 1', node_text, count=1)
```

## Testing Recommendations

### Debug Function Added
Created `debug_undistortion_file()` to analyze .nk file structure:

```python
from nuke_script_generator import NukeScriptGenerator
NukeScriptGenerator.debug_undistortion_file("/path/to/undistortion.nk")
```

This will report:
- File format (standalone vs copy/paste)
- Line counts and types
- Found node types
- Unrecognized patterns
- Import test results

### What to Look For in Logs

With enhanced logging, successful import shows:
```
INFO - Attempting to import undistortion nodes from: /path/to/file.nk
INFO - Detected copy/paste format undistortion file
DEBUG - Found LensDistortion node at line 5
DEBUG - Found Group node at line 25
INFO - Successfully imported 2 nodes from copy/paste format
INFO - Successfully imported undistortion nodes into script
```

Failed import shows:
```
WARNING - Failed to import undistortion nodes from /path/to/file.nk, creating reference note instead
```

## Future Improvements

### Potential Enhancements

1. **Alternative Import Method**
   - Could generate TCL `source` command in the script
   - Would require Nuke to have access to undistortion file path

2. **Node Library System**
   - Cache parsed undistortion nodes
   - Reuse for similar shots
   - Version management

3. **Validation System**
   - Verify imported nodes are complete
   - Check for missing connections
   - Validate required node types present

## Summary

The undistortion import was failing because the files use Nuke's copy/paste format with TCL stack operations, not the standalone script format our parser expected. The solution involves:

1. Detecting the copy/paste format
2. Stripping TCL-specific commands
3. Extracting and converting node definitions
4. Properly handling node connections

This fix should enable proper import of undistortion nodes from 3DE exports and other sources that use the copy/paste format.

---
End of Initial Findings