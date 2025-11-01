#!/usr/bin/env python3
"""Count mock usage across test files with detailed analysis."""

import re
from collections import defaultdict
from pathlib import Path


def count_mocks(file_path):
    """Count mock occurrences in a Python file."""
    patterns = {
        "Mock()": r"\bMock\s*\(",
        "MagicMock()": r"\bMagicMock\s*\(",
        "@patch": r"@patch",
        "monkeypatch.setattr": r"monkeypatch\.setattr",
        "mock.": r"\bmock\.",
        "spec=": r"\bspec\s*=",
        "spec_set=": r"\bspec_set\s*=",
    }

    counts = defaultdict(int)
    total = 0

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        for pattern_name, pattern in patterns.items():
            matches = re.findall(pattern, content)
            count = len(matches)
            if count > 0:
                counts[pattern_name] = count
                total += count

    except Exception as e:
        print(f"Error reading {file_path}: {e}")

    return total, counts


def main():
    """Main function to count mocks across all test files."""
    test_dir = Path("/mnt/c/CustomScripts/Python/PyFFMPEG/BB/shotbot/tests")

    all_files = list(test_dir.rglob("*.py"))
    test_files = [f for f in all_files if f.name.startswith("test_")]

    print(f"Found {len(test_files)} test files\n")

    file_stats = []
    total_mocks = 0
    pattern_totals = defaultdict(int)

    for test_file in test_files:
        count, patterns = count_mocks(test_file)
        if count > 0:
            relative_path = test_file.relative_to(test_dir)
            file_stats.append((count, str(relative_path), patterns))
            total_mocks += count
            for pattern, pcount in patterns.items():
                pattern_totals[pattern] += pcount

    # Sort by mock count
    file_stats.sort(reverse=True)

    print("=== Top 15 Files by Mock Usage ===")
    for count, filepath, patterns in file_stats[:15]:
        print(f"{count:4d} mocks - {filepath}")

    print("\n=== Mock Pattern Distribution ===")
    for pattern, count in sorted(
        pattern_totals.items(), key=lambda x: x[1], reverse=True
    ):
        print(f"{pattern:20s}: {count:4d}")

    print("\n=== Summary Statistics ===")
    print(f"Total test files analyzed: {len(test_files)}")
    print(f"Files with mocks: {len(file_stats)}")
    print(f"Total mock occurrences: {total_mocks}")
    print(
        f"Average mocks per file: {total_mocks / len(test_files) if test_files else 0:.1f}"
    )

    # Separate by directory
    unit_files = [f for f in test_files if "unit" in str(f)]
    integration_files = [f for f in test_files if "integration" in str(f)]

    unit_mocks = sum(count_mocks(f)[0] for f in unit_files)
    integration_mocks = sum(count_mocks(f)[0] for f in integration_files)

    print("\n=== Distribution by Test Type ===")
    print(f"Unit tests: {len(unit_files)} files, {unit_mocks} mocks")
    print(
        f"Integration tests: {len(integration_files)} files, {integration_mocks} mocks"
    )
    if unit_files:
        print(f"Avg mocks per unit test: {unit_mocks / len(unit_files):.1f}")
    if integration_files:
        print(
            f"Avg mocks per integration test: {integration_mocks / len(integration_files):.1f}"
        )

    # Check for refactored versions
    refactored_files = [f for f in test_files if "_refactored" in f.name]
    original_files = [f for f in test_files if "_refactored" not in f.name]

    print("\n=== Refactoring Impact ===")
    print(f"Original test files: {len(original_files)}")
    print(f"Refactored test files: {len(refactored_files)}")

    # Compare original vs refactored
    total_reduction = 0
    comparisons = 0
    for refactored in refactored_files:
        base_name = refactored.name.replace("_refactored", "")
        # Find original file in same directory
        parent_dir = refactored.parent
        original = parent_dir / base_name
        if original.exists():
            orig_count, _ = count_mocks(original)
            ref_count, _ = count_mocks(refactored)
            reduction = orig_count - ref_count
            total_reduction += reduction
            comparisons += 1
            reduction_pct = (reduction / orig_count * 100) if orig_count > 0 else 0
            print(
                f"  {base_name}: {orig_count} → {ref_count} mocks ({reduction_pct:.0f}% reduction)"
            )

    if comparisons > 0:
        print(f"\nTotal mocks eliminated through refactoring: {total_reduction}")
        print(
            f"Average reduction per refactored file: {total_reduction / comparisons:.1f} mocks"
        )


if __name__ == "__main__":
    main()
