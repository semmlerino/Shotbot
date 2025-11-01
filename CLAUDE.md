# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Shotbot is a PySide6-based GUI application for VFX production management. The application provides shot tracking, media management, and workflow automation for visual effects pipelines.

## Deployment Environment

### Remote VFX Environment
**Shotbot runs on a remote VFX production environment**, not on the development machine:

- **Development Location**: `/mnt/c/CustomScripts/Python/PyFFMPEG/BB/shotbot` (WSL2/Windows)
- **Production Location**: `/nethome/gabriel-h/Python/Shotbot/` (Remote Linux VFX server)
- **Deployment Method**: Encoded bundle transfer via `encoded-releases` branch

### Encoded Bundle System
The application uses an automated encoding/deployment system:

1. **Development**: Code changes are committed to `master` branch
2. **Auto-Encoding**: Post-commit hook automatically creates base64-encoded bundle
3. **Auto-Push**: Bundle is pushed to `encoded-releases` branch on GitHub
4. **Remote Deployment**: Bundle is pulled and decoded on the VFX server
5. **Execution**: Application runs in production environment with VFX tools

**Bundle Files**:
- `shotbot_latest.txt` - Base64-encoded compressed application bundle
- `shotbot_latest_metadata.json` - Bundle metadata (commit info, size, timestamp)

### Why This Architecture?
- **Isolated Environments**: Dev machine (Windows/WSL) ≠ Production (Linux VFX pipeline)
- **Dependency Isolation**: VFX environment has specific Python/Qt versions
- **Easy Deployment**: Single base64 file transfer instead of complex file sync
- **Version Control**: GitHub acts as deployment artifact repository

## Development Commands

### Running Locally (Development)
```bash
# Activate virtual environment
source .venv/bin/activate

# Run the application
~/.local/bin/uv run python shotbot.py
```

### Testing Before Deployment
```bash
# Run type checking
~/.local/bin/uv run basedpyright

# Run linting
~/.local/bin/uv run ruff check .

# Run tests
~/.local/bin/uv run pytest tests/
```

### Creating Deployment Bundle
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

# Decode and extract bundle
python decode_app.py shotbot_latest.txt

# Run the application
cd shotbot_bundle_temp
python shotbot.py
```

## Import Errors and Debugging

### Common Import Issues
If you see import errors like:
```
ImportError: cannot import name 'Config' from 'config'
```

This typically means:
1. **Bundle is out of sync** - The encoded bundle doesn't match current codebase
2. **Missing file in bundle** - `transfer_config.json` doesn't include the file
3. **Import path mismatch** - Module structure changed but imports weren't updated

### Fixing Import Errors
1. **Verify Local Imports Work**:
   ```bash
   ~/.local/bin/uv run python -c "from config import AppConfig; print('OK')"
   ```

2. **Check transfer_config.json**:
   ```bash
   cat transfer_config.json
   ```
   Ensure all required files are included in the bundle.

3. **Regenerate Bundle**:
   ```bash
   # Commit changes to trigger auto-bundle
   git commit -m "fix: Update imports"

   # Or manually create bundle
   ~/.local/bin/uv run python bundle_app.py -c transfer_config.json
   ```

4. **Test Decoded Bundle Locally**:
   ```bash
   python decode_app.py shotbot_latest.txt
   cd shotbot_bundle_temp
   python shotbot.py
   ```

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
The `.git/hooks/push_bundle_background.sh` script:
1. Switches to `encoded-releases` branch
2. Updates `shotbot_latest.txt` and metadata
3. Commits and pushes to `origin/encoded-releases`
4. Switches back to original branch

### Troubleshooting Auto-Push
Check the logs in `.post-commit-output/`:
- `bundle.txt` - Bundle creation log
- `bundle-push.log` - Push to encoded-releases log
- `import-test.txt` - Import validation results
- `type-check.txt` - Type checking results

## Dependencies

### Development Environment
- Python 3.12+ (via uv)
- PySide6 (Qt for Python)
- Development tools: basedpyright, ruff, pytest

### Production Environment (VFX Server)
- Python 3.x (VFX pipeline version)
- PySide6 (matching VFX pipeline)
- Various VFX tools and libraries

**Note**: Production dependencies may differ from development. The encoded bundle is self-contained but requires compatible Python/Qt versions on the target system.

## Project Structure

```
shotbot/
├── controllers/       # Application controllers
├── core/             # Core business logic
├── launcher/         # Launch system components
├── tests/            # Test suite
├── docs/             # Documentation
├── .git/hooks/       # Git hooks for auto-push
├── shotbot.py        # Main entry point
├── bundle_app.py     # Bundle encoding script
├── decode_app.py     # Bundle decoding script
├── transfer_config.json  # Bundle configuration
└── encoded_releases/ # Local copy of encoded bundles
```

## Type Safety

The project uses basedpyright for type checking with strict settings:
- All refactored code has comprehensive type hints
- `reportOptionalMemberAccess` enabled (no suppressions)
- Configuration in `pyproject.toml` and `pyrightconfig.json`

Current status: **0 errors, 0 warnings, 0 notes** ✅

## Testing

Run tests with:
```bash
~/.local/bin/uv run pytest tests/
```

Test coverage is tracked and the project maintains comprehensive test suites for:
- Core business logic
- Controllers and managers
- UI components (where possible)
- Integration scenarios
