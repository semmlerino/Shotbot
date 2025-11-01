#!/usr/bin/env python3
"""Script to automatically fix all remaining time.sleep() calls in the test suite."""

import re
from pathlib import Path
from typing import List, Tuple

# Mapping of sleep patterns to their replacements
SLEEP_REPLACEMENTS = {
    # Memory management sleeps
    r"time\.sleep\(([\d.]+)\)\s*#?\s*[Gg]ive GC time": {
        "replacement": "wait_for_memory_cleanup(threshold_mb=500, timeout_ms={ms})",
        "import": "from tests.helpers.synchronization import wait_for_memory_cleanup",
        "multiplier": 1000,
    },
    # UI event processing sleeps
    r"time\.sleep\(([\d.]+)\)\s*#?\s*[Ll]et UI update|allow UI": {
        "replacement": "process_qt_events(qapp, {ms})",
        "import": "from tests.helpers.synchronization import process_qt_events",
        "multiplier": 1000,
    },
    # File operation waits
    r"time\.sleep\(([\d.]+)\)\s*#?\s*[Ww]ait for file|ensure deletion": {
        "replacement": "wait_for_file_operation(path, 'exists', timeout_ms={ms})",
        "import": "from tests.helpers.synchronization import wait_for_file_operation",
        "multiplier": 1000,
    },
    # Work simulation
    r"time\.sleep\(([\d.]+)\)\s*#?\s*[Ss]imulate work|brief pause|small delay": {
        "replacement": "simulate_work_without_sleep({ms})",
        "import": "from tests.helpers.synchronization import simulate_work_without_sleep",
        "multiplier": 1000,
    },
    # Thread synchronization
    r"time\.sleep\(([\d.]+)\)\s*#?\s*[Ll]et.*thread|wait.*start": {
        "replacement": "wait_for_threads_to_start(max_wait_ms={ms})",
        "import": "from tests.helpers.synchronization import wait_for_threads_to_start",
        "multiplier": 1000,
    },
    # Generic small sleeps (< 0.1s)
    r"time\.sleep\((0\.0\d+)\)": {
        "replacement": "simulate_work_without_sleep({ms})",
        "import": "from tests.helpers.synchronization import simulate_work_without_sleep",
        "multiplier": 1000,
    },
    # Generic medium sleeps (0.1s - 0.5s)
    r"time\.sleep\((0\.[1-4]\d*)\)": {
        "replacement": "process_qt_events(qapp, {ms})",
        "import": "from tests.helpers.synchronization import process_qt_events",
        "multiplier": 1000,
    },
    # Generic large sleeps (>= 0.5s)
    r"time\.sleep\(([0-9.]+)\)": {
        "replacement": "wait_for_condition(lambda: False, timeout_ms={ms})",
        "import": "from tests.helpers.synchronization import wait_for_condition",
        "multiplier": 1000,
    },
}

# Files to skip (intentional delays for chaos/load testing)
SKIP_FILES = [
    "test_chaos_engineering.py",
    "test_load_stress.py",
    "test_mutation_testing.py",
    "test_fuzzing.py",
]


def should_skip_file(file_path: Path) -> bool:
    """Check if file should be skipped."""
    return any(skip in file_path.name for skip in SKIP_FILES)


def fix_time_sleeps_in_file(file_path: Path) -> Tuple[bool, int, List[str]]:
    """Fix time.sleep calls in a single file.

    Returns:
        Tuple of (was_modified, num_replacements, imports_needed)
    """
    if should_skip_file(file_path):
        return False, 0, []

    try:
        content = file_path.read_text()
        original_content = content

        imports_needed = set()
        num_replacements = 0

        # Apply each replacement pattern
        for pattern, config in SLEEP_REPLACEMENTS.items():
            matches = list(re.finditer(pattern, content))
            if matches:
                for match in reversed(matches):  # Reverse to maintain positions
                    sleep_time = float(match.group(1))
                    ms_time = int(sleep_time * config["multiplier"])

                    replacement = config["replacement"].format(ms=ms_time)

                    # Replace the sleep call
                    start, end = match.span()
                    content = content[:start] + replacement + content[end:]

                    imports_needed.add(config["import"])
                    num_replacements += 1

                # Stop after first matching pattern
                if matches:
                    break

        # Add imports if needed
        if imports_needed and content != original_content:
            # Find where to add imports (after existing imports)
            import_insert_pos = 0
            for line in content.split("\n"):
                if line.startswith("import ") or line.startswith("from "):
                    import_insert_pos = content.find(line) + len(line) + 1
                elif line and not line.startswith("#"):
                    break

            # Add the new imports
            for imp in sorted(imports_needed):
                if imp not in content:
                    content = (
                        content[:import_insert_pos]
                        + imp
                        + "\n"
                        + content[import_insert_pos:]
                    )
                    import_insert_pos += len(imp) + 1

        # Write back if modified
        if content != original_content:
            file_path.write_text(content)
            return True, num_replacements, list(imports_needed)

        return False, 0, []

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False, 0, []


def main():
    """Fix all time.sleep calls in the test suite."""
    test_dir = Path("/mnt/c/CustomScripts/Python/PyFFMPEG/BB/shotbot/tests")

    # Find all test files
    test_files = list(test_dir.rglob("test_*.py"))

    print(f"Scanning {len(test_files)} test files for time.sleep() calls...")
    print("=" * 60)

    total_files_modified = 0
    total_replacements = 0
    files_with_sleeps = []

    # First pass: identify files with time.sleep
    for test_file in test_files:
        if should_skip_file(test_file):
            continue

        content = test_file.read_text()
        if "time.sleep" in content:
            files_with_sleeps.append(test_file)

    print(f"Found {len(files_with_sleeps)} files with time.sleep() calls")
    print()

    # Second pass: fix the files
    for test_file in files_with_sleeps:
        relative_path = test_file.relative_to(test_dir)
        was_modified, num_replacements, imports = fix_time_sleeps_in_file(test_file)

        if was_modified:
            total_files_modified += 1
            total_replacements += num_replacements
            print(f"✓ Fixed {relative_path}: {num_replacements} replacements")
            if imports:
                print(f"  Added imports: {', '.join(imports)}")
        else:
            # Check if file still has sleeps (might be in skip list or failed)
            content = test_file.read_text()
            if "time.sleep" in content:
                print(
                    f"⚠ Skipped {relative_path} (intentional delays or complex pattern)"
                )

    print()
    print("=" * 60)
    print("Summary:")
    print(f"  Files modified: {total_files_modified}")
    print(f"  Total replacements: {total_replacements}")
    print(f"  Files skipped: {len(files_with_sleeps) - total_files_modified}")

    # List remaining files with time.sleep
    remaining_files = []
    for test_file in test_files:
        content = test_file.read_text()
        if "time.sleep" in content and not should_skip_file(test_file):
            remaining_files.append(test_file.relative_to(test_dir))

    if remaining_files:
        print("\nFiles still containing time.sleep() (need manual review):")
        for f in remaining_files[:10]:  # Show first 10
            print(f"  - {f}")
        if len(remaining_files) > 10:
            print(f"  ... and {len(remaining_files) - 10} more")
    else:
        print("\n✅ All time.sleep() calls have been replaced!")

    return total_files_modified


if __name__ == "__main__":
    main()
