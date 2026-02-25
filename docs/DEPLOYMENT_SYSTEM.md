# Deployment System

Shotbot uses an encoded bundle system for deployment. Code changes committed to `master` are automatically bundled, pushed to the `encoded-releases` branch on GitHub, then pulled and decoded on the remote VFX production server.

## Encoded Bundle System

The application uses an automated encoding/deployment system:

1. **Development**: Code changes are committed to `master` branch
2. **Auto-Encoding**: Post-commit hook automatically creates base64-encoded bundle
3. **Auto-Push**: Bundle is pushed to `encoded-releases` branch on GitHub
4. **Remote Deployment**: Bundle is pulled and decoded on the VFX server
5. **Execution**: Application runs in production environment with VFX tools

**Bundle Files**:
- `shotbot_latest.txt` - Base64-encoded compressed application bundle
- `shotbot_latest_metadata.json` - Bundle metadata (commit info, size, timestamp)

## Auto-Push System

### Post-Commit Hook

The `.git/hooks/post-commit` script automatically:
1. Runs type checking and linting
2. Creates encoded application bundle
3. Copies bundle to `encoded_releases/` directory
4. Launches background script to push to GitHub

**Important**: The hook uses the virtual environment Python:
- `$PROJECT_ROOT/.venv/bin/python3` for all operations
- Ensures PySide6 and other dependencies are available

### Background Push Script

The `.git/hooks/push_bundle_background.sh` script uses git plumbing commands to create a commit on the `encoded-releases` branch **without ever switching branches or touching the working tree**:

1. Reads saved context (current branch, commit hash, message) from `.post-commit-output/`
2. Updates bundle metadata with source commit info
3. Writes the bundle and metadata files as blob objects via `git hash-object -w`
4. Builds a tree from those blobs via `git mktree`
5. Creates a commit against the `encoded-releases` branch tip via `git commit-tree`
6. Advances the branch ref via `git update-ref`
7. Pushes `encoded-releases` to `origin`

No checkout, no stash — the working tree and `HEAD` remain on `master` throughout.

### Troubleshooting

Check the logs in `.post-commit-output/`:
- `bundle.txt` - Bundle creation log
- `bundle-push.log` - Push to encoded-releases log
- `import-test.txt` - Import validation results
- `type-check.txt` - Type checking results

## Manual Bundle Operations

### Creating a Bundle

The bundle is automatically created on commit, but can be manually triggered:
```bash
# Manual bundle creation
~/.local/bin/uv run python bundle_app.py -c transfer_config.json

# Check bundle was created
ls -lh encoded_app_*.txt
```

### Deploying to Remote Environment

On the **remote VFX server**:
```bash
# Pull latest encoded release
git checkout encoded-releases
git pull origin encoded-releases

# Decode and extract bundle (extracts to a subdirectory named after the archive root)
python decode_app.py shotbot_latest.txt

# Run the application — the subdirectory name comes from the archive root,
# currently "shotbot_bundle_temp" (the staging dir used during bundling)
cd shotbot_bundle_temp
python shotbot.py
```

## Import Error Debugging

### Common Causes

If you see import errors like `ImportError: cannot import name 'Config' from 'config'`, this typically means:
1. **Bundle is out of sync** - The encoded bundle doesn't match current codebase
2. **Missing file in bundle** - `transfer_config.json` doesn't include the file
3. **Import path mismatch** - Module structure changed but imports weren't updated

### Fix Steps

1. **Verify local imports work**:
   ```bash
   ~/.local/bin/uv run python -c "from config import AppConfig; print('OK')"
   ```

2. **Check transfer_config.json** — ensure all required files are included in the bundle.

3. **Regenerate bundle**:
   ```bash
   git commit -m "fix: Update imports"
   # Or manually:
   ~/.local/bin/uv run python bundle_app.py -c transfer_config.json
   ```

4. **Test decoded bundle locally**:
   ```bash
   # Extracts to a subdirectory named after the archive root (currently "shotbot_bundle_temp")
   python decode_app.py shotbot_latest.txt
   cd shotbot_bundle_temp
   python shotbot.py
   ```
