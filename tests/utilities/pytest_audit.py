#!/usr/bin/env python3
"""Audit pytest suite to identify problematic tests."""

# Standard library imports
import subprocess
import sys
import time
from pathlib import Path


def run_pytest_with_timeout(timeout_per_test=5):
    """Run pytest and collect results."""
    print("Running pytest audit with timeout...")
    print(f"Timeout per test: {timeout_per_test} seconds")
    print("=" * 70)

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",  # First just collect tests
        "-q",
        "--no-header",
    ]

    try:
        result = subprocess.run(
            cmd,
            check=False, capture_output=True,
            text=True,
            timeout=30,
            cwd=Path(__file__).parent,
        )

        # Parse collected tests
        test_lines = result.stdout.strip().split("\n")
        tests = [
            line.strip()
            for line in test_lines
            if "::" in line and not line.startswith(" ")
        ]

        print(f"Found {len(tests)} tests to audit")
        return tests

    except subprocess.TimeoutExpired:
        print("ERROR: Test collection timed out!")
        return []
    except Exception as e:
        print(f"ERROR collecting tests: {e}")
        return []


def audit_individual_file(test_file, timeout=10):
    """Audit an individual file with timeout."""
    print(f"\nTesting: {test_file}")
    print("-" * 50)

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        test_file,
        "-v",
        "--tb=short",
        "--no-header",
        "-p",
        "no:warnings",
    ]

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            check=False, capture_output=True,
            text=True,
            timeout=timeout,
            cwd=Path(__file__).parent,
        )

        duration = time.time() - start_time

        # Parse output for results
        output = result.stdout + result.stderr

        # Look for test results
        passed = output.count(" PASSED")
        failed = output.count(" FAILED")
        skipped = output.count(" SKIPPED")
        errors = output.count(" ERROR")

        # Check for specific issues
        has_timeout = False
        has_import_error = "ImportError" in output or "ModuleNotFoundError" in output
        has_fixture_error = (
            "fixture" in output.lower() and "not found" in output.lower()
        )

        return {
            "file": test_file,
            "status": "timeout"
            if has_timeout
            else ("success" if result.returncode == 0 else "failure"),
            "duration": duration,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "errors": errors,
            "has_import_error": has_import_error,
            "has_fixture_error": has_fixture_error,
            "output_sample": output[:500] if result.returncode != 0 else "",
        }

    except subprocess.TimeoutExpired:
        return {
            "file": test_file,
            "status": "timeout",
            "duration": timeout,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "has_timeout": True,
            "output_sample": f"TIMEOUT after {timeout} seconds",
        }
    except Exception as e:
        return {
            "file": test_file,
            "status": "error",
            "duration": time.time() - start_time,
            "error": str(e),
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 1,
        }


def main() -> int:
    """Run audit of all test files."""
    print("PyTest Suite Audit")
    print("=" * 70)

    # Find all test files
    test_files = list(Path("tests").rglob("test_*.py"))

    # Exclude our known problematic files
    exclude_patterns = [
        "test_process_pool_integration.py",  # We have test_process_pool_fast.py
        "test_subprocess_fixes.py",  # We have test_subprocess_fast.py
    ]

    test_files = [
        f
        for f in test_files
        if not any(pattern in f.name for pattern in exclude_patterns)
    ]

    print(f"Found {len(test_files)} test files to audit")
    print("(Excluding known problematic files we've already replaced)")

    results = []
    problematic = []

    for test_file in sorted(test_files):
        result = audit_individual_file(str(test_file), timeout=10)
        results.append(result)

        # Identify problematic tests
        if result["status"] == "timeout":
            problematic.append(("TIMEOUT", test_file))
        elif result["skipped"] > 0:
            problematic.append(("SKIPPED", test_file))
        elif result["failed"] > 0:
            problematic.append(("FAILED", test_file))
        elif result["errors"] > 0:
            problematic.append(("ERROR", test_file))

    # Summary
    print("\n" + "=" * 70)
    print("AUDIT SUMMARY")
    print("=" * 70)

    total = len(results)
    successful = sum(
        1 for r in results if r["status"] == "success" and r["skipped"] == 0
    )
    timeouts = sum(1 for r in results if r["status"] == "timeout")
    failures = sum(1 for r in results if r["status"] == "failure")
    with_skips = sum(1 for r in results if r["skipped"] > 0)

    print(f"Total test files: {total}")
    print(f"Fully successful: {successful}")
    print(f"With timeouts: {timeouts}")
    print(f"With failures: {failures}")
    print(f"With skipped tests: {with_skips}")

    if problematic:
        print("\n" + "=" * 70)
        print("PROBLEMATIC TESTS TO FIX OR DELETE")
        print("=" * 70)

        for issue, test_file in sorted(problematic):
            print(f"{issue:10} {test_file}")

        # Write problematic list to file
        with Path("problematic_tests.txt").open("w") as f:
            f.write("# Problematic Tests Found\n\n")
            for issue, test_file in sorted(problematic):
                f.write(f"{issue}: {test_file}\n")

        print("\nProblematic tests written to: problematic_tests.txt")

    # Detailed results for debugging
    print("\n" + "=" * 70)
    print("DETAILED RESULTS")
    print("=" * 70)

    for result in results:
        status_icon = (
            "✓" if result["status"] == "success" and result["skipped"] == 0 else "✗"
        )
        file_name = Path(result["file"]).name

        stats = f"P:{result['passed']} F:{result['failed']} S:{result['skipped']} E:{result['errors']}"
        duration = f"{result['duration']:.2f}s"

        print(f"{status_icon} {file_name:40} {stats:20} {duration:>8}")

        if result.get("output_sample"):
            print(f"   Issue: {result['output_sample'][:100]}...")

    return 0 if len(problematic) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
