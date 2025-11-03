#!/usr/bin/env python3
"""Fix reportUnusedCallResult warnings by adding _ = prefix where appropriate."""

import re
import subprocess
from typing import NamedTuple


class Warning(NamedTuple):
    """Represents a basedpyright warning."""
    filepath: str
    line_num: int
    return_type: str
    full_line: str


# Safe patterns that can be automatically fixed with _ =
SAFE_PATTERNS = [
    r"\.disconnect\(",  # Qt signal disconnects
    r"\.add_argument\(",  # Argparse actions
    r"\.mkdir\(",  # Path operations
    r"\.addAction\(",  # Qt menu actions
    r"QShortcut\(",  # Qt shortcuts
    r"\.pop\(",  # List pop operations (return value intentionally ignored)
    r"\.remove\(",  # List remove operations
    r"\.rmdir\(",  # Path rmdir
    r"\.unlink\(",  # Path unlink
    r"shutil\.copytree\(",  # Directory copy operations
    r"Path\([^)]+\)\.replace\(",  # Path.replace() - atomic file replacement
    r"gc\.collect\(",  # Garbage collection
    r"\.request_stop\(",  # Worker stop requests
    r"self\.terminate_process\(",  # Process termination
    r"_write_json_cache\(",  # Cache writes (errors logged internally)
    r"\.setEnabled\(",  # Qt widget state
    r"\.setVisible\(",  # Qt widget visibility
    r"\.setText\(",  # Qt widget text
    r"\.setStyleSheet\(",  # Qt styling
    r"\.setReadOnly\(",  # Qt widget read-only state
    r"\.setMaximum\(",  # Qt widget maximum value
    r"\.setMinimum\(",  # Qt widget minimum value
    r"\.setValue\(",  # Qt widget value
    r"\.setWindowTitle\(",  # Qt window title
    r"\.setIcon\(",  # Qt icon
]

# Patterns that need manual review (might need actual handling)
REVIEW_PATTERNS = [
    r"QMessageBox\.",  # Message boxes - might need button result
    r"\.exec\(",  # Dialog exec - might need accept/reject result
    r"_write_json_cache\(",  # Cache writes - errors logged internally
    r"\.write\(",  # File writes - might need to check bytes written
    r"\.wait\(",  # Process/thread waits - might need to check result
]


def get_warnings() -> list[Warning]:
    """Get all reportUnusedCallResult warnings from basedpyright."""
    import os
    uv_path = os.path.expanduser("~/.local/bin/uv")
    result = subprocess.run(
        [uv_path, "run", "basedpyright"],
        check=False, capture_output=True,
        text=True,
        shell=False
    )

    warnings = []
    pattern = r'(.+?):(\d+):\d+ - warning: Result of call expression is of type "(.+?)" and is not used'

    # Combine stdout and stderr
    output = result.stdout + result.stderr

    for line in output.split("\n"):
        if "reportUnusedCallResult" in line:
            match = re.search(pattern, line)
            if match:
                filepath = match.group(1).strip()
                line_num = int(match.group(2))
                return_type = match.group(3)
                warnings.append(Warning(filepath, line_num, return_type, line))

    return warnings


def read_source_line(filepath: str, line_num: int) -> str:
    """Read a specific line from a source file."""
    try:
        with open(filepath) as f:
            lines = f.readlines()
            if line_num <= len(lines):
                return lines[line_num - 1].rstrip()
    except Exception as e:
        print(f"Error reading {filepath}:{line_num}: {e}")
    return ""


def is_safe_pattern(source_line: str) -> bool:
    """Check if line matches a safe pattern for automatic fixing."""
    return any(re.search(pattern, source_line) for pattern in SAFE_PATTERNS)


def needs_review(source_line: str) -> str | None:
    """Check if line matches a pattern that needs manual review."""
    for pattern in REVIEW_PATTERNS:
        if re.search(pattern, source_line):
            return pattern
    return None


def fix_line(source_line: str) -> str:
    """Add _ = prefix to a line if not already present."""
    stripped = source_line.lstrip()
    indent = source_line[:len(source_line) - len(stripped)]

    # Don't add if already has assignment
    if "=" in stripped and not stripped.startswith("="):
        return source_line

    return f"{indent}_ = {stripped}"


