# Launcher System & VFX Environment

This document defines launcher behavior assumptions for the BlueBolt environment.

## Launcher Role

`CommandLauncher` is the production entrypoint for application launches with shot context.
It coordinates workspace setup, environment handling, and app dispatch.
Internally, it delegates to the `launch/` subpackage: `command_builder` module (functions), `EnvironmentManager`, `ProcessExecutor`, `FileSearchCoordinator`, and `LaunchOperation`.

Supported launch targets: `3de`, `maya`, `nuke`, `rv`, `publish`.
The file-open and Toolkit-specific sections below focus on the DCC-heavy paths;
`publish` uses the same workspace/Rez launch pipeline but does not add extra
scene/workfile startup hooks.

## Environment Assumptions

1. `ws` sets workspace context (show/sequence/shot), not Rez initialization.
2. DCC launches resolve explicit Rez packages for the target app unless `REZ_MODE` is `DISABLED`.
3. Launcher shell commands use `bash -ilc` for the outer shell so `ws` is available before the Rez command runs.
4. A facility command on `PATH` may be a site wrapper rather than the raw DCC binary. Treat wrapper behavior as part of the production contract.

## Shell Flow

High-level launch sequence:

`bash -ilc "ws <show>/<seq>/<shot> && rez env <packages> -- bash -lc '<app command>'"`

Why this matters:

- `-i` loads `.bashrc` where `workspace/ws` is defined
- `-l` preserves login-shell initialization behavior
- `ws` runs in the studio shell before Rez resolves the DCC context
- the inner Rez command only executes the app payload; it does not re-enter an interactive login shell

The launcher no longer treats `REZ_USED` as sufficient for DCC launches. A base Rez shell is not assumed to contain the correct Maya/Nuke/RV packages.

## Site Wrapper Resolution

Some facility commands exposed on `PATH` are wrappers, not raw DCC binaries.
This matters because the wrapper may perform its own environment resolution,
version selection, startup-hook injection, and Toolkit bootstrap steps.

## BlueBolt 3DE Triage (March 2026)

The following sections document concrete evidence from BlueBolt production environment
diagnostics on March 19, 2026. This material is investigation-specific and separates
general launcher behavior (above) from real-world site wrapper findings (below).

### Site Wrapper Resolution Example

Observed on the BlueBolt remote 3DE path on March 19, 2026:

`3de` -> versioned wrapper -> `launch 3de --add 3de_tools -- 3DE4 "$@"`

`launch` -> `launch_production` -> `${REZ_ROOT}/python3 -E ${LAUNCH_MODULE}`

`launch.py` then resolves the final environment from `.rezenv` files and
show/package/user overrides, not just from the caller's current Rez shell.

Practical implications:

- Do not assume `type 3de` or `type maya` points at a bare binary.
- Do not assume `rez env <package>` matches the environment the site wrapper
  will actually launch.
- If a DCC fails the same way under `ws <shot> && <dcc> ...` outside Shotbot,
  treat it as a site wrapper / package issue first.
- For DCCs launched through facility wrappers, compare the wrapper launch path
  and the direct Rez resolve before changing Shotbot.

### Observed 3DE Mismatch (March 19, 2026)

During remote triage on BlueBolt:

- `rez env 3de` resolved `3de-4.8.0` with `python-3.9.18`
- `ws <shot> && 3de -open <scene.3de>` launched `3DEqualizer4 Release 7.1`
  from `3de/4.7.1/python-3.7`
- `ws <shot> && launch 3de -- env` resolved `3de-4.7.1` with `python-3.7.10`
  and `bb_startup`, with no Toolkit layer yet
- `ws <shot> && launch 3de --add 3de_tools -- env` added `3de_tools`,
  `sg_launch`, `tk_core`, `sgtk`, `toolkitini`, and other ShotGrid-related
  packages on top of the same `3de-4.7.1/python-3.7` base
- both `launch 3de -- 3DE4` and `launch 3de --add 3de_tools -- 3DE4` emitted
  the same embedded-Python `<prefix>` / `<exec_prefix>` startup warnings
- despite those warnings, later in-DCC inspection showed a live
  `tk-3dequalizer` engine and a partial Toolkit menu in the running 3DE session

This is concrete evidence that direct Rez inspection and the facility wrapper
are not equivalent, and that the base facility 3DE runtime can already be
in an unexpected state before Toolkit integration is added. Use this as a
diagnostic pattern for other DCCs as well.

