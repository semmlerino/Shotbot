# Auto-Push System for Encoded Releases

This repository uses a post-commit hook system to automatically create and push encoded bundles to the `encoded-releases` branch.

## How It Works

### 1. Post-Commit Hook (`.git/hooks/post-commit`)
After every commit on the master branch:
- Creates encoded bundle via `bundle_app.py`
- Generates timestamped bundle: `encoded_app_YYYYMMDD_HHMMSS.txt`
- Creates consistent bundle: `encoded_releases/shotbot_latest.txt`
- Saves commit context (branch, message, hash)
- Launches background push script

### 2. Background Push Script (`.git/hooks/push_bundle_background.sh`)
Runs independently after the commit completes:
- Waits 3 seconds for git to finish
- Copies bundles to `/tmp` directory (avoids branch-switching issues)
- Switches to `encoded-releases` branch
- Copies `shotbot_latest.txt` and metadata from temp to branch
- **Updates metadata with source commit hash and timestamp** (ensures changes on every commit)
- Creates commit with original commit reference
- Pushes to `origin/encoded-releases`
- Switches back to original branch
- Cleans up temp files
- Logs everything to `.post-commit-output/bundle-push.log`

## Architecture Benefits

**Separation of Concerns**: Post-commit hook doesn't do branch switching
**Non-Blocking**: Commit completes immediately, push happens in background
**Reliable**: No branch-switching conflicts during commit
**Extensible**: Easy to add notifications, retries, cleanup
**Debuggable**: Separate log file for troubleshooting

## Logs

Check these files after each commit:
- `.post-commit-output/bundle.txt` - Bundle creation status
- `.post-commit-output/bundle-push.log` - Background push status
- `.post-commit-output/summary.txt` - Overall summary

## Setup

The hooks are already installed and active. Every commit to master will automatically:
1. Create an encoded bundle
2. Push it to the `encoded-releases` branch in the background

To manually run the background push:
```bash
.git/hooks/push_bundle_background.sh
```

## Safety Notes

The background script uses temporary files (`/tmp/shotbot_bundle_$$`) to safely handle branch switching:
- Bundle files are copied to temp directory BEFORE any git operations
- Branch switching doesn't affect the source files
- No `git rm` commands that could accidentally delete files across branches
- Clean separation between bundle creation and git operations

## Troubleshooting

If auto-push fails:
1. Check `.post-commit-output/bundle-push.log` for errors
2. Verify `encoded_releases/shotbot_latest.txt` exists
3. Ensure git credentials are configured
4. Check network connectivity to GitHub
5. If push is rejected (non-fast-forward), the remote branch may need manual sync
