# Portable Encoded-Bundle Workflow

This folder is the reusable copy of the base64 bundle workflow.

Before this was added, the workflow was only partially documented:

- `docs/DEPLOYMENT_SYSTEM.md` explained how Shotbot uses the flow.
- The actual Git hook scripts lived only in `.git/hooks/`, which is not tracked.
- The files you need to copy into another repository were split across multiple locations.

This folder puts the required pieces in one tracked place so you can copy it into another project and adapt it there.

## Included Files

- `bundle_app.py` - Collects project files into a temporary bundle directory, then calls `transfer_cli.py`
- `transfer_cli.py` - Compresses and base64-encodes the bundle directory
- `decode_app.py` - Decodes and extracts an encoded bundle on the target machine
- `transfer_config.json` - Generic include/exclude rules for the portable workflow
- `hooks/post-commit` - Creates the bundle after each commit and starts the background push
- `hooks/push_bundle_background.sh` - Pushes the latest bundle to the encoded release branch with Git plumbing

## How To Reuse It

1. Copy `bundle_workflow_template/` into the root of the target repository.
2. Edit `bundle_workflow_template/transfer_config.json` so the include/exclude rules match the target project.
3. Copy the hook templates into `.git/hooks/` in the target repository.
4. Make both installed hooks executable.
5. Commit on the main development branch and inspect `.post-commit-output/` after the first run.

## Hook Installation

```bash
cp bundle_workflow_template/hooks/post-commit .git/hooks/post-commit
cp bundle_workflow_template/hooks/push_bundle_background.sh .git/hooks/push_bundle_background.sh
chmod +x .git/hooks/post-commit .git/hooks/push_bundle_background.sh
```

## Optional Environment Overrides

The hook templates support these environment variables if you need to change defaults:

- `BUNDLE_WORKFLOW_DIR` - Folder name that contains this workflow (default: `bundle_workflow_template`)
- `BUNDLE_PROJECT_NAME` - Used to build the stable artifact name (default: repository folder name)
- `BUNDLE_BASENAME` - Stable artifact basename inside `encoded_releases/`
- `BUNDLE_CONFIG_PATH` - Full path to the config file the bundler should use
- `BUNDLE_PYTHON` - Python interpreter to use for the workflow
- `ENCODED_RELEASE_BRANCH` - Branch that stores the encoded artifacts (default: `encoded-releases`)

## Default Runtime Flow

1. `post-commit` runs after each commit.
2. It optionally runs `ruff`, `basedpyright`, and `deptry` if they are installed.
3. It runs `bundle_workflow_template/bundle_app.py` from the repository root.
4. The hook copies the newest `encoded_app_*.txt` and metadata into `encoded_releases/<project>_latest.*`.
5. The hook starts `push_bundle_background.sh`.
6. The background script writes the encoded files directly to the target branch using Git plumbing (`hash-object`, `mktree`, `commit-tree`, `update-ref`).

## Manual Commands

Create an encoded bundle manually:

```bash
python3 bundle_workflow_template/bundle_app.py -c bundle_workflow_template/transfer_config.json
```

Decode the latest bundle manually:

```bash
python3 bundle_workflow_template/decode_app.py encoded_releases/<project>_latest.txt
```

## What To Customize Per Project

- Add or remove include patterns in `transfer_config.json`.
- Add or remove exclude patterns in `transfer_config.json`.
- Decide whether `encoded-releases` is the right branch name.
- Decide whether the optional lint/type/dependency checks belong in the hook for that repository.
- If the target project needs smoke tests after commit, add them to the hook explicitly.

The shipped config starts conservative on purpose. Add shell scripts, documentation, Docker files, or other non-runtime assets only if the target project actually needs them in the deployed bundle.

## Maintenance Note

This folder is a copy, not a shared implementation.

If the root deployment scripts change (`bundle_app.py`, `transfer_cli.py`, `decode_app.py`, or the live hooks), update this folder as well so the portable copy stays aligned with the active workflow.