## Rez Mode

`REZ_MODE` in `config.py` controls wrapping strategy:

- `AUTO` (default): resolve the configured app packages for each DCC launch
- `DISABLED`: never wrap with Rez
- `FORCE`: always wrap with app-specific Rez packages

For BlueBolt, `AUTO` is the intended mode.

For facility commands that already go through a site launcher, validate that
explicit Shotbot Rez wrapping does not diverge from the site wrapper's own
resolve logic. This is especially relevant for `3de`, where the facility
wrapper may add extra packages such as `3de_tools` and may select a different
version than a direct `rez env 3de` call.

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
- On BlueBolt, the 3DE wrapper currently ensures ShotGrid Desktop is running
  before calling the site `launch` stack. That happens outside Shotbot.
- Site packages may overwrite, not append, startup-hook environment variables.
  On BlueBolt, `3de_tools-1.4.0` assigns `PYTHON_CUSTOM_SCRIPTS_3DE4` directly
  to the site package path, which can mask Shotbot's own exported 3DE scripts
  path unless the final resolved environment appends both.

### Partial Toolkit Context Inside the DCC

A DCC can launch with a live Toolkit engine but still be in a partial context.
In that state, only a subset of commands may be registered initially. A later
Toolkit command can force a `change_context(...)` call and load the rest of the
 app menu.

Observed on BlueBolt in 3DE on March 19, 2026:

- engine before manual intervention: `tk-3dequalizer`
- context before manual intervention: `Shot BOB_205_017_430`
- visible commands before manual intervention: `File Open...`, `File Save...`,
  `Flow Production Tracking Panel...`, logging/debug commands
- after running the SG `File Save...` command, context changed to
  `mm-default BOB_205_017_430, Shot BOB_205_017_430`
- additional commands then appeared, including `Publish...`,
  `Work Area Info...`, and `Export...`

Implication:

- if "most of the environment" appears only after a Toolkit menu command is
  used, suspect a delayed context change rather than a missing engine bootstrap
- the launcher may have reached a valid engine, but not the final task/work-area
  context expected by the artist
- startup warnings printed by the site wrapper are not sufficient to conclude
  that the DCC failed to launch; confirm the actual in-DCC engine and context
  state before treating them as fatal

### Toolkit Command Introspection Inside the DCC

When a Toolkit command appears to "fix" the environment, inspect the command
from inside the running DCC before changing Shotbot.

Use this pattern inside the DCC's Python console:

```python
import inspect
import pprint
import sgtk

e = sgtk.platform.current_engine()
cmd = e.commands["File Save..."]
cb = cmd["callback"]

print("ENGINE:", e)
print("ENGINE NAME:", e.name if e else None)
print("CONTEXT:", e.context if e else None)
print("CALLBACK:", cb)
print("CALLBACK MODULE:", getattr(cb, "__module__", None))
print("CALLBACK FILE:", inspect.getsourcefile(cb) or inspect.getfile(cb))
print("APP:", cmd["properties"].get("app"))
print("APP DISK LOCATION:", getattr(cmd["properties"].get("app"), "disk_location", None))
pprint.pprint(sorted(e.commands.keys()))
```

Interpretation:

- `callback.__module__` may point at Toolkit core (for example
  `tank.platform.engine`) because the engine wraps callbacks in a generic
  `register_command(...)` wrapper
- the real owner is usually `commands[name]["properties"]["app"]`
- `app.disk_location` is the actual Toolkit app bundle to inspect next

Observed on BlueBolt in 3DE on March 19, 2026:

- callback module: `tank.platform.engine`
- callback file:
  `/disk1/tmp/gabriel-h/.shotgun/bluebolt/p4683c9266.basic.3dequalizer/cfg/install/core/python/tank/platform/engine.py`
- command owner app: `tk-multi-workfiles2`
- app disk location:
  `/disk1/tmp/gabriel-h/.shotgun/bundle_cache/git/tk-multi-workfiles2.git/v0.15.5.2`

### Delayed Context Promotion Call Chain

After identifying the owning app, inspect its action classes rather than
stopping at `app.py`.

Observed on BlueBolt in 3DE on March 19, 2026:

- `tk-multi-workfiles2/app.py` registers `File Save...` to
  `show_file_save_dlg()`
