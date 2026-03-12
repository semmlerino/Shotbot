# Deployment System

Shotbot deployment is bundle-based:

`commit on main -> post-commit bundle -> push encoded-releases -> pull/decode on VFX server`

## Artifacts

- `encoded_releases/shotbot_latest.txt` - Base64-encoded application bundle
- `encoded_releases/shotbot_latest_metadata.json` - Source commit and bundle metadata

## Reusing This In Another Repository

This document is the operational overview for Shotbot's live deployment path.

If you want to reuse the same base64-plus-git workflow in another repository, use the tracked portable copy in `bundle_workflow_template/` instead of copying from `.git/hooks/` manually. That folder now contains:

- the bundling scripts
- generic hook templates
- a reusable transfer config
- instructions for installing and customizing the workflow

## Automated Flow

### 1. Post-Commit Hook (`.git/hooks/post-commit`)

Runs quality checks, creates bundle artifacts, and dispatches background push.

### 2. Background Push (`.git/hooks/push_bundle_background.sh`)

Uses git plumbing (`hash-object`, `mktree`, `commit-tree`, `update-ref`) to update
`encoded-releases` without branch switching or working-tree mutation.

## Logs

All hook output is written to `.post-commit-output/`:

- `bundle.txt`
- `bundle-push.log`
- `import-test.txt`
- `type-check.txt`
- `ruff-check.txt`
- `deptry-check.txt`
- `summary.txt`
- `commit_msg.txt`
- `current_commit.txt`
- `current_branch.txt`
- `info.txt`
- `background-startup.log`

## Manual Operations

### Create Bundle Manually

```bash
uv run python bundle_app.py -c transfer_config.json
```

### Deploy on Remote VFX Host

```bash
git checkout encoded-releases
git pull origin encoded-releases
python decode_app.py shotbot_latest.txt
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
uv run python bundle_app.py -c transfer_config.json
python decode_app.py shotbot_latest.txt
```

### Missing Toolkit Apps or Startup Hooks in DCC

Typical causes:

1. `SHOTBOT_SCRIPTS_DIR` not set on the deployed host
2. Bundled `scripts/` directory missing or incomplete
3. Site Rez package / wrapper did not start an initial SGTK engine

Minimal recovery loop:

```bash
cd shotbot_bundle_temp
export SHOTBOT_SCRIPTS_DIR="$PWD/scripts"
test -f "$SHOTBOT_SCRIPTS_DIR/init.py"
test -f "$SHOTBOT_SCRIPTS_DIR/3de_sgtk_context_callback.py"
python shotbot.py
```

## Guardrails

1. Do not use destructive cleanup commands in deployment hooks (`git rm -rf .`).
2. Keep deployment behavior branch-agnostic (no checkout from background script).
3. Treat `.post-commit-output/` logs as the first source of truth for failures.
4. Treat `SHOTBOT_SCRIPTS_DIR` as part of the production launch contract when
   deploying outside the facility's shared Shotbot scripts location.