def apply_fixes(warnings_to_fix: list[Warning]) -> dict[str, list[tuple[int, str, str]]]:
    """Group fixes by file and prepare changes."""
    fixes_by_file: dict[str, list[tuple[int, str, str]]] = {}

    for warning in warnings_to_fix:
        source_line = read_source_line(warning.filepath, warning.line_num)
        if source_line:
            fixed_line = fix_line(source_line)
            if fixed_line != source_line:
                if warning.filepath not in fixes_by_file:
                    fixes_by_file[warning.filepath] = []
                fixes_by_file[warning.filepath].append(
                    (warning.line_num, source_line, fixed_line)
                )

    return fixes_by_file


def main():
    """Main function to analyze and fix warnings."""
    print("Analyzing reportUnusedCallResult warnings...")
    warnings = get_warnings()
    print(f"Found {len(warnings)} warnings\n")

    # Categorize warnings
    safe_fixes = []
    needs_manual_review = []
    other = []

    for warning in warnings:
        source_line = read_source_line(warning.filepath, warning.line_num)

        if is_safe_pattern(source_line):
            safe_fixes.append((warning, source_line))
        elif review_pattern := needs_review(source_line):
            needs_manual_review.append((warning, source_line, review_pattern))
        else:
            other.append((warning, source_line))

    print("="*80)
    print("CATEGORIZATION SUMMARY")
    print("="*80)
    print(f"Safe to auto-fix: {len(safe_fixes)}")
    print(f"Needs manual review: {len(needs_manual_review)}")
    print(f"Other (needs analysis): {len(other)}")
    print()

    # Show safe fixes breakdown
    if safe_fixes:
        print("="*80)
        print("SAFE FIXES (will auto-apply _ = prefix)")
        print("="*80)
        pattern_counts: dict[str, int] = {}
        for warning, source_line in safe_fixes:
            for pattern in SAFE_PATTERNS:
                if re.search(pattern, source_line):
                    pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
                    break

        for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
            print(f"{count:3d} - {pattern}")
        print()

    # Show manual review cases
    if needs_manual_review:
        print("="*80)
        print("NEEDS MANUAL REVIEW")
        print("="*80)
        for warning, source_line, pattern in needs_manual_review[:20]:
            print(f"{warning.filepath}:{warning.line_num}")
            print(f"  Type: {warning.return_type}")
            print(f"  Pattern: {pattern}")
            print(f"  Code: {source_line.strip()}")
            print()
        if len(needs_manual_review) > 20:
            print(f"... and {len(needs_manual_review) - 20} more")
        print()

    # Show other cases
    if other:
        print("="*80)
        print("OTHER (needs pattern identification)")
        print("="*80)
        for warning, source_line in other[:20]:
            print(f"{warning.filepath}:{warning.line_num}")
            print(f"  Type: {warning.return_type}")
            print(f"  Code: {source_line.strip()}")
            print()
        if len(other) > 20:
            print(f"... and {len(other) - 20} more")
        print()

    # Ask for confirmation before applying
    if safe_fixes:
        print("="*80)
        response = input(f"Apply fixes to {len(safe_fixes)} safe cases? (yes/no): ")
        if response.lower() in ("yes", "y"):
            fixes_by_file = apply_fixes([w for w, _ in safe_fixes])

            for filepath, fixes in fixes_by_file.items():
                print(f"\nFixing {filepath}...")
                with open(filepath) as f:
                    lines = f.readlines()

                # Apply fixes in reverse order to maintain line numbers
                for line_num, old_line, new_line in sorted(fixes, reverse=True, key=lambda x: x[0]):
                    lines[line_num - 1] = new_line + "\n"

                with open(filepath, "w") as f:
                    f.writelines(lines)

                print(f"  Applied {len(fixes)} fixes")

            print(f"\nFixed {len(safe_fixes)} warnings in {len(fixes_by_file)} files")
            print("Run basedpyright again to see remaining warnings")
        else:
            print("Skipped applying fixes")


if __name__ == "__main__":
    main()