- `show_file_save_dlg()` dispatches into the app's Workfiles UI layer
- `python/tk_multi_workfiles/actions/save_as_file_action.py` checks whether
  `self.environment.context` differs from the current app context
- if the contexts differ, it calls
  `FileAction.change_context(self.environment.context)`
- `python/tk_multi_workfiles/actions/file_action.py` implements that method as
  `sgtk.platform.change_context(ctx)`
- after the context change, the save flow continues through
  `python/tk_multi_workfiles/scene_operation.py`, which calls the configured
  `hook_scene_operation` hook with operations such as `save_as` or `save`

Practical implication:

- if a DCC "loads the rest of the environment" only after `File Save...`,
  `File Open...`, or a similar Workfiles action, the likely missing step is
  automatic context promotion into the final work area, not engine startup
- for other DCCs, inspect the owning Toolkit app's `actions/` modules and
  `scene_operation.py` before changing Shotbot
- search for `sgtk.platform.change_context(...)`, `scene_operation`, and
  work-area selection logic first

### Toolkit App and Hook Resolution

After identifying the owning Toolkit app, inspect both the app bundle and the
site configuration.

Useful locations:

- Toolkit app bundle:
  `~/.shotgun/bundle_cache/.../<app>/`
- Toolkit config root:
  `~/.shotgun/<site>/<pipeline_config>/cfg/`
- site hooks usually live under:
  `cfg/config/hooks/`
- site environment yml usually lives under:
  `cfg/config/env/`

Observed on BlueBolt in 3DE on March 19, 2026:

- `tk-multi-workfiles2/app.py` registers `File Save...`
- `tk-multi-workfiles2/python/tk_multi_workfiles/actions/save_as_file_action.py`
  changes to `self.environment.context` before saving when needed
- `python/tk_multi_workfiles/actions/file_action.py` contains
  `sgtk.platform.change_context(ctx)`
- `python/tk_multi_workfiles/actions/save_as_file_action.py` and
  `python/tk_multi_workfiles/scene_operation.py` are part of the save flow
- `tk-multi-workfiles2/info.yml` defaults `hook_scene_operation` to
  `{self}/scene_operation_{engine_name}.py`
- grepping `cfg/config` for `scene_operation` / `change_context` produced no
  site override hits, so the default app code path was likely active

## Launch Entry Point Semantics

The launcher exposes a unified entry point:

- `launch(request: LaunchRequest) -> bool`: Dispatcher that routes to one of three
  internal paths based on which optional fields are set on `request`:
  - *scene* set → scene-file launch via `_launch_with_scene()`. Opens the concrete
    3DE scene file referenced by the scene object.
  - *file_path* set → explicit-file launch via `_launch_with_explicit_file()`.
    Opens a specific DCC-native file (for example, a Maya scene or Nuke script).
    This path exports file-oriented SGTK variables and startup-hook paths.
  - neither field set → standard app launch via `_launch_standard()`. Shot-context
    launch that may resolve the latest scene for 3DE/Maya before launching.

## Debugging Checklist

