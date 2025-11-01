#!/usr/bin/env python3
"""Analyze mock usage to determine if it's truly minimal and necessary."""

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

# Categories of mock targets with necessity assessment
MOCK_CATEGORIES = {
    "NECESSARY_GUI": {
        "patterns": [
            r"QMessageBox",
            r"QFileDialog",
            r"QInputDialog",
            r"QDesktopServices",
            r"QApplication\.clipboard",
            r"QTimer\.singleShot",
        ],
        "reason": "GUI components require mocking to avoid actual UI interactions",
    },
    "NECESSARY_SUBPROCESS": {
        "patterns": [
            r"subprocess\.run",
            r"subprocess\.Popen",
            r"subprocess\.check_output",
            r"os\.system",
            r"os\.popen",
        ],
        "reason": "External process calls should be mocked for test isolation",
    },
    "NECESSARY_FILE_IO": {
        "patterns": [
            r"@patch\(['\"].*\.open",
            r"@patch\(['\"]builtins\.open",
            r"mock_open",
            r"pathlib\.Path\.exists",
            r"pathlib\.Path\.is_file",
        ],
        "reason": "File I/O should be mocked to avoid filesystem dependencies",
    },
    "NECESSARY_NETWORK": {
        "patterns": [r"requests\.", r"urllib\.", r"http\.client", r"socket\."],
        "reason": "Network operations must be mocked for offline testing",
    },
    "QUESTIONABLE_QT_INTERNALS": {
        "patterns": [r"QImage", r"QPixmap", r"QPainter", r"QFont", r"QColor"],
        "reason": "Qt drawing primitives might be testable without mocking",
    },
    "QUESTIONABLE_INTERNAL_METHODS": {
        "patterns": [
            r"Mock\(\)\s*#.*internal",
            r"self\._\w+\s*=\s*Mock",
            r"window\._\w+\s*=\s*Mock",
            r"manager\._\w+\s*=\s*Mock",
        ],
        "reason": "Internal method mocking may indicate poor test boundaries",
    },
    "EXCESSIVE_DATA_CLASSES": {
        "patterns": [
            r"Mock\(\)\s*#.*data",
            r"Mock\(spec=.*Model\)",
            r"Mock\(\).*\.to_dict",
            r"Mock\(\).*\.from_dict",
        ],
        "reason": "Data classes should use real instances, not mocks",
    },
    "EXCESSIVE_SIMPLE_RETURNS": {
        "patterns": [
            r"Mock\(return_value=True\)",
            r"Mock\(return_value=False\)",
            r"Mock\(return_value=None\)",
            r"Mock\(return_value=\[\]\)",
            r"Mock\(return_value=\"\"\)",
        ],
        "reason": "Simple return values might indicate over-mocking",
    },
}


def analyze_mock_line(line: str) -> Tuple[str, bool]:
    """Analyze a line containing mock usage and categorize it."""
    for category, info in MOCK_CATEGORIES.items():
        for pattern in info["patterns"]:
            if re.search(pattern, line):
                is_necessary = category.startswith("NECESSARY_")
                return category, is_necessary
    return "UNCATEGORIZED", False


def analyze_file(file_path: Path) -> Dict[str, List[str]]:
    """Analyze mock usage in a single file."""
    results = defaultdict(list)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            if any(keyword in line for keyword in ["Mock", "patch", "monkeypatch"]):
                category, is_necessary = analyze_mock_line(line)
                results[category].append(f"  Line {i}: {line.strip()}")
    except Exception as e:
        print(f"Error analyzing {file_path}: {e}")

    return results


