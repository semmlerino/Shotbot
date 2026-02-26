# Deployment System

Shotbot deployment is bundle-based:

`commit on master -> post-commit bundle -> push encoded-releases -> pull/decode on VFX server`

## Artifacts

- `encoded_releases/shotbot_latest.txt` - Base64-encoded application bundle
- `encoded_releases/shotbot_latest_metadata.json` - Source commit and bundle metadata

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
python shotbot.py
```

## Common Failure Modes

### Push Rejected (non-fast-forward)

Cause: local `encoded-releases` ref diverged from remote.

Recovery:

```bash
git fetch origin encoded-releases
git checkout encoded-releases
git reset --hard origin/encoded-releases
git checkout master
```

### Import Errors in Decoded Bundle

Typical causes:

1. Bundle not regenerated after code changes
2. Missing file in `transfer_config.json`
3. Stale import paths after refactor

Minimal recovery loop:

```bash
uv run python -c "from config import AppConfig; print('OK')"
uv run python bundle_app.py -c transfer_config.json
python decode_app.py shotbot_latest.txt
```

## Guardrails

1. Do not use destructive cleanup commands in deployment hooks (`git rm -rf .`).
2. Keep deployment behavior branch-agnostic (no checkout from background script).
3. Treat `.post-commit-output/` logs as the first source of truth for failures.
