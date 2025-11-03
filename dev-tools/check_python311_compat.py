#!/usr/bin/env python3
"""Comprehensive Python 3.11 compatibility checker."""

# Standard library imports
import ast
import sys
from pathlib import Path


def check_file_syntax(filepath: Path) -> list[str]:
    """Check a Python file for Python 3.11 compatibility issues."""
    issues = []

    try:
        with filepath.open(encoding="utf-8") as f:
            content = f.read()

        # Parse the AST
        tree = ast.parse(content, str(filepath))

        # Check for specific patterns
        for node in ast.walk(tree):
            # Check for type parameter syntax (PEP 695) - Python 3.12+
            if hasattr(ast, "TypeAlias") and isinstance(
                node, getattr(ast, "TypeAlias", type)
            ):
                issues.append(
                    f"Type parameter syntax (PEP 695) used at line {getattr(node, 'lineno', 0)}"
                )

            # Check for improved f-strings (PEP 701) - Python 3.12+
            if isinstance(node, ast.JoinedStr):
                issues.extend(
                    f"Nested f-string at line {node.lineno} (Python 3.12+)"
                    for value in node.values
                    if (
                        isinstance(value, ast.FormattedValue)
                        and hasattr(value, "format_spec")
                        and value.format_spec
                        and isinstance(value.format_spec, ast.JoinedStr)
                    )
                )

        # Check imports
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "typing":
                # Check for Python 3.12+ only imports from typing
                issues.extend(
                    f"Line {node.lineno}: 'override' imported from typing (Python 3.12+ only)"
                    for alias in node.names
                    if alias.name == "override"
                )

    except SyntaxError as e:
        issues.append(f"Syntax error: {e}")
    except Exception as e:
        issues.append(f"Error checking file: {e}")

    return issues


def main() -> int:
    """Check all Python files in the project."""
    # Get all Python files, excluding venv and test_venv
    python_files = [
        path
        for pattern in ["*.py", "**/*.py"]
        for path in Path().glob(pattern)
        if "venv" not in str(path) and "test_venv" not in str(path)
    ]

    print(f"Checking {len(python_files)} Python files for Python 3.11 compatibility...")
    print()

    all_issues = []
    for filepath in sorted(python_files):
        issues = check_file_syntax(filepath)
        if issues:
            all_issues.append((filepath, issues))

    if all_issues:
        print("❌ Compatibility issues found:")
        for filepath, issues in all_issues:
            print(f"\n{filepath}:")
            for issue in issues:
                print(f"  - {issue}")
    else:
        print("✅ All files are Python 3.11 compatible!")

    # Also check for match/case usage (Python 3.10+, so compatible with 3.11)
    print("\n📝 Files using match/case (Python 3.10+, compatible with 3.11):")
    for filepath in sorted(python_files):
        try:
            with filepath.open() as f:
                content = f.read()
                if "match " in content and "case " in content:
                    print(f"  - {filepath}")
        except (OSError, UnicodeDecodeError):
            pass

    return 0 if not all_issues else 1


if __name__ == "__main__":
    sys.exit(main())