```bash
# Shotbot runtime logs
tail -n 200 ~/.shotbot/logs/shotbot.log
tail -n 200 ~/.shotbot/logs/dispatcher.out

# rez state
echo "$REZ_USED"
rez context

# workspace command availability
type ws

# identify whether a DCC command is a wrapper
type -a 3de launch shotgrid_desktop
command -v 3de
command -v launch
head -n 200 "$(command -v 3de)"
head -n 200 "$(command -v launch)"

# inspect workspace env after ws
ws <show>/<seq>/<shot> && env | grep -E '^(SHOW|SEQUENCE|SHOT|WORKSPACE|REZ_)'

# verify Shotbot startup-hook location
echo "$SHOTBOT_SCRIPTS_DIR"

# inspect file-launch integration variables inside the launch shell
ws <show>/<seq>/<shot> && rez env <packages> -- env | grep -E '^(SGTK_|SHOTGUN_|NUKE_PATH|PYTHON_CUSTOM_SCRIPTS_3DE4|REZ_)'

# compare site wrapper behavior with direct Rez resolution
ws <show>/<seq>/<shot> && <dcc> <args>
ws <show>/<seq>/<shot> && rez env <packages> -- bash -lc 'env | grep -E "^(PYTHON(HOME|PATH)?|SGTK_|SHOTGUN_|TK_|TANK_|REZ_)"'

# 3DE-specific: isolate site package additions
ws <show>/<seq>/<shot> && 3de -open <scene.3de>
ws <show>/<seq>/<shot> && launch 3de -- 3DE4
ws <show>/<seq>/<shot> && launch 3de --add 3de_tools -- 3DE4
ws <show>/<seq>/<shot> && launch 3de -- env | grep -E '^(PYTHON(HOME|PATH)?|PYTHON_CUSTOM_SCRIPTS_3DE4|TDE4_ROOT|REZ_)'
ws <show>/<seq>/<shot> && launch 3de --add 3de_tools -- env | grep -E '^(PYTHON(HOME|PATH)?|PYTHON_CUSTOM_SCRIPTS_3DE4|TDE4_ROOT|REZ_|SGTK_)'

# inspect launch overrides that can pin unexpected versions
grep -RInE '3de|3de_tools|maya|nuke|rv' \
  /software/bluebolt/rez/environments/show_overrides \
  /software/bluebolt/rez/environments/package_overrides

# inspect package commands for overwrite vs append behavior
sed -n '1,220p' /software/bluebolt/rez/packages/bluebolt/3de_tools/1.4.0/package.py
sed -n '1,220p' /software/bluebolt/rez/packages/thirdparty/3de/4.7.1/package.py

# inspect Toolkit command ownership inside the DCC
# run in the DCC Python console, not the shell
import inspect
import sgtk
e = sgtk.platform.current_engine()
cmd = e.commands["File Save..."]
cb = cmd["callback"]
print(getattr(cb, "__module__", None))
print(inspect.getsourcefile(cb) or inspect.getfile(cb))
print(getattr(cmd["properties"].get("app"), "disk_location", None))

# inspect the owning Toolkit app and likely context-change code
APP=~/.shotgun/bundle_cache/git/tk-multi-workfiles2.git/v0.15.5.2
CFG=~/.shotgun/<site>/<pipeline_config>/cfg
sed -n '1,260p' "$APP/app.py"
sed -n '1,240p' "$APP/python/tk_multi_workfiles/actions/save_as_file_action.py"
sed -n '1,240p' "$APP/python/tk_multi_workfiles/actions/file_action.py"
sed -n '1,240p' "$APP/python/tk_multi_workfiles/scene_operation.py"
grep -RIn 'scene_operation|change_context' "$APP" "$CFG/config"
```

Interpretation guidance:

- If `dispatcher.out` contains a facility wrapper banner (for example
  `PIPELINE 3DE WRAPPER`), Shotbot has successfully reached the site wrapper.
- If the same failure reproduces with `ws <shot> && <dcc> ...` outside Shotbot,
  the problem is downstream of Shotbot.
- If both the base facility launch (`launch <dcc> -- <binary>`) and the
  Toolkit-augmented launch fail the same way, the base DCC package/runtime is
  already suspect and the SG layer is not the primary cause.
- If the DCC still opens and exposes a live Toolkit engine, treat wrapper
  startup warnings and final in-DCC state as separate signals.
- If `launch_production` invokes `python3 -E`, inherited `PYTHONHOME` /
  `PYTHONPATH` are less likely to explain the wrapper startup itself. Focus on
  package overrides, startup hooks, and the environment produced by `launch.py`.
- If a site tools package overwrites a startup-hook variable instead of
  appending, compare the final wrapper-resolved value with the value Shotbot
  exported before launch.
- If a Toolkit command appears to "fix" the environment after launch, inspect
  `engine.commands[name]["properties"]["app"]` and look for
  `sgtk.platform.change_context(...)` in that app's code path.

## Integration Notes

- `ProcessExecutor` is the launcher's subprocess mechanism for executing DCC commands and managing process lifecycle.
- Maya/SGTK context handling behavior is launcher-specific and should be validated in integration tests after refactors.
- Nuke/3DE file-launch hooks depend on `Config.SCRIPTS_DIR` being valid in the deployed environment.
- Context-only launches from 3DE scene selections must not pass a `.3de` path into non-3DE applications.
- Shotbot already emits high-signal launcher diagnostics to
  `~/.shotbot/logs/shotbot.log` and the spawned shell output to
  `~/.shotbot/logs/dispatcher.out`; inspect those before adding new logging.
