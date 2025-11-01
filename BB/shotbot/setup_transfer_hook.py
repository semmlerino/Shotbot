#!/usr/bin/env python3
"""Setup script for the automated base64 transfer workflow.

This script sets up the git hooks and configuration needed for automatic
base64 encoding of application files after each commit.
"""

import argparse
import shutil
import stat
import subprocess
import sys
from pathlib import Path


class TransferHookSetup:
    """Setup and manage the transfer hook workflow."""

    def __init__(self, repo_path: str = ".", verbose: bool = False):
        """Initialize setup with repository path.

        Args:
            repo_path: Path to git repository
            verbose: Enable verbose output
        """
        self.repo_path = Path(repo_path).absolute()
        self.verbose = verbose
        self.git_dir = self.repo_path / ".git"
        self.hooks_dir = self.git_dir / "hooks"

        if not self.git_dir.exists():
            raise ValueError(f"Not a git repository: {self.repo_path}")

    def log(self, message: str):
        """Log a message if verbose mode is enabled."""
        if self.verbose:
            print(f"[SETUP] {message}")

    def check_requirements(self) -> bool:
        """Check if all required files are present.

        Returns:
            True if all requirements are met
        """
        required_files = ["transfer_cli.py", "bundle_app.py", "transfer_config.json"]

        missing = []
        for file in required_files:
            file_path = self.repo_path / file
            if not file_path.exists():
                missing.append(file)

        if missing:
            print(f"ERROR: Missing required files: {', '.join(missing)}")
            return False

        self.log("All required files present")
        return True

    def create_hook_script(self) -> str:
        """Create the post-commit hook script.

        Returns:
            The hook script content
        """
        hook_content = """#!/bin/bash
# Git post-commit hook for automatic base64 encoding of application files
#
# This hook runs after each commit to encode the application files
# and push them to a separate branch in the remote repository.

# Configuration
REPO_ROOT="$(git rev-parse --show-toplevel)"
PYTHON_CMD="${PYTHON_CMD:-python3}"
CONFIG_FILE="$REPO_ROOT/transfer_config.json"
BUNDLE_SCRIPT="$REPO_ROOT/bundle_app.py"
OUTPUT_DIR="$REPO_ROOT/encoded_releases"
LOG_FILE="$REPO_ROOT/.git/hooks/post-commit.log"

# Enable logging
exec 1> >(tee -a "$LOG_FILE")
exec 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Post-commit hook started"

# Check if we should skip the hook (e.g., during merge, rebase, or if disabled)
if [ -f "$REPO_ROOT/.git/MERGE_HEAD" ]; then
    echo "Merge in progress, skipping post-commit hook"
    exit 0
fi

if [ -f "$REPO_ROOT/.git/rebase-merge/interactive" ]; then
    echo "Rebase in progress, skipping post-commit hook"
    exit 0
fi

if [ -f "$REPO_ROOT/.skip-transfer-hook" ]; then
    echo "Transfer hook disabled (found .skip-transfer-hook file)"
    exit 0
fi

# Check if required files exist
if [ ! -f "$BUNDLE_SCRIPT" ]; then
    echo "ERROR: bundle_app.py not found at $BUNDLE_SCRIPT"
    exit 0  # Exit gracefully to not block commits
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "WARNING: transfer_config.json not found, using defaults"
fi

# Get current commit information
COMMIT_HASH=$(git rev-parse HEAD)
COMMIT_SHORT=$(git rev-parse --short HEAD)
COMMIT_MSG=$(git log -1 --pretty=%B)
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')

echo "Processing commit: $COMMIT_SHORT"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Generate output filename
OUTPUT_FILE="$OUTPUT_DIR/encoded_app_${TIMESTAMP}_${COMMIT_SHORT}.txt"

# Run the bundling and encoding process in background to not block git workflow
{
    echo "Starting bundle and encode process..."
    
    # Change to repo root
    cd "$REPO_ROOT"
    
    # Run bundle_app.py
    if $PYTHON_CMD "$BUNDLE_SCRIPT" -c "$CONFIG_FILE" -o "$OUTPUT_FILE"; then
        echo "Successfully created encoded bundle: $OUTPUT_FILE"
        
        # Read config to check if auto-push is enabled
        AUTO_PUSH=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE', 'r')) if os.path.exists('$CONFIG_FILE') else {}; print(c.get('auto_push', True))" 2>/dev/null || echo "True")
        REMOTE_BRANCH=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE', 'r')) if os.path.exists('$CONFIG_FILE') else {}; print(c.get('remote_branch', 'encoded-releases'))" 2>/dev/null || echo "encoded-releases")
        
        if [ "$AUTO_PUSH" = "True" ]; then
            echo "Auto-pushing to remote branch: $REMOTE_BRANCH"
            
            # Save current branch
            CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
            
            # Check if remote branch exists
            if ! git show-ref --verify --quiet "refs/remotes/origin/$REMOTE_BRANCH"; then
                echo "Creating remote branch: $REMOTE_BRANCH"
                # Create an orphan branch for encoded releases
                git checkout --orphan "$REMOTE_BRANCH" 2>/dev/null
                git rm -rf . 2>/dev/null || true
                echo "# Encoded Application Releases" > README.md
                echo "" >> README.md
                echo "This branch contains base64-encoded snapshots of the application." >> README.md
                echo "Each file corresponds to a specific commit in the main branch." >> README.md
                git add README.md
                git commit -m "Initialize encoded releases branch"
                git push -u origin "$REMOTE_BRANCH"
                git checkout "$CURRENT_BRANCH" 2>/dev/null
            else
                # Fetch and checkout the encoded releases branch
                git fetch origin "$REMOTE_BRANCH":"$REMOTE_BRANCH" 2>/dev/null || true
                git checkout "$REMOTE_BRANCH" 2>/dev/null
            fi
            
            # Copy the encoded file
            cp "$OUTPUT_FILE" .
            
            # Add and commit
            git add "$(basename "$OUTPUT_FILE")"
            COMMIT_MESSAGE="Auto-encoded release for commit $COMMIT_SHORT

Original commit: $COMMIT_MSG
Timestamp: $(date '+%Y-%m-%d %H:%M:%S')
Full hash: $COMMIT_HASH"
            
            git commit -m "$COMMIT_MESSAGE"
            
            # Push to remote
            if git push origin "$REMOTE_BRANCH"; then
                echo "Successfully pushed encoded release to $REMOTE_BRANCH"
            else
                echo "WARNING: Failed to push to remote branch $REMOTE_BRANCH"
            fi
            
            # Switch back to the original branch
            git checkout "$CURRENT_BRANCH" 2>/dev/null
            
            # Clean up old releases if configured
            MAX_KEEP=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE', 'r')) if os.path.exists('$CONFIG_FILE') else {}; print(c.get('max_releases_to_keep', 10))" 2>/dev/null || echo "10")
            if [ "$MAX_KEEP" -gt 0 ]; then
                echo "Cleaning up old releases (keeping last $MAX_KEEP)"
                cd "$OUTPUT_DIR"
                ls -t encoded_app_*.txt 2>/dev/null | tail -n +$((MAX_KEEP + 1)) | xargs rm -f 2>/dev/null || true
                cd "$REPO_ROOT"
            fi
        fi
        
    else
        echo "ERROR: Failed to create encoded bundle"
    fi
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Post-commit hook completed"
    
} &

# Run in background and detach
HOOK_PID=$!
echo "Post-commit encoding running in background (PID: $HOOK_PID)"

# Exit immediately to not block git workflow
exit 0
"""
        return hook_content

    def install_hook(self, force: bool = False) -> bool:
        """Install the post-commit hook.

        Args:
            force: Force overwrite if hook already exists

        Returns:
            True if installation successful
        """
        hook_path = self.hooks_dir / "post-commit"

        # Check if hook already exists
        if hook_path.exists() and not force:
            print(f"ERROR: Hook already exists at {hook_path}")
            print("Use --force to overwrite")
            return False

        # Backup existing hook if present
        if hook_path.exists():
            backup_path = hook_path.with_suffix(".backup")
            shutil.copy2(hook_path, backup_path)
            self.log(f"Backed up existing hook to {backup_path}")

        # Create hooks directory if it doesn't exist
        self.hooks_dir.mkdir(parents=True, exist_ok=True)

        # Write hook script
        hook_content = self.create_hook_script()
        hook_path.write_text(hook_content)

        # Make executable
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)

        self.log(f"Installed hook at {hook_path}")
        return True

    def uninstall_hook(self) -> bool:
        """Uninstall the post-commit hook.

        Returns:
            True if uninstallation successful
        """
        hook_path = self.hooks_dir / "post-commit"

        if not hook_path.exists():
            print("No hook installed")
            return False

        # Check if it's our hook
        content = hook_path.read_text()
        if "automatic base64 encoding" not in content:
            print("Hook doesn't appear to be the transfer hook")
            return False

        # Backup before removing
        backup_path = hook_path.with_suffix(".removed")
        shutil.move(str(hook_path), str(backup_path))
        self.log(f"Removed hook (backed up to {backup_path})")

        return True

    def create_encoded_releases_branch(self) -> bool:
        """Create the encoded-releases branch if it doesn't exist.

        Returns:
            True if branch created or already exists
        """
        try:
            # Check if branch exists locally
            result = subprocess.run(
                [
                    "git",
                    "show-ref",
                    "--verify",
                    "--quiet",
                    "refs/heads/encoded-releases",
                ],
                cwd=self.repo_path,
                capture_output=True,
            )

            if result.returncode == 0:
                self.log("encoded-releases branch already exists locally")
                return True

            # Check if branch exists on remote
            result = subprocess.run(
                ["git", "ls-remote", "--heads", "origin", "encoded-releases"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )

            if result.stdout.strip():
                self.log("encoded-releases branch exists on remote")
                # Fetch it
                subprocess.run(
                    ["git", "fetch", "origin", "encoded-releases:encoded-releases"],
                    cwd=self.repo_path,
                    capture_output=True,
                )
                return True

            # Create new orphan branch
            print("Creating encoded-releases branch...")

            # Save current branch
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
            current_branch = result.stdout.strip()

            # Create orphan branch
            subprocess.run(
                ["git", "checkout", "--orphan", "encoded-releases"],
                cwd=self.repo_path,
                capture_output=True,
            )

            # Remove all files
            subprocess.run(
                ["git", "rm", "-rf", "."],
                cwd=self.repo_path,
                capture_output=True,
                stderr=subprocess.DEVNULL,
            )

            # Create README
            readme_path = self.repo_path / "README.md"
            readme_content = """# Encoded Application Releases

This branch contains base64-encoded snapshots of the application.
Each file corresponds to a specific commit in the main branch.

## File Format
- Filename: `encoded_app_YYYYMMDD_HHMMSS_COMMIT.txt`
- Content: Base64-encoded tar.gz archive of application files

## Usage
To decode a release, use the Transfer.py application or transfer_cli.py script.
"""
            readme_path.write_text(readme_content)

            # Commit README
            subprocess.run(["git", "add", "README.md"], cwd=self.repo_path)
            subprocess.run(
                ["git", "commit", "-m", "Initialize encoded releases branch"],
                cwd=self.repo_path,
                capture_output=True,
            )

            # Switch back to original branch
            subprocess.run(
                ["git", "checkout", current_branch],
                cwd=self.repo_path,
                capture_output=True,
            )

            self.log("Created encoded-releases branch")
            return True

        except Exception as e:
            print(f"ERROR: Failed to create branch: {e}")
            return False

    def test_workflow(self) -> bool:
        """Test the workflow by creating a test bundle.

        Returns:
            True if test successful
        """
        print("\nTesting workflow...")

        # Test bundle creation
        try:
            result = subprocess.run(
                [sys.executable, "bundle_app.py", "--list-files"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                print(f"ERROR: Failed to list files: {result.stderr}")
                return False

            # Parse output
            lines = result.stdout.strip().split("\n")
            if lines and "Found" in lines[0]:
                file_count = lines[0].split()[1]
                print(f"✓ Bundle script found {file_count} files")

            # Test encoding a small test directory
            test_dir = self.repo_path / "test_bundle"
            test_dir.mkdir(exist_ok=True)
            test_file = test_dir / "test.txt"
            test_file.write_text("Test content")

            result = subprocess.run(
                [sys.executable, "transfer_cli.py", str(test_dir), "-v"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )

            # Clean up test directory
            shutil.rmtree(test_dir)

            if result.returncode != 0:
                print(f"ERROR: Encoding test failed: {result.stderr}")
                return False

            print("✓ Encoding test successful")
            return True

        except Exception as e:
            print(f"ERROR: Test failed: {e}")
            return False

    def enable_hook(self):
        """Enable the transfer hook."""
        disable_file = self.repo_path / ".skip-transfer-hook"
        if disable_file.exists():
            disable_file.unlink()
            print("Transfer hook enabled")
        else:
            print("Transfer hook is already enabled")

    def disable_hook(self):
        """Disable the transfer hook."""
        disable_file = self.repo_path / ".skip-transfer-hook"
        disable_file.touch()
        print("Transfer hook disabled (create .skip-transfer-hook file)")
        print("To re-enable, delete the .skip-transfer-hook file")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Setup automated base64 transfer workflow"
    )
    parser.add_argument(
        "action",
        choices=["install", "uninstall", "test", "enable", "disable", "status"],
        help="Action to perform",
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Path to git repository (default: current directory)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Force overwrite existing hooks"
    )
    parser.add_argument(
        "--create-branch",
        action="store_true",
        help="Create encoded-releases branch during install",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )

    args = parser.parse_args()

    try:
        setup = TransferHookSetup(args.repo, verbose=args.verbose)

        if args.action == "install":
            print("Installing transfer hook...")

            # Check requirements
            if not setup.check_requirements():
                sys.exit(1)

            # Install hook
            if not setup.install_hook(force=args.force):
                sys.exit(1)

            # Create branch if requested
            if args.create_branch:
                setup.create_encoded_releases_branch()

            # Create output directory
            output_dir = setup.repo_path / "encoded_releases"
            output_dir.mkdir(exist_ok=True)

            # Add to .gitignore
            gitignore_path = setup.repo_path / ".gitignore"
            if gitignore_path.exists():
                content = gitignore_path.read_text()
                if "encoded_releases/" not in content:
                    with open(gitignore_path, "a") as f:
                        f.write(
                            "\n# Transfer hook output\nencoded_releases/\n.skip-transfer-hook\n"
                        )
                    print("Updated .gitignore")

            print("\n✓ Transfer hook installed successfully!")
            print("\nThe hook will run automatically after each commit.")
            print("To disable temporarily, create a .skip-transfer-hook file")
            print("To test, run: python setup_transfer_hook.py test")

        elif args.action == "uninstall":
            print("Uninstalling transfer hook...")
            if setup.uninstall_hook():
                print("✓ Transfer hook uninstalled")
            else:
                sys.exit(1)

        elif args.action == "test":
            if setup.test_workflow():
                print("\n✓ All tests passed!")
            else:
                print("\n✗ Tests failed")
                sys.exit(1)

        elif args.action == "enable":
            setup.enable_hook()

        elif args.action == "disable":
            setup.disable_hook()

        elif args.action == "status":
            hook_path = setup.hooks_dir / "post-commit"
            disable_file = setup.repo_path / ".skip-transfer-hook"

            print("Transfer Hook Status:")
            print(f"  Installed: {'Yes' if hook_path.exists() else 'No'}")
            print(f"  Enabled: {'No (disabled)' if disable_file.exists() else 'Yes'}")

            if hook_path.exists():
                print(f"  Hook path: {hook_path}")
                print(f"  Log file: {setup.git_dir / 'hooks' / 'post-commit.log'}")

            # Check for encoded releases
            output_dir = setup.repo_path / "encoded_releases"
            if output_dir.exists():
                encoded_files = list(output_dir.glob("encoded_app_*.txt"))
                print(f"  Encoded releases: {len(encoded_files)} files")
                if encoded_files:
                    latest = max(encoded_files, key=lambda p: p.stat().st_mtime)
                    print(f"  Latest: {latest.name}")

    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