def main():
    """Analyze all test files for mock necessity."""
    test_dir = Path("/mnt/c/CustomScripts/Python/PyFFMPEG/BB/shotbot/tests")

    # Find all test files
    test_files = list(test_dir.rglob("test_*.py"))

    print("=" * 80)
    print("MOCK USAGE NECESSITY ANALYSIS")
    print("=" * 80)

    category_totals = defaultdict(int)
    file_details = defaultdict(lambda: defaultdict(list))

    # Analyze each file
    for test_file in test_files:
        results = analyze_file(test_file)
        relative_path = test_file.relative_to(test_dir)

        for category, instances in results.items():
            if instances:
                category_totals[category] += len(instances)
                file_details[category][str(relative_path)].extend(instances)

    # Calculate statistics
    necessary_count = sum(
        count for cat, count in category_totals.items() if cat.startswith("NECESSARY_")
    )
    questionable_count = sum(
        count
        for cat, count in category_totals.items()
        if cat.startswith("QUESTIONABLE_")
    )
    excessive_count = sum(
        count for cat, count in category_totals.items() if cat.startswith("EXCESSIVE_")
    )
    uncategorized_count = category_totals.get("UNCATEGORIZED", 0)

    total_count = sum(category_totals.values())

    # Print summary
    print("\n=== MOCK NECESSITY SUMMARY ===")
    print(f"Total mock usages analyzed: {total_count}")
    print(
        f"  Necessary:     {necessary_count:4d} ({necessary_count / total_count * 100:.1f}%)"
    )
    print(
        f"  Questionable:  {questionable_count:4d} ({questionable_count / total_count * 100:.1f}%)"
    )
    print(
        f"  Excessive:     {excessive_count:4d} ({excessive_count / total_count * 100:.1f}%)"
    )
    print(
        f"  Uncategorized: {uncategorized_count:4d} ({uncategorized_count / total_count * 100:.1f}%)"
    )

    # Print category breakdown
    print("\n=== CATEGORY BREAKDOWN ===")
    for category in sorted(MOCK_CATEGORIES.keys()):
        count = category_totals.get(category, 0)
        if count > 0:
            info = MOCK_CATEGORIES[category]
            status = (
                "✓"
                if category.startswith("NECESSARY_")
                else "?"
                if category.startswith("QUESTIONABLE_")
                else "✗"
            )
            print(f"\n{status} {category}: {count} instances")
            print(f"  Reason: {info['reason']}")

            # Show top 3 files for this category
            files_for_category = file_details[category]
            if files_for_category:
                print("  Top files:")
                for file, instances in sorted(
                    files_for_category.items(), key=lambda x: len(x[1]), reverse=True
                )[:3]:
                    print(f"    - {file}: {len(instances)} instances")

    # Identify files with highest excessive mocking
    print("\n=== FILES WITH MOST EXCESSIVE/QUESTIONABLE MOCKING ===")
    excessive_by_file = defaultdict(int)

    for category in [
        "QUESTIONABLE_QT_INTERNALS",
        "QUESTIONABLE_INTERNAL_METHODS",
        "EXCESSIVE_DATA_CLASSES",
        "EXCESSIVE_SIMPLE_RETURNS",
    ]:
        for file, instances in file_details[category].items():
            excessive_by_file[file] += len(instances)

    for file, count in sorted(
        excessive_by_file.items(), key=lambda x: x[1], reverse=True
    )[:10]:
        print(f"  {count:3d} - {file}")

    # Print recommendations
    print("\n=== RECOMMENDATIONS ===")
    reduction_potential = questionable_count + excessive_count
    reduction_percentage = (
        reduction_potential / total_count * 100 if total_count > 0 else 0
    )

    print(
        f"Potential mock reduction: {reduction_potential} instances ({reduction_percentage:.1f}%)"
    )
    print("\nPriority refactoring targets:")

    if category_totals.get("EXCESSIVE_SIMPLE_RETURNS", 0) > 0:
        print("1. Replace Mock(return_value=simple) with actual test data")

    if category_totals.get("EXCESSIVE_DATA_CLASSES", 0) > 0:
        print("2. Use real data class instances instead of mocks")

    if category_totals.get("QUESTIONABLE_INTERNAL_METHODS", 0) > 0:
        print("3. Test public interfaces instead of mocking internal methods")

    if category_totals.get("QUESTIONABLE_QT_INTERNALS", 0) > 0:
        print("4. Consider using real Qt objects (QImage, QColor) in tests")

    # Final verdict
    print("\n=== VERDICT ===")
    if reduction_percentage > 30:
        print(
            f"❌ EXCESSIVE MOCKING DETECTED: {reduction_percentage:.1f}% could be reduced"
        )
        print("   The test suite has significant room for mock reduction.")
    elif reduction_percentage > 15:
        print(f"⚠️  MODERATE MOCKING: {reduction_percentage:.1f}% could be reduced")
        print("   The test suite could benefit from some mock reduction.")
    else:
        print(f"✅ MINIMAL MOCKING: Only {reduction_percentage:.1f}% questionable")
        print("   The test suite appears to have reasonably minimal mocking.")


if __name__ == "__main__":
    main()
