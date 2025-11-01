#!/usr/bin/env python3
"""Bundle application files for base64 encoding.

This script collects all relevant application files (respecting .gitignore),
copies them to a temporary directory, and optionally encodes them using transfer_cli.py.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


class GitIgnoreParser:
    """Parse and apply .gitignore patterns."""

    def __init__(self, gitignore_path: Optional[str] = None):
        """Initialize with optional .gitignore file path."""
        self.patterns = []
        self.always_exclude = {
            "__pycache__",
            ".git",
            ".pytest_cache",
            "venv",
            "env",
            ".venv",
            ".env",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            ".DS_Store",
            "Thumbs.db",
            ".coverage",
            "htmlcov",
            ".hypothesis",
        }

        if gitignore_path and os.path.exists(gitignore_path):
            self._parse_gitignore(gitignore_path)

    def _parse_gitignore(self, gitignore_path: str):
        """Parse .gitignore file and extract patterns."""
        with open(gitignore_path, "r") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if line and not line.startswith("#"):
                    self.patterns.append(line)

    def should_exclude(self, path: str, is_dir: bool = False) -> bool:
        """Check if a path should be excluded based on patterns.

        Args:
            path: Relative path to check
            is_dir: Whether the path is a directory

        Returns:
            True if the path should be excluded
        """
        path_parts = Path(path).parts
        path_name = os.path.basename(path)

        # Check always exclude patterns
        for pattern in self.always_exclude:
            if pattern.startswith("*."):
                # File extension pattern
                if path.endswith(pattern[1:]):
                    return True
            elif pattern in path_parts or path_name == pattern:
                return True

        # Check gitignore patterns
        for pattern in self.patterns:
            # Simple pattern matching (not full gitignore spec)
            if pattern.endswith("/"):
                # Directory pattern
                if is_dir and (pattern[:-1] in path_parts or path_name == pattern[:-1]):
                    return True
            elif "*" in pattern:
                # Wildcard pattern
                regex_pattern = pattern.replace(".", r"\.").replace("*", ".*")
                if re.match(regex_pattern, path) or re.match(regex_pattern, path_name):
                    return True
            else:
                # Exact match or path contains pattern
                if pattern in path_parts or path_name == pattern or path == pattern:
                    return True

        return False


class ApplicationBundler:
    """Bundle application files for transfer."""

    def __init__(self, config_path: Optional[str] = None, verbose: bool = False):
        """Initialize the bundler.

        Args:
            config_path: Path to configuration file
            verbose: Enable verbose output
        """
        self.verbose = verbose
        self.config = self._load_config(config_path)
        self.gitignore_parser = GitIgnoreParser(".gitignore")

    def _load_config(self, config_path: Optional[str]) -> dict:
        """Load configuration from file or use defaults.

        Args:
            config_path: Path to configuration file

        Returns:
            Configuration dictionary
        """
        default_config = {
            "include_patterns": [
                "*.py",
                "*.json",
                "*.yml",
                "*.yaml",
                "*.md",
                "*.txt",
                "*.ini",
                "*.cfg",
                "requirements*.txt",
                "Dockerfile",
                ".dockerignore",
            ],
            "exclude_patterns": [
                "test_*.py",
                "*_test.py",
                "tests/",
                "Transfer.py",
                "transfer_cli.py",
                "bundle_app.py",
                "setup_transfer_hook.py",
                "*.log",
                "*.tmp",
                "*.bak",
                "encoded_app_*.txt",
            ],
            "exclude_dirs": [
                "tests",
                "test",
                "__pycache__",
                ".git",
                ".pytest_cache",
                "venv",
                "env",
                ".venv",
                "archive",
                "archived",
                "copy",
                ".shotbot",
            ],
            "max_file_size_mb": 10,
            "chunk_size_kb": 5120,  # 5MB chunks
            "output_dir": "encoded_releases",
        }

        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
                    if self.verbose:
                        print(f"Loaded config from {config_path}", file=sys.stderr)
            except Exception as e:
                print(
                    f"Warning: Failed to load config from {config_path}: {e}",
                    file=sys.stderr,
                )

        return default_config

    def should_include_file(self, file_path: str) -> bool:
        """Check if a file should be included in the bundle.

        Args:
            file_path: Relative path to the file

        Returns:
            True if file should be included
        """
        # Check gitignore patterns first
        if self.gitignore_parser.should_exclude(file_path):
            return False

        file_name = os.path.basename(file_path)

        # Check exclude patterns from config
        for pattern in self.config["exclude_patterns"]:
            if "*" in pattern:
                regex_pattern = pattern.replace(".", r"\.").replace("*", ".*")
                if re.match(regex_pattern, file_path) or re.match(
                    regex_pattern, file_name
                ):
                    return False
            elif pattern in file_path or file_name == pattern:
                return False

        # Check include patterns
        for pattern in self.config["include_patterns"]:
            if "*" in pattern:
                regex_pattern = pattern.replace(".", r"\.").replace("*", ".*")
                if re.match(regex_pattern, file_path) or re.match(
                    regex_pattern, file_name
                ):
                    return True
            elif file_name == pattern:
                return True

        return False

    def collect_files(self, source_dir: str = ".") -> List[Tuple[str, str]]:
        """Collect all files to be bundled.

        Args:
            source_dir: Source directory to scan

        Returns:
            List of (source_path, relative_path) tuples
        """
        files_to_bundle = []
        source_dir = os.path.abspath(source_dir)
        max_size_bytes = self.config["max_file_size_mb"] * 1024 * 1024

        for root, dirs, files in os.walk(source_dir):
            # Filter out excluded directories
            dirs[:] = [
                d
                for d in dirs
                if d not in self.config["exclude_dirs"]
                and not self.gitignore_parser.should_exclude(d, is_dir=True)
            ]

            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, source_dir)

                # Skip files that are too large
                try:
                    if os.path.getsize(file_path) > max_size_bytes:
                        if self.verbose:
                            size_mb = os.path.getsize(file_path) / (1024 * 1024)
                            print(
                                f"Skipping large file ({size_mb:.1f}MB): {relative_path}",
                                file=sys.stderr,
                            )
                        continue
                except OSError:
                    continue

                if self.should_include_file(relative_path):
                    files_to_bundle.append((file_path, relative_path))

        return files_to_bundle

    def create_bundle(self, output_dir: Optional[str] = None) -> str:
        """Create a bundle of application files.

        Args:
            output_dir: Optional output directory (uses temp dir if not specified)

        Returns:
            Path to the bundle directory
        """
        # Collect files
        files_to_bundle = self.collect_files()

        if not files_to_bundle:
            raise ValueError("No files found to bundle")

        if self.verbose:
            print(f"Found {len(files_to_bundle)} files to bundle", file=sys.stderr)

        # Create output directory
        if output_dir:
            bundle_dir = output_dir
            os.makedirs(bundle_dir, exist_ok=True)
        else:
            bundle_dir = tempfile.mkdtemp(prefix="shotbot_bundle_")

        # Copy files to bundle directory
        for source_path, relative_path in files_to_bundle:
            dest_path = os.path.join(bundle_dir, relative_path)
            dest_dir = os.path.dirname(dest_path)

            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(source_path, dest_path)

            if self.verbose:
                print(f"Bundled: {relative_path}", file=sys.stderr)

        # Create bundle metadata
        metadata = {
            "created": datetime.now().isoformat(),
            "files_count": len(files_to_bundle),
            "files": [rel_path for _, rel_path in files_to_bundle],
            "source_dir": os.getcwd(),
        }

        metadata_path = os.path.join(bundle_dir, ".bundle_metadata.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return bundle_dir

    def encode_bundle(self, bundle_dir: str, output_file: Optional[str] = None) -> str:
        """Encode the bundle using transfer_cli.py.

        Args:
            bundle_dir: Path to the bundle directory
            output_file: Optional output file path

        Returns:
            Path to the encoded file
        """
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"encoded_app_{timestamp}.txt"

        # Build transfer_cli command
        transfer_cli_path = os.path.join(os.path.dirname(__file__), "transfer_cli.py")

        if not os.path.exists(transfer_cli_path):
            raise FileNotFoundError(f"transfer_cli.py not found at {transfer_cli_path}")

        cmd = [
            sys.executable,
            transfer_cli_path,
            bundle_dir,
            "-o",
            output_file,
            "-c",
            str(self.config["chunk_size_kb"]),
            "--single-file",
            "--metadata",
        ]

        if self.verbose:
            cmd.append("-v")
            print(f"Running: {' '.join(cmd)}", file=sys.stderr)

        # Run transfer_cli
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"transfer_cli.py failed: {result.stderr}")

        if self.verbose and result.stderr:
            print(result.stderr, file=sys.stderr)

        return output_file


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Bundle application files for base64 encoding"
    )
    parser.add_argument(
        "-c", "--config", help="Configuration file path", default="transfer_config.json"
    )
    parser.add_argument(
        "-o", "--output", help="Output file for encoded bundle", default=None
    )
    parser.add_argument(
        "--bundle-dir",
        help="Directory to create bundle in (temp dir if not specified)",
        default=None,
    )
    parser.add_argument(
        "--keep-bundle",
        action="store_true",
        help="Keep the bundle directory after encoding",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    parser.add_argument(
        "--list-files",
        action="store_true",
        help="List files that would be bundled without creating bundle",
    )

    args = parser.parse_args()

    try:
        # Create bundler
        bundler = ApplicationBundler(
            config_path=args.config if os.path.exists(args.config) else None,
            verbose=args.verbose,
        )

        # List files mode
        if args.list_files:
            files = bundler.collect_files()
            print(f"Found {len(files)} files to bundle:")
            for source_path, relative_path in sorted(files, key=lambda x: x[1]):
                size_kb = os.path.getsize(source_path) / 1024
                print(f"  {relative_path} ({size_kb:.1f} KB)")
            sys.exit(0)

        # Create bundle
        if args.verbose:
            print("Creating application bundle...", file=sys.stderr)

        bundle_dir = bundler.create_bundle(args.bundle_dir)

        if args.verbose:
            print(f"Bundle created at: {bundle_dir}", file=sys.stderr)

        # Encode bundle
        if args.verbose:
            print("Encoding bundle...", file=sys.stderr)

        output_file = bundler.encode_bundle(bundle_dir, args.output)

        print(f"Encoded bundle saved to: {output_file}")

        # Clean up bundle directory if not keeping it
        if not args.keep_bundle and not args.bundle_dir:
            shutil.rmtree(bundle_dir)
            if args.verbose:
                print(f"Cleaned up bundle directory: {bundle_dir}", file=sys.stderr)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
