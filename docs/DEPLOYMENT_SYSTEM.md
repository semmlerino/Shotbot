# Deployment System

Shotbot deployment is bundle-based:

`commit on main -> post-commit bundle -> push encoded-releases -> pull/decode on VFX server`

## Artifacts

- `encoded_releases/shotbot_latest.txt` - Base64-encoded application bundle
- `encoded_releases/shotbot_latest_metadata.json` - Source commit and bundle metadata

## Automated Flow

### 1. Post-Commit Hook (`.git/hooks/post-commit`)

Runs quality checks (ruff, basedpyright, deptry), creates the bundle using V1
format (gzip + base64), and dispatches background push.

### 2. Background Push (`.git/hooks/push_bundle_background.sh`)

Uses git plumbing (`hash-object`, `mktree`, `commit-tree`, `update-ref`) to update
`encoded-releases` without branch switching or working-tree mutation. Acquires a
lock file (`flock`) to prevent concurrent pushes.

## Logs

All hook output is written to `.post-commit-output/` (check `summary.txt` first, then individual log files).

Runtime launcher diagnostics on the remote host are separate:

- `~/.shotbot/logs/shotbot.log` - Shotbot application logs
- `~/.shotbot/logs/dispatcher.out` - stdout/stderr from the spawned DCC launch shell

## Manual Operations

### Create Bundle Manually

```bash
uv run python deploy/bundle_app.py -c transfer_config.json
```

### Deploy on Remote VFX Host

```bash
git checkout encoded-releases
git pull origin encoded-releases
python deploy/decode_app.py shotbot_latest.txt
cd shotbot_bundle_temp
export SHOTBOT_SCRIPTS_DIR="$PWD/scripts"
python shotbot.py
```

`SHOTBOT_SCRIPTS_DIR` is required when the deployed host does not provide the
expected external Shotbot scripts location. This keeps Nuke/3DE startup hooks
pointing at the bundled `scripts/` directory.

## Common Failure Modes

### Push Rejected (non-fast-forward)

Cause: local `encoded-releases` ref diverged from remote.

Recovery:

```bash
git fetch origin encoded-releases
git checkout encoded-releases
git reset --hard origin/encoded-releases
git checkout main
```

### Import Errors in Decoded Bundle

Typical causes:

1. Bundle not regenerated after code changes
2. Missing file in `transfer_config.json`
3. Stale import paths after refactor

Minimal recovery loop:

```bash
uv run python -c "from config import Config; print('OK')"
uv run python deploy/bundle_app.py -c transfer_config.json
python deploy/decode_app.py shotbot_latest.txt
```

### Missing Toolkit Apps or Startup Hooks in DCC

Typical causes:

1. `SHOTBOT_SCRIPTS_DIR` not set on the deployed host
2. Bundled `scripts/` directory missing or incomplete
3. Site Rez package / wrapper did not start an initial SGTK engine
4. Site wrapper resolved a different DCC or tools package than direct `rez env` inspection suggested

Minimal recovery loop:

```bash
cd shotbot_bundle_temp
export SHOTBOT_SCRIPTS_DIR="$PWD/scripts"
test -f "$SHOTBOT_SCRIPTS_DIR/init.py"
test -f "$SHOTBOT_SCRIPTS_DIR/3de_sgtk_context_callback.py"
python shotbot.py
```

### DCC Fails Inside the Site Wrapper

Typical signs:

1. `dispatcher.out` shows a facility banner such as `PIPELINE 3DE WRAPPER`
2. The same failure reproduces under `ws <shot> && <dcc> ...` outside Shotbot
3. Direct `rez env <package>` output does not match the DCC version actually launched

Recommended triage:

```bash
tail -n 200 ~/.shotbot/logs/shotbot.log
tail -n 200 ~/.shotbot/logs/dispatcher.out

type -a <dcc> launch
command -v <dcc>
command -v launch
head -n 200 "$(command -v <dcc>)"
head -n 200 "$(command -v launch)"

ws <show>/<seq>/<shot> && <dcc> <args>
ws <show>/<seq>/<shot> && rez env <package> -- bash -lc 'env | grep -E "^(PYTHON(HOME|PATH)?|SGTK_|SHOTGUN_|TK_|TANK_|REZ_)"'

# 3DE-specific comparison
ws <show>/<seq>/<shot> && launch 3de -- 3DE4
ws <show>/<seq>/<shot> && launch 3de --add 3de_tools -- 3DE4
ws <show>/<seq>/<shot> && launch 3de -- env | grep -E '^(PYTHON(HOME|PATH)?|PYTHON_CUSTOM_SCRIPTS_3DE4|TDE4_ROOT|REZ_)'
ws <show>/<seq>/<shot> && launch 3de --add 3de_tools -- env | grep -E '^(PYTHON(HOME|PATH)?|PYTHON_CUSTOM_SCRIPTS_3DE4|TDE4_ROOT|REZ_|SGTK_)'

sed -n '1,220p' /software/bluebolt/rez/packages/bluebolt/3de_tools/1.4.0/package.py
sed -n '1,220p' /software/bluebolt/rez/packages/thirdparty/3de/4.7.1/package.py

grep -RInE '<dcc>|<tools_package>' \
  /software/bluebolt/rez/environments/show_overrides \
  /software/bluebolt/rez/environments/package_overrides
```