- Wrapper-resolved startup paths win over caller exports. For 3DE on BlueBolt,
  the site `3de_tools` package currently replaces `PYTHON_CUSTOM_SCRIPTS_3DE4`
  with its own path. Similar overwrite behavior is possible for other DCC hook
  variables (`NUKE_PATH`, `MAYA_SCRIPT_PATH`, etc.) depending on site packages.
- A Toolkit command may be registered by one app but wrapped by Toolkit core.
  Do not stop at `callback.__module__`; always inspect
  `commands[name]["properties"]["app"]` to find the real owner.

## Known Limitations

### SGTK Bootstrap Non-Determinism (F2)

Shotbot relies on Toolkit's auto-bootstrap behavior within the DCC session rather
than calling `sgtk.bootstrap.ToolkitManager.bootstrap_engine()` explicitly. This
means the SGTK engine may not be available when Shotbot's context-update code
first runs. The Maya bootstrap works around this with a background poller, but
the underlying issue is studio-pipeline-level: deterministic bootstrap requires
coordinating with the facility's Toolkit configuration and launch hooks.

### Facility Wrapper / Rez Divergence

Shotbot may explicitly Rez-wrap a DCC command while the facility command on
`PATH` is itself a wrapper that performs its own resolve. If those two paths
select different package versions or startup hooks, the actual launched DCC can
differ materially from `rez env <package>` inspection.

Observed example on BlueBolt on March 19, 2026:

- direct `rez env 3de` resolved `3de-4.8.0` / `python-3.9.18`
- the facility `3de` wrapper launched `3de/4.7.1/python-3.7`
- the site `launch 3de -- 3DE4` base path already emitted the same embedded-
  Python startup warnings seen under the Toolkit-augmented launch
- adding `3de_tools` introduced the Toolkit stack, but did not change the base
  warning pattern

When this happens, compare the site wrapper path, `launch.py` overrides, and
package startup scripts before changing Shotbot launcher code.

### Site Hook Path Overwrites

Shotbot may export a startup-hook path before calling a facility wrapper, but
the final wrapper-resolved environment can overwrite that variable.

Observed on BlueBolt on March 19, 2026:

- Shotbot exports `PYTHON_CUSTOM_SCRIPTS_3DE4=<shotbot scripts>:$PYTHON_CUSTOM_SCRIPTS_3DE4`
- the site `3de_tools-1.4.0` package assigns `PYTHON_CUSTOM_SCRIPTS_3DE4` to its
  own package path instead of appending

Result: Shotbot's 3DE callback path may never reach the actual DCC process even
though Shotbot exported it successfully in the parent shell.

This generalizes to other DCCs: inspect final wrapper-resolved values for
startup hook variables before assuming the caller's export survived.

### Delayed Context Promotion

A DCC can start in a coarse context (for example `Shot`) and later promote into
the expected task/work-area context only after a Toolkit app performs a
save/open/change-context action.

Observed on BlueBolt in 3DE on March 19, 2026:

- before `File Save...`: `Shot BOB_205_017_430`
- after `File Save...`: `mm-default BOB_205_017_430, Shot BOB_205_017_430`

The command owner in that case was `tk-multi-workfiles2`, and its code path
contains `sgtk.platform.change_context(ctx)` in
`python/tk_multi_workfiles/actions/file_action.py`, reached through
`save_as_file_action.py`.

For other DCCs, use the same heuristic:

- inspect `engine.context` before and after the user action
- compare the command list before and after
- inspect the owning Toolkit app for `change_context`, `scene_operation`, and
  work-area resolution logic
- distinguish between app-bundle defaults and site hook overrides under
  `cfg/config/`

### RV Launch Path (F5)

RV is launched through a single code path via `CommandLauncher.launch()`:

The UI context menu (in `ui/grid_context_menu_mixin.py`) calls `_open_main_plate_in_rv()`,
which discovers the main plate for a shot, then creates a `LaunchRequest(app_name="rv",
workspace_path=..., context=LaunchContext(sequence_path=plate_path))` and delegates to
`CommandLauncher.launch()`.

The request is dispatched to `_launch_standard()` (since neither `scene` nor `file_path`
is set), which routes through `RVAppHandler` in `launch/app_handlers.py`. The handler
calls `commands/rv_commands.build_rv_command()` to build the RV command with the plate
path, then `ProcessExecutor` executes the command through the standard workspace/Rez
pipeline.
