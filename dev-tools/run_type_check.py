#!/usr/bin/env python3
"""Run comprehensive type checking and linting for shotbot."""

# Standard library imports
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and return success status."""
    print(f"\n{'=' * 60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print("=" * 60)

    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=300)

        if result.stdout:
            print("STDOUT:")
            print(result.stdout)

        if result.stderr:
            print("STDERR:")
            print(result.stderr)

        success = result.returncode == 0
        print(f"Exit code: {result.returncode} ({'SUCCESS' if success else 'FAILED'})")
        return success

    except subprocess.TimeoutExpired:
        print("ERROR: Command timed out after 5 minutes")
        return False
    except Exception as e:
        print(f"ERROR: Failed to run command: {e}")
        return False


def main() -> int:
    """Run type checking and linting."""

    # Ensure we're in the right directory
    script_dir = Path(__file__).parent
    if script_dir != Path.cwd():
        print(f"Changing directory to {script_dir}")
        # Standard library imports
        import os

        os.chdir(script_dir)

    results = []

    # 1. Run ruff formatting
    results.append(
        run_command(
            ["python3", "-m", "ruff", "format", "--check", "."], "Ruff formatting check"
        )
    )

    # 2. Run ruff linting with type-checking rules
    results.append(
        run_command(
            ["python3", "-m", "ruff", "check", "--select", "UP,TCH,ANN", "."],
            "Ruff type-checking rules (UP, TCH, ANN)",
        )
    )

    # 3. Run basedpyright on key files
    key_files = [
        "base_shot_model.py",
        "shot_model.py",
        "cache_manager.py",
        "main_window.py",
        "protocols.py",
        "shotbot_types.py",
        "type_definitions.py",
    ]

    results.extend(
        run_command(
            ["python3", "-m", "basedpyright", file], f"Type checking {file}"
        )
        for file in key_files
        if Path(file).exists()
    )

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)

    passed = sum(results)
    total = len(results)

    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("🎉 All type checking passed!")
        return 0
    print("❌ Some checks failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
