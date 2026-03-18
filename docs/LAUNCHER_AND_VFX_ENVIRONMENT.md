# Launcher System & VFX Environment

This document defines launcher behavior assumptions for the BlueBolt environment.

## Launcher Role

`CommandLauncher` is the production entrypoint for DCC launches with shot context.
It coordinates workspace setup, environment handling, and app dispatch.
Internally, it delegates to the `launch/` subpackage: `CommandBuilder`, `EnvironmentManager`, `ProcessExecutor`, and `FileSearchCoordinator`.

Supported DCCs: `3de`, `maya`, `nuke`, `rv`.

## Environment Assumptions

1. `ws` sets workspace context (show/sequence/shot), not Rez initialization.
2. DCC launches resolve explicit Rez packages for the target app unless `REZ_MODE` is `DISABLED`.
3. Launcher shell commands use `bash -ilc` for the outer shell so `ws` is available before the Rez command runs.

## Shell Flow

High-level launch sequence:

`bash -ilc "ws <show>/<seq>/<shot> && rez env <packages> -- bash -lc '<app command>'"`

Why this matters:

- `-i` loads `.bashrc` where `workspace/ws` is defined
- `-l` preserves login-shell initialization behavior
- `ws` runs in the studio shell before Rez resolves the DCC context
- the inner Rez command only executes the app payload; it does not re-enter an interactive login shell

The launcher no longer treats `REZ_USED` as sufficient for DCC launches. A base Rez shell is not assumed to contain the correct Maya/Nuke/RV packages.

## Rez Mode

`REZ_MODE` in `config.py` controls wrapping strategy:

- `AUTO` (default): resolve the configured app packages for each DCC launch
- `DISABLED`: never wrap with Rez
- `FORCE`: always wrap with app-specific Rez packages

For BlueBolt, `AUTO` is the intended mode.

## SGTK Integration Contract

Shotbot guarantees shell/workspace setup and, when enabled, explicit Rez package
resolution for the target DCC. Shotbot does **not** currently perform a full
Toolkit bootstrap itself via `sgtk.bootstrap.ToolkitManager`,
`sgtk.platform.start_engine()`, `tk-multi-launchapp`, or
`sgtk.platform.SoftwareLauncher.prepare_launch()`.

Operationally, that means:

- Rez packages, site wrappers, or DCC startup scripts must be responsible for
  starting the initial SGTK engine.
- If no engine starts inside the launched DCC, Shotbot's post-launch SGTK hooks
  are no-ops.
- `SGTK_FILE_TO_OPEN` is a launcher contract for file-based DCC launches
  (`nuke`, `maya`, `3de`). Site startup code and Shotbot helper scripts may use
  it to derive Toolkit context from the target workfile path.
- `Config.SCRIPTS_DIR` is injected into `NUKE_PATH` and
  `PYTHON_CUSTOM_SCRIPTS_3DE4` for Shotbot-managed startup hooks. In deployment,
  this path must exist, or `SHOTBOT_SCRIPTS_DIR` must be set explicitly.
- Maya additionally uses `SHOTBOT_MAYA_SCRIPT` to run a deferred bootstrap that
  waits for an existing engine and then derives context from the opened scene.

## Launch Entry Point Semantics

The launcher exposes multiple public entrypoints with different guarantees:

- `launch_app(...)`: shot-context launch. Maya/3DE may resolve the latest scene
  first, then launch inside the shot workspace.
- `launch_with_file(...)`: explicit DCC-native file launch. This is the main
  path that exports file-oriented SGTK variables and startup-hook paths.
- `launch_app_opening_scene_file(...)`: open the concrete file referenced by the
  provided scene object. Only use this when the target DCC can consume that
  file path directly.

## Best-Practice Guidance

- Prefer deterministic Toolkit startup via `SoftwareLauncher.prepare_launch()`
  or a documented site bootstrap layer when that is available.
- Prefer `sgtk.platform.change_context(...)` for engine-aware context switches.
  Direct `engine.change_context(...)` should be treated as engine-specific and
  validated in the target DCC.
- Treat shell-exported variables such as `SGTK_FILE_TO_OPEN` as a compatibility
  layer, not as a substitute for a documented bootstrap contract.

## Launch Verification

`Config.LAUNCH_VERIFICATION_ENABLED` (default `True`) enables async verification that GUI app launches succeed. Controlled by `LAUNCH_VERIFICATION_TIMEOUT_SEC` (60s) and `LAUNCH_VERIFICATION_POLL_SEC` (0.5s).

## Debugging Checklist

```bash
# rez state
echo "$REZ_USED"
rez context

# workspace command availability
type ws

# inspect workspace env after ws
ws <show>/<seq>/<shot> && env | grep -E '^(SHOW|SEQUENCE|SHOT|WORKSPACE|REZ_)'

# verify Shotbot startup-hook location
echo "$SHOTBOT_SCRIPTS_DIR"

# inspect file-launch integration variables inside the launch shell
ws <show>/<seq>/<shot> && rez env <packages> -- env | grep -E '^(SGTK_|SHOTGUN_|NUKE_PATH|PYTHON_CUSTOM_SCRIPTS_3DE4|REZ_)'
```

## Integration Notes

- `ProcessPoolManager` supports launcher workflows by handling subprocess-heavy paths.
- Maya/SGTK context handling behavior is launcher-specific and should be validated in integration tests after refactors.
- Nuke/3DE file-launch hooks depend on `Config.SCRIPTS_DIR` being valid in the deployed environment.
- Context-only launches from 3DE scene selections must not pass a `.3de` path into non-3DE applications.
