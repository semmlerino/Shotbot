#!/usr/bin/env python3
"""
Automated test anti-pattern checker for UNIFIED_TESTING_GUIDE compliance.

This script checks for common anti-patterns in test files:
- time.sleep() usage instead of proper synchronization
- assert_called patterns instead of behavior verification
- Mock(spec=) instead of test doubles
- QPixmap usage in worker threads
- Missing qtbot.addWidget() for widgets
- Negative indexing with QSignalSpy

Usage:
    python check_test_antipatterns.py [path]

If no path is provided, checks the tests/ directory.
"""

# Standard library imports
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, TypedDict


class PatternConfig(TypedDict):
    """Type for pattern configuration dictionary."""

    regex: str
    suggestion: str
    exclude_files: list[str]


@dataclass
class AntiPattern:
    """Represents a detected anti-pattern."""

    file_path: Path
    line_number: int
    pattern_type: str
    line_content: str
    suggestion: str


class TestAntiPatternChecker:
    """Check test files for anti-patterns defined in UNIFIED_TESTING_GUIDE."""

    # Define patterns to check
    PATTERNS: ClassVar[dict[str, PatternConfig]] = {
        "time.sleep": {
            "regex": r"time\.sleep\s*\(",
            "suggestion": "Use qtbot.wait(), qtbot.waitUntil(), or mock datetime for time control",
            "exclude_files": ["helpers/synchronization.py", "test_doubles_library.py"],
        },
        "assert_called": {
            "regex": r"assert_called(?:_once|_with|_once_with)\s*\(",
            "suggestion": "Test behavior outcomes, not implementation details (mock calls)",
            "exclude_files": [],
        },
        "mock_spec": {
            "regex": r"Mock\s*\(\s*spec\s*=",
            "suggestion": "Use test doubles from test_doubles_library.py instead of Mock(spec=)",
            "exclude_files": [],
        },
        "qpixmap_thread": {
            "regex": r"QPixmap.*thread|pixmap.*Thread",
            "suggestion": "Use ThreadSafeTestImage or QImage in worker threads, never QPixmap",
            "exclude_files": [
                "test_helpers.py",
                "test_doubles_library.py",
            ],  # Documentation is OK
        },
        "spy_negative_index": {
            "regex": r"spy\.at\s*\(\s*-",
            "suggestion": "Use spy.at(spy.count() - 1) instead of negative indexing",
            "exclude_files": [],
        },
        "if_layout": {
            "regex": r"if\s+self\.layout\s*:",
            "suggestion": "Use 'if self.layout is not None:' as Qt containers are falsy when empty",
            "exclude_files": [],
        },
    }

    def __init__(self, root_path: Path = Path("tests")) -> None:
        """Initialize the checker with a root path."""
        self.root_path = root_path
        self.anti_patterns: list[AntiPattern] = []

    def check_file(self, file_path: Path) -> list[AntiPattern]:
        """Check a single file for anti-patterns."""
        patterns = []

        # Skip non-Python files
        if file_path.suffix != ".py":
            return patterns

        # Skip certain files that are allowed to have patterns

        try:
            with file_path.open(encoding="utf-8") as f:
                lines = f.readlines()

            for line_num, line in enumerate(lines, start=1):
                for pattern_name, pattern_config in self.PATTERNS.items():
                    # Skip if file is in exclude list
                    if any(
                        exclude in str(file_path)
                        for exclude in pattern_config["exclude_files"]
                    ):
                        continue

                    # Check if pattern matches
                    if re.search(pattern_config["regex"], line):
                        # Check for valid exceptions (comments explaining why it's OK)
                        if "# Following UNIFIED_TESTING_GUIDE" in line:
                            continue
                        if "# OK: " in line or "# ALLOWED: " in line:
                            continue

                        patterns.append(
                            AntiPattern(
                                file_path=file_path,
                                line_number=line_num,
                                pattern_type=pattern_name,
                                line_content=line.strip(),
                                suggestion=pattern_config["suggestion"],
                            )
                        )

        except Exception as e:
            print(f"Error reading {file_path}: {e}", file=sys.stderr)

        return patterns

    def check_missing_qtbot_addwidget(self, file_path: Path) -> list[AntiPattern]:
        """Check for widgets created without qtbot.addWidget()."""
        patterns = []

        if file_path.suffix != ".py" or "test" not in file_path.name:
            return patterns

        try:
            with file_path.open(encoding="utf-8") as f:
                content = f.read()

            # Find widget creations
            widget_creations = re.finditer(
                r"(\w+)\s*=\s*(?:MainWindow|QWidget|QDialog|ThumbnailWidget|LauncherPanel|ShotInfoPanel)\s*\(",
                content,
            )

            for match in widget_creations:
                var_name = match.group(1)
                # Check if qtbot.addWidget() is called for this widget
                if not re.search(rf"qtbot\.addWidget\s*\(\s*{var_name}\s*\)", content):
                    # Find line number
                    lines_before = content[: match.start()].count("\n")
                    patterns.append(
                        AntiPattern(
                            file_path=file_path,
                            line_number=lines_before + 1,
                            pattern_type="missing_qtbot_addwidget",
                            line_content=match.group(0),
                            suggestion=f"Add 'qtbot.addWidget({var_name})' after creating the widget",
                        )
                    )

        except Exception as e:
            print(
                f"Error checking qtbot.addWidget in {file_path}: {e}", file=sys.stderr
            )

        return patterns

    def check_directory(self, directory: Path | None = None) -> list[AntiPattern]:
        """Check all test files in a directory."""
        if directory is None:
            directory = self.root_path

        all_patterns = []

        # Find all Python test files
        test_files = directory.rglob("test_*.py") if directory.is_dir() else [directory]

        for file_path in test_files:
            # Check standard anti-patterns
            patterns = self.check_file(file_path)
            all_patterns.extend(patterns)

            # Check for missing qtbot.addWidget
            widget_patterns = self.check_missing_qtbot_addwidget(file_path)
            all_patterns.extend(widget_patterns)

        return all_patterns

    def print_report(self, patterns: list[AntiPattern]) -> None:
        """Print a formatted report of found anti-patterns."""
        if not patterns:
            print(
                "✅ No anti-patterns found! Tests follow UNIFIED_TESTING_GUIDE best practices."
            )
            return

        # Group by pattern type
        grouped: dict[str, list[AntiPattern]] = {}
        for pattern in patterns:
            if pattern.pattern_type not in grouped:
                grouped[pattern.pattern_type] = []
            grouped[pattern.pattern_type].append(pattern)

        print(
            f"❌ Found {len(patterns)} anti-patterns in {len({p.file_path for p in patterns})} files\n"
        )

        for pattern_type, items in grouped.items():
            print(
                f"\n📋 {pattern_type.replace('_', ' ').title()} ({len(items)} occurrences)"
            )
            print("-" * 80)

            for item in items[:10]:  # Show first 10 of each type
                try:
                    rel_path = item.file_path.relative_to(Path.cwd())
                except ValueError:
                    # If not relative to cwd, just use the path as is
                    rel_path = item.file_path
                print(f"  {rel_path}:{item.line_number}")
                print(f"    Line: {item.line_content[:80]}")
                print(f"    Fix: {item.suggestion}")
                print()

            if len(items) > 10:
                print(f"  ... and {len(items) - 10} more\n")

    def generate_pre_commit_config(self) -> str:
        """Generate a pre-commit hook configuration."""
        return """# .pre-commit-config.yaml
# Add this to your pre-commit configuration

repos:
  - repo: local
    hooks:
      - id: check-test-antipatterns
        name: Check test anti-patterns
        entry: python check_test_antipatterns.py
        language: system
        files: ^tests/.*\\.py$
        pass_filenames: true
"""


def main() -> None:
    """Main entry point."""
    # Parse arguments
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests")

    if not path.exists():
        print(f"Error: Path {path} does not exist", file=sys.stderr)
        sys.exit(1)

    # Run checker
    checker = TestAntiPatternChecker()
    patterns = checker.check_directory(path)

    # Print report
    checker.print_report(patterns)

    # Exit with error if patterns found (for CI)
    if patterns:
        print(
            "\n💡 To add this as a pre-commit hook, add the following to .pre-commit-config.yaml:"
        )
        print(checker.generate_pre_commit_config())
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
