#!/usr/bin/env python3
"""Fix remaining reportUnusedCallResult warnings by analyzing context."""

import os
import re
import subprocess
from pathlib import Path


def get_warnings():
    """Get all remaining reportUnusedCallResult warnings."""
    uv_path = os.path.expanduser("~/.local/bin/uv")
    result = subprocess.run(
        [uv_path, "run", "basedpyright"],
        check=False, capture_output=True,
        text=True,
        shell=False
    )

    warnings = []
    pattern = r'(.+?):(\d+):\d+ - warning: Result of call expression is of type "(.+?)" and is not used'

    output = result.stdout + result.stderr
    for line in output.split("\n"):
        if "reportUnusedCallResult" in line:
            match = re.search(pattern, line)
            if match:
                filepath = match.group(1).strip()
                line_num = int(match.group(2))
                return_type = match.group(3)
                warnings.append((filepath, line_num, return_type))

    return warnings


def fix_file(filepath, line_numbers):
    """Add _ = prefix to specified lines in a file."""
    with open(filepath) as f:
        lines = f.readlines()

    fixed_count = 0
    for line_num in sorted(line_numbers, reverse=True):
        if line_num <= len(lines):
            line = lines[line_num - 1]
            stripped = line.lstrip()
            indent = line[:len(line) - len(stripped)]

            # Don't add if already has assignment (shouldn't happen but be safe)
            if "=" in stripped and not stripped.startswith("="):
                continue

            lines[line_num - 1] = f"{indent}_ = {stripped}"
            fixed_count += 1

    with open(filepath, "w") as f:
        f.writelines(lines)

    return fixed_count


def main():
    """Main function."""
    warnings = get_warnings()
    print(f"Found {len(warnings)} warnings\n")

    # Group by file
    by_file = {}
    for filepath, line_num, return_type in warnings:
        if filepath not in by_file:
            by_file[filepath] = []
        by_file[filepath].append(line_num)

    # Fix all files
    total_fixed = 0
    for filepath, line_nums in sorted(by_file.items()):
        fixed = fix_file(filepath, line_nums)
        print(f"Fixed {fixed} warnings in {Path(filepath).name}")
        total_fixed += fixed

    print(f"\nTotal: Fixed {total_fixed} warnings in {len(by_file)} files")
    print("Run basedpyright to verify.")


if __name__ == "__main__":
    main()
