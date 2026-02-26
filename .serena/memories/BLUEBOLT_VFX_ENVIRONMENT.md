# BlueBolt VFX Environment Reference

> See `CLAUDE.md` for essential overview and `docs/LAUNCHER_AND_VFX_ENVIRONMENT.md` for launcher details.
> This memory captures verified VFX pipeline behavior for AI context loading.
> Last Updated: February 2026

## Shell Initialization Chain

```
~/.bashrc → /etc/bashrc → /etc/profile.d/*.sh
  → /software/bluebolt/vfxplatform/startup/current/bashrc.env
    → /shows/bluebolt/config/env.sh
    → $SHOW_CONFIG_PATH/{show_config,tools_config,bluebolt_platform}.sh
      → setbbplatform → REZ SETUP (sets REZ_USED, app paths)
```

**Key insight**: Rez is initialized at shell startup, NOT by the `ws` command. By the time `ws` runs, `REZ_USED` is already set.

## The `ws` Command

`ws` (alias for `workspace`) generates a temp workspace file, sources it into the current shell, and adds wrappers to PATH.

**What it sets**: `SHOW`, `SHOW_PATH`, `SEQUENCE`, `SEQUENCE_PATH`, `SHOT`, `SHOT_PATH`, `WORKSPACE`, `WORKSPACE_PATH`, `WORKSPACE_TYPE`, `WORKSPACE_ORDER`, `PWD`

**What it does NOT do**: Call `rez env`, resolve Rez packages, or set `REZ_USED`.

## Launcher Command Flow

`bash -ilc "ws show seq shot && app"`:
1. `-il` loads bashrc → Rez initialized, `workspace` function defined
2. `ws` sets workspace env vars, sources show/seq/shot configs, CDs to workspace
3. `&& app` runs with Rez + workspace env inherited

**Why `-ilc`**: `-i` loads `.bashrc` (defines `workspace` function), `-l` ensures full init chain.

## Rez Mode (config.py)

- `AUTO` (default): Skip outer Rez wrapping if `REZ_USED` already set
- `DISABLED`: Never wrap with Rez
- `FORCE`: Always wrap with app-specific Rez packages

## SGTK (ShotGrid Toolkit) Integration

### Context Levels → App Loading

| Context | Apps Loaded |
|---------|-------------|
| Shot only (no Task/Step) | Basic: workfiles2, shotgunpanel |
| Shot + Task + Step | Full: publish2, loader2, snapshot, breakdown2, etc. |

### The Command-Line Launch Problem

Launching Maya via `maya -file /path` bootstraps SGTK with Shot context only → only basic apps load.

### Shotbot's Solution (command_launcher.py)

For Maya file launches, Shotbot:
1. Sets `SGTK_FILE_TO_OPEN={file_path}` env var
2. Adds a deferred Maya command that after file loads runs:
   `sgtk.context_from_path(file_path)` → `engine.change_context(new_context)`
3. This triggers full app registration with Task/Step context

### Key SGTK Environment Variables

Set by BlueBolt environment: `SHOTGUN_ENTITY_TYPE=Shot`, `SHOTGUN_ENTITY_ID`, `SHOTGUN_PIPELINE_CONFIGURATION_ID`, `SHOTGUN_HOME=/disk1/tmp/<user>/.shotgun`

Set by Shotbot: `SGTK_FILE_TO_OPEN=/path/to/file.ma`

### Common Issues

- **Only basic SG menu items**: Context has no Task/Step → solved by deferred context update
- **File dialog on startup**: `launch_at_startup: True` in tk-multi-workfiles2 → server-side config (outside Shotbot scope)
- **3DEqualizer**: Does not use SGTK, these issues don't apply

## Debugging

```bash
# See workspace file contents
DEBUG=1 KEEP_TEMP_WORKSPACE_FILES=1 ws <show> <seq> <shot>

# Check Rez state
echo $REZ_USED && rez context

# Check env after ws
ws <show> <seq> <shot> && env | grep -E '^(SHOW|SEQUENCE|SHOT|WORKSPACE|REZ_)'
```
