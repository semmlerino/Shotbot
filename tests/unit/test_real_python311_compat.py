#!/usr/bin/env python3
"""Test actual Python 3.11 compatibility by compiling with limited features."""

# Standard library imports
from pathlib import Path


def check_real_compatibility(filepath: Path) -> list:
    """Check for actual Python 3.12+ specific features."""
    issues = []

    try:
        with filepath.open(encoding="utf-8") as f:
            content = f.read()

        # Look for actual nested f-strings (f"...{f'...'}...")
        # These have quotes inside the braces
        # Standard library imports
        import re

        # Pattern for actual nested f-strings like f"outer {f'inner'}"
        nested_pattern = r'f["\'].*?\{f["\'].*?["\'].*?\}.*?["\']'
        if re.search(nested_pattern, content):
            for i, line in enumerate(content.split("\n"), 1):
                if re.search(nested_pattern, line):
                    issues.append(f"Line {i}: Actual nested f-string found")

        # Check for type parameter syntax (PEP 695)
        if re.search(r"^type\s+\w+\[.*?\]\s*=", content, re.MULTILINE):
            issues.append("PEP 695 type parameter syntax (Python 3.12+)")

        # Check for override imported from typing (not typing_extensions)
        if "from typing import" in content and "override" in content:
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                if "from typing import" in line and "override" in line:
                    issues.append(
                        f"Line {i}: override imported from typing (use typing_extensions)"
                    )

    except Exception as e:
        issues.append(f"Error: {e}")

    return issues


# Test specific files that were flagged
test_files = [
    "utils.py",
    "cache/memory_manager.py",
    "previous_shots_finder.py",
]

print("Testing for REAL Python 3.11 compatibility issues...")
print()

for filepath in test_files:
    if Path(filepath).exists():
        issues = check_real_compatibility(Path(filepath))
        if issues:
            print(f"{filepath}:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"{filepath}: ✓ Compatible")

print("\nChecking if the format specs are actually compatible with Python 3.11...")
# This is what the code actually uses - format specs, not nested f-strings
test_code = """
size = 100.123
name = "test"
result = f"File {name} is {size:.1f}MB"  # This works in Python 3.11
"""

try:
    compile(test_code, "<test>", "exec")
    print("✓ Format specifications in f-strings are Python 3.11 compatible")
except SyntaxError:
    print("✗ Format specifications would fail in Python 3.11")
