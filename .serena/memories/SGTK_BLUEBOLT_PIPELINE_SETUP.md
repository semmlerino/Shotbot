# BlueBolt SGTK/ShotGrid Pipeline Setup

## Overview

BlueBolt uses ShotGrid Toolkit (SGTK) for pipeline integration in Maya, Nuke, and other DCCs. Understanding this setup is critical for Shotbot's file launching functionality.

## Key Discovery: Context Levels Determine App Loading

SGTK loads different apps based on context level:

| Context Level | Apps Loaded |
|---------------|-------------|
| Shot only (no Task/Step) | Basic: workfiles2, shotgunpanel, screeningroom, about |
| Shot + Task + Step | Full suite: publish2, loader2, snapshot, breakdown2, validation, etc. |

**This is why opening via command line initially showed fewer apps than using SG File Open.**

## Environment Variables

### Set by BlueBolt Environment
```bash
SHOTGUN_API_VERSION=3.0.40
SHOTGUN_UTILS_VERSION=2.4.1
SHOTGUN_DESKTOP_VERSION=1.5.3
SHOTGUN_HOME=/disk1/tmp/gabriel-h/.shotgun
SHOTGUN_PIPELINE_CONFIGURATION_ID=8046
SHOTGUN_ENTITY_TYPE=Shot
SHOTGUN_ENTITY_ID=<shot_id>
```

### Set by Shotbot (for file launches)
```bash
SGTK_FILE_TO_OPEN=/path/to/file.ma  # Tells SGTK which file is being opened
```

### Workspace Variables (set by `ws` command)
```bash
SHOW=jack_ryan
SEQUENCE=GG_134
SHOT=GG_134_1020
WORKSPACE_PATH=/shows/jack_ryan/shots/GG_134/GG_134_1020
```

## SGTK Configuration Paths

```
Pipeline Config: /disk1/tmp/gabriel-h/.shotgun/bluebolt/p<project_id>c<config_id>.basic.maya/cfg
Bundle Cache: /disk1/tmp/gabriel-h/.shotgun/bundle_cache/
SGTK Core: <config_path>/install/core/python/tank/
```

## Key SGTK Settings

### tk-multi-workfiles2
- **Version**: v0.15.5.2 (BlueBolt custom from git)
- **Location**: bundle_cache/git/tk-multi-workfiles2.git/
- **`launch_at_startup`: True** - This causes the file dialog to appear on startup
- To suppress: Would need server-side config change to `launch_at_startup: false`

## Maya Launch with Full SGTK Context

### The Problem
When launching Maya via command line with `-file`, SGTK bootstraps with Shot context only (no Task/Step), resulting in only basic apps loading.

### The Solution
Shotbot adds a deferred MEL command that:
1. Waits for file to fully load
2. Gets full context (including Task/Step) from file path using `sgtk.context_from_path()`
3. Calls `engine.change_context()` to trigger full app registration

### Implementation (command_launcher.py)
```python
# For Maya file launches:
context_script = (
    "import sgtk; "
    "e=sgtk.platform.current_engine(); "
    "p=__import__('maya.cmds',fromlist=['']).file(q=1,sn=1); "
    "c=e.sgtk.context_from_path(p) if p else None; "
    "e.change_context(c) if c and c.task and not e.context.task else None"
)
deferred_cmd = f'python("import maya.cmds; maya.cmds.evalDeferred(\\"{context_script}\\")")'
command = f'{command} -file {safe_file_path} -c "{deferred_cmd}"'
```

## BlueBolt Rez Packages (SGTK-related)

```
/software/bluebolt/rez/packages/bluebolt/maya_tools/4.0.2/
/software/bluebolt/rez/packages/bluebolt/nuke_tools/4.0.3/
/software/bluebolt/rez/packages/bluebolt/sgtk_utils/2.0.2/
/software/bluebolt/rez/packages/bluebolt/sg_launch/2.0.1/
/software/bluebolt/rez/packages/bluebolt/shotgun_utils/3.1.2/
/software/bluebolt/rez/packages/bluebolt/bb_shotgrid_api/1.0.0/
/software/bluebolt/rez/packages/thirdparty/shotgun_api3/3.5.1/
```

## Maya Startup Scripts (userSetup.py locations)

```
/software/bluebolt/rez/packages/bluebolt/maya_tools/4.0.2/python-3.11/scripts/userSetup.py
/software/bluebolt/rez/packages/bluebolt/maya_tools/4.0.2/python-3.11/modules/shotgun/scripts/userSetup.py
```

## Diagnostic Scripts

Located in `scripts/` directory:
- `find_sgtk_config.py` - Find SGTK config locations (run from terminal)
- `find_sgtk_maya.py` - Detailed SGTK info (run inside Maya)
- `check_sgtk_apps.py` - List registered apps/commands (run inside Maya)
- `sgtk_context_from_file.py` - Manually trigger context update (run inside Maya)

## SGTK App Registration Flow

```
Maya starts
    ↓
SGTK engine bootstraps (tk-maya)
    ↓
Context determined from SHOTGUN_ENTITY_* env vars
    ↓
Apps loaded based on context level (Shot only = basic apps)
    ↓
File opens via -file flag
    ↓
[Without fix] User must use SG File Open to get full apps
    ↓
[With fix] Deferred command gets context from file path
    ↓
engine.change_context() triggers full app registration
    ↓
Full "Flow Production Tracking" menu available
```

## Common Issues

### Issue: Only basic SG menu items appear
**Cause**: Context has no Task/Step
**Solution**: Shotbot's deferred command updates context from file path

### Issue: File dialog appears on startup
**Cause**: `launch_at_startup: True` in tk-multi-workfiles2 config
**Solution**: Server-side config change (outside Shotbot scope)

### Issue: SGTK_FILE_TO_OPEN not working
**Cause**: Variable is informational, doesn't suppress dialogs or trigger context
**Solution**: Use context_from_path() + change_context() instead

## Future Considerations

### Nuke
May need similar deferred context update if same issue occurs.

### 3DEqualizer
Does not use SGTK, so these issues don't apply.

## References

- [SGTK Environment Variables](https://developers.shotgridsoftware.com/tk-core/environment_variables.html)
- [tk-multi-workfiles2 Documentation](https://github.com/shotgunsoftware/tk-multi-workfiles2/wiki/Documentation)
- [SGTK Context API](https://developers.shotgridsoftware.com/tk-core/core.html#context)
