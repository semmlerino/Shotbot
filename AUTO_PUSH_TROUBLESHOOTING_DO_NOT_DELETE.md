# Auto-Push System Troubleshooting Guide

## Critical Lessons Learned

### Issue 1: Dangerous `git rm -rf .` Command
**Problem**: Original implementation included `git rm -rf .` in the background script to "clean" the encoded-releases branch before copying new bundles.

**Impact**: When the background script ran while git was still processing, it deleted 236 files across branches, including all source code files.

**Root Cause**: `git rm -rf .` affects the working tree, not just the current branch. When switching branches, this command deleted files that existed in the working directory.

**Solution**: Removed the `git rm -rf .` command entirely. Instead, we simply overwrite the bundle files:
```bash
# DANGEROUS - DO NOT USE
git rm -rf . 2>> "$LOG_FILE" || true

# SAFE - Just copy and overwrite
cp "$TEMP_DIR/shotbot_latest.txt" shotbot_latest.txt 2>> "$LOG_FILE"
cp "$TEMP_DIR/shotbot_latest_metadata.json" shotbot_latest_metadata.json 2>> "$LOG_FILE"
```

### Issue 2: Branch-Switching File Access
**Problem**: Switching branches changes the working directory contents. If the background script tries to access files from the master branch after switching to encoded-releases, those files don't exist.

**Impact**: `cp: cannot stat 'encoded_releases/shotbot_latest.txt': No such file or directory`

**Solution**: Copy bundle files to temporary location BEFORE switching branches:
```bash
# Copy to temp FIRST (while still on master)
TEMP_DIR="/tmp/shotbot_bundle_$$"
cp "$PROJECT_ROOT/encoded_releases/shotbot_latest.txt" "$TEMP_DIR/shotbot_latest.txt"

# THEN switch branches
git checkout encoded-releases

# THEN copy from temp to branch
cp "$TEMP_DIR/shotbot_latest.txt" shotbot_latest.txt
```

### Issue 3: Branch Divergence
**Problem**: Local `encoded-releases` branch diverged from remote, causing push failures.

**Symptoms**:
```
! [rejected]        encoded-releases -> encoded-releases (non-fast-forward)
error: failed to push some refs
```

**Solution**: Reset local branch to match remote:
```bash
git checkout encoded-releases
git fetch origin encoded-releases
git reset --hard origin/encoded-releases
git checkout master
```

### Issue 4: Background Script Not Returning to Master
**Problem**: If the background script fails during push or encounters errors, it may not return to the master branch, leaving the repository in an inconsistent state.

**Symptoms**: Running `git branch --show-current` shows `encoded-releases` instead of `master`.

**Solution**:
1. Force switch back to master: `git checkout -f master`
2. The background script now includes proper error handling to ensure branch return even on failure

## Recovery Procedures

### If Files Are Accidentally Deleted
1. **DO NOT PANIC** - Git has your files
2. Check which commit deleted them: `git log --oneline --stat -5`
3. Reset to the commit before deletion: `git reset --hard <commit-hash>`
4. Example: `git reset --hard 1f06520`

### If Stuck on Wrong Branch
```bash
# Force return to master
git checkout -f master

# Verify you're on master
git branch --show-current

# Check status
git status
```

### If Bundle Push Keeps Failing
1. Check the log: `cat .post-commit-output/bundle-push.log`
2. Common issues:
   - **No changes**: Bundle content hasn't changed since last push (safe to ignore)
   - **Non-fast-forward**: Branch divergence, need to sync (see Issue 3 above)
   - **Network error**: Check GitHub connectivity
   - **Authentication**: Verify git credentials

### If Background Script Hangs
1. Find the process: `ps aux | grep push_bundle_background`
2. Kill it: `kill -9 <PID>`
3. Manually clean up: `rm -rf /tmp/shotbot_bundle_*`
4. Return to master: `git checkout -f master`

## Safety Checks Before Modifying Hooks

Before editing `.git/hooks/post-commit` or `.git/hooks/push_bundle_background.sh`:

1. **Test on a separate branch first**
2. **Never use `git rm -rf .` or similar destructive commands**
3. **Always copy files to temp before branch switching**
4. **Ensure proper cleanup in error paths**
5. **Log everything for debugging**

## Monitoring the System

### Check if auto-push worked:
```bash
# View latest bundle creation
cat .post-commit-output/bundle.txt

# View background push status
cat .post-commit-output/bundle-push.log

# Check if files were pushed to remote
git log origin/encoded-releases -3
```

### Expected success output in bundle-push.log:
```
✓ Successfully pushed to origin/encoded-releases
✓ SUCCESS
Switching back to master...
Cleaning up temp files...
```

## Architecture Safeguards

The current implementation includes these safety features:

1. **Non-blocking**: Post-commit hook exits immediately, background script runs independently
2. **Temporary files**: Bundle copied to `/tmp` before any git operations
3. **No destructive commands**: No `git rm`, `rm -rf`, or force flags
4. **Error logging**: All operations logged to `.post-commit-output/bundle-push.log`
5. **Cleanup**: Temp files removed after use (`rm -rf /tmp/shotbot_bundle_$$`)

## When to Disable Auto-Push

Temporarily disable by making the hook non-executable:
```bash
chmod -x .git/hooks/post-commit
```

Re-enable:
```bash
chmod +x .git/hooks/post-commit
```

## Related Documentation

- System architecture is documented in CLAUDE.md under "Auto-Push System"
- `.post-commit-output/` - Logs from hook execution
