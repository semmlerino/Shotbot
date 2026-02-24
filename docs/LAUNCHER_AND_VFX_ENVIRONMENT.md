# Launcher System & VFX Environment

## CommandLauncher

**CommandLauncher is the production launcher system** for application launching with shot context.

**File**: `command_launcher.py`

**Features**:
- Application launching with shot context
- Rez environment integration
- LaunchContext API for flexible launch options
- Scene-based launching support
- Spawns new terminal windows for each command

**Usage**:
```python
from command_launcher import CommandLauncher, LaunchContext

# Initialize
launcher = CommandLauncher(parent=self)

# Launch with context
context = LaunchContext(
    include_raw_plate=True,
    open_latest_threede=False,
    create_new_file=True
)
launcher.launch_app("nuke", context)
```

**Production Stack**:
- **CommandLauncher**: Application launching with shot context
- **ProcessPoolManager**: Process pool for workspace command caching

## VFX Environment Architecture

This section documents how the BlueBolt VFX environment works, which is critical for understanding the launcher system.

### Shell Initialization Chain

When a user logs in or opens a terminal, the following chain executes:

```
~/.bashrc
  → /etc/bashrc
    → bashrc.env
      → setbbplatform ${BLUEBOLT_PLATFORM}  ← REZ INITIALIZED HERE
        → Sets REZ_USED, loads rez packages, configures app paths
```

**Key insight**: Rez is initialized at shell startup, NOT by the `ws` command.

### The `ws` Command

`ws` is an alias to the `workspace` shell function that:
1. Generates a temporary workspace file via `$WRAPPERS/write_workspace_file`
2. Sources the generated file (sets SHOW, SEQUENCE, SHOT, WORKSPACE_PATH)
3. Sources hierarchical `env.sh` files for show/sequence/shot config
4. Does **NOT** handle Rez - Rez is already available from shell init

**Example**:
```bash
ws /shows/myshow/shots/sq010/sh0010
# Sets: SHOW=myshow, SEQUENCE=sq010, SHOT=sh0010, WORKSPACE_PATH=/shows/...
```

### Why `bash -ilc` is Required

Shell commands in the launcher use `bash -ilc` (interactive login shell) because:
- The `ws` function is defined in `.bashrc` (interactive shell config)
- Without `-i`, bash won't source `.bashrc` and `ws` won't be available
- The `-l` flag ensures login shell profile is also loaded
- The ~50ms startup overhead is acceptable for reliability

### Key Environment Variables

| Variable | Set By | Purpose |
|----------|--------|---------|
| `REZ_USED` | setbbplatform | Indicates Rez environment is active |
| `SHOW` | ws command | Current show name |
| `SEQUENCE` | ws command | Current sequence |
| `SHOT` | ws command | Current shot |
| `WORKSPACE_PATH` | ws command | Full workspace path |
| `SHOWS_ROOT` | bashrc.env | Root path for all shows (default: `/shows`) |

### REZ_MODE Configuration

In `config.py`, the `REZ_MODE` setting (a `RezMode` enum) controls Rez wrapping behavior:

```python
class RezMode(Enum):
    DISABLED = auto()  # Never wrap with rez
    AUTO = auto()      # Skip if REZ_USED is set (BlueBolt default)
    FORCE = auto()     # Always wrap with app-specific packages
```

- **`RezMode.AUTO` (default)**: Skip outer Rez wrapping if `REZ_USED` env var is set because:
  - Shell initialization already set up Rez before `ws` runs
  - `REZ_USED` environment variable indicates Rez is active
  - Double-wrapping would cause package conflicts

- **`RezMode.DISABLED`**: Never wrap with Rez (for non-Rez environments)

- **`RezMode.FORCE`**: Always wrap with app-specific Rez packages

`AUTO` is correct for BlueBolt's environment. Other VFX facilities may need `DISABLED` or `FORCE` depending on their shell initialization.

### Debugging VFX Environment Issues

```bash
# Check if Rez is initialized
echo $REZ_USED  # Should show "1" if rez is active

# Check ws function availability
type ws  # Should show "ws is aliased to `workspace'"

# Debug ws command
DEBUG=1 ws /shows/myshow/shots/sq010/sh0010

# Trace shell init
bash -xl -c "echo done" 2>&1 | head -100
```