Interpretation:

- If the failure reproduces outside Shotbot, fix the facility wrapper / launch
  package / Rez overrides first.
- Do not assume the wrapper-resolved DCC version matches a direct
  `rez env <package>` inspection.
- For 3DE on BlueBolt, `3de` currently chains to `launch 3de --add 3de_tools -- 3DE4`.
  Isolate `3de_tools` by comparing launch behavior with and without that extra package.
- If both `launch 3de -- 3DE4` and `launch 3de --add 3de_tools -- 3DE4` fail
  or emit the same warnings, the base 3DE runtime is already suspect before
  Toolkit packages are added.
- Treat shell warnings and final in-DCC state separately. A wrapper can emit
  embedded-Python warnings while the DCC still reaches a live Toolkit engine.
- If the site tools package overwrites a startup-hook variable such as
  `PYTHON_CUSTOM_SCRIPTS_3DE4`, Shotbot's exported hook path may not survive
  into the final DCC process.

### Partial Toolkit Context After Successful Launch

Typical signs:

1. A Toolkit engine is already running inside the DCC
2. Only a small subset of Toolkit commands is visible initially
3. Running one Toolkit menu command such as `File Save...` suddenly adds
   `Publish...`, `Work Area Info...`, or other task-scoped commands
4. `engine.context` becomes more specific after that action

Recommended triage inside the DCC:

```python
import inspect
import pprint
import sgtk

e = sgtk.platform.current_engine()
cmd = e.commands["File Save..."]
cb = cmd["callback"]

print("ENGINE:", e)
print("CONTEXT BEFORE:", e.context if e else None)
print("CALLBACK MODULE:", getattr(cb, "__module__", None))
print("CALLBACK FILE:", inspect.getsourcefile(cb) or inspect.getfile(cb))
print("APP DISK LOCATION:", getattr(cmd["properties"].get("app"), "disk_location", None))
pprint.pprint(sorted(e.commands.keys()))
```

Then run the user action and compare:

```python
import sgtk
e = sgtk.platform.current_engine()
print("CONTEXT AFTER:", e.context if e else None)
print("COMMANDS AFTER:", sorted(e.commands.keys()) if e else None)
```

Follow-up inspection on the remote shell:

```bash
APP='<app disk location from the DCC output>'
CFG='~/.shotgun/<site>/<pipeline_config>/cfg'

sed -n '1,260p' "$APP/app.py"
sed -n '1,240p' "$APP/python/tk_multi_workfiles/actions/save_as_file_action.py"
sed -n '1,240p' "$APP/python/tk_multi_workfiles/actions/file_action.py"
sed -n '1,240p' "$APP/python/tk_multi_workfiles/scene_operation.py"
grep -RIn 'scene_operation|change_context' "$APP" "$CFG/config"
```

Interpretation:

- If `callback.__module__` points at Toolkit core such as `tank.platform.engine`,
  that may only be the wrapper callback.
- The real command owner is usually `commands[name]["properties"]["app"]`.
- Look for `sgtk.platform.change_context(...)`, `scene_operation`, save/open
  actions, and work-area resolution in the owning app bundle.
- Distinguish between the app bundle default flow and any site overrides under
  `cfg/config`.

Observed on BlueBolt in 3DE on March 19, 2026:

- `File Save...` was owned by `tk-multi-workfiles2`
- Toolkit core wrapped the callback in `tank.platform.engine`
- the context changed from `Shot BOB_205_017_430` to
  `mm-default BOB_205_017_430, Shot BOB_205_017_430`
- additional commands appeared after that context promotion
- `tk-multi-workfiles2/python/tk_multi_workfiles/actions/file_action.py`
  contains `sgtk.platform.change_context(ctx)`
- `tk-multi-workfiles2/python/tk_multi_workfiles/actions/save_as_file_action.py`
  changes to `self.environment.context` before saving when the current app
  context is too coarse
- `tk-multi-workfiles2/python/tk_multi_workfiles/scene_operation.py` then
  drives the save/save-as hook path
- grepping `cfg/config` for `scene_operation` / `change_context` produced no
  site override hits, so the default app code path was likely active

## Guardrails

1. Do not use destructive cleanup commands in deployment hooks (`git rm -rf .`).
2. Keep deployment behavior branch-agnostic (no checkout from background script).
3. Treat `.post-commit-output/` logs as the first source of truth for failures.
4. Treat `SHOTBOT_SCRIPTS_DIR` as part of the production launch contract when
   deploying outside the facility's shared Shotbot scripts location.
5. When a DCC launch fails, reproduce it through the facility wrapper outside
   Shotbot before changing Shotbot launcher code.
6. When a DCC launches with a partial Toolkit menu, inspect the owning Toolkit
   app and context-change path before modifying Shotbot startup scripts.
7. For Workfiles-driven DCCs, inspect the owning app's `actions/` modules and
   `scene_operation.py` before assuming the launcher failed to bootstrap SGTK.
