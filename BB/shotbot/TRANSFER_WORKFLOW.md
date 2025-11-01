# Automated Base64 Transfer Workflow

This document describes the automated base64 encoding workflow that runs after each git commit.

## Overview

The transfer workflow automatically encodes all application files to base64 format after each commit, creating a portable snapshot that can be easily transferred or archived. The encoded files are optionally pushed to a separate `encoded-releases` branch in the remote repository.

## Components

### 1. **transfer_cli.py**
Command-line tool for encoding directories to base64 format.
- Encodes folders using tar.gz compression followed by base64 encoding
- Supports chunking for large files
- Compatible with Transfer.py GUI application

**Usage:**
```bash
python transfer_cli.py <folder> -o output.txt -c 5120 --metadata
```

### 2. **bundle_app.py**
Application bundler that collects relevant files for encoding.
- Respects .gitignore patterns
- Filters files based on configuration
- Creates temporary bundle directory

**Usage:**
```bash
python bundle_app.py -o encoded_output.txt --list-files
```

### 3. **transfer_config.json**
Configuration file controlling the workflow behavior.
- Include/exclude patterns for files
- Chunk size settings
- Auto-push configuration
- Output directory settings

### 4. **Git Hook (post-commit)**
Automatically triggered after each commit.
- Runs in background to not block git workflow
- Creates timestamped encoded files
- Optionally pushes to remote branch

### 5. **setup_transfer_hook.py**
Setup and management script for the workflow.

**Commands:**
```bash
# Install the workflow
python setup_transfer_hook.py install

# Check status
python setup_transfer_hook.py status

# Test the workflow
python setup_transfer_hook.py test

# Disable temporarily
python setup_transfer_hook.py disable

# Enable again
python setup_transfer_hook.py enable

# Uninstall
python setup_transfer_hook.py uninstall
```

## Installation

1. Run the setup script:
```bash
python setup_transfer_hook.py install
```

2. The hook will automatically run after each commit

## Configuration

Edit `transfer_config.json` to customize:

- **include_patterns**: File patterns to include
- **exclude_patterns**: File patterns to exclude
- **chunk_size_kb**: Size of each chunk (default: 5120 KB)
- **auto_push**: Whether to push to remote (default: false)
- **remote_branch**: Branch name for encoded files (default: encoded-releases)
- **max_releases_to_keep**: Number of releases to keep locally (default: 10)

## Workflow Operation

1. **After Commit**: The post-commit hook triggers automatically
2. **Bundle Creation**: Application files are collected based on configuration
3. **Encoding**: Bundle is encoded to base64 format
4. **Storage**: Encoded file saved to `encoded_releases/` directory
5. **Push (Optional)**: If enabled, pushes to remote branch

## Output

Encoded files are saved as:
```
encoded_releases/encoded_app_YYYYMMDD_HHMMSS_<commit_hash>.txt
```

Each file contains:
- Metadata header with timestamp and statistics
- Base64 encoded tar.gz archive of application files

## Decoding

To decode a release:

1. Using Transfer.py GUI application:
   - Load the encoded file
   - Select output directory
   - Click Decode

2. Using command line:
   ```bash
   # Extract base64 content (skip metadata)
   tail -n +12 encoded_app_*.txt | base64 -d | tar -xzf -
   ```

## Disabling/Enabling

To temporarily disable the workflow:
```bash
touch .skip-transfer-hook
# or
python setup_transfer_hook.py disable
```

To re-enable:
```bash
rm .skip-transfer-hook
# or
python setup_transfer_hook.py enable
```

## Troubleshooting

1. **Check logs**: `.git/hooks/post-commit.log`
2. **Verify installation**: `python setup_transfer_hook.py status`
3. **Test manually**: `python bundle_app.py --list-files`
4. **Run tests**: `python setup_transfer_hook.py test`

## Notes

- The workflow runs in background and doesn't block git operations
- Errors in encoding don't fail the commit
- Encoded files are excluded from git tracking via .gitignore
- The workflow respects existing .gitignore patterns