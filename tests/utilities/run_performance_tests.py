#!/usr/bin/env python3
"""Master performance test runner.

This script runs all standalone performance tests and provides a comprehensive
performance validation report. It doesn't rely on pytest and focuses on
validating real performance characteristics.
"""

from __future__ import annotations

# Standard library imports
import subprocess
import sys
import time
from pathlib import Path


def run_test_script(script_path: Path) -> tuple[bool, float, str]:
    """Run a test script and return results.

    Args:
        script_path: Path to the test script

    Returns:
        Tuple of (success, runtime, output)
    """
    print(f"\n{'=' * 80}")
    print(f"RUNNING: {script_path.name}")
    print(f"{'=' * 80}")

    start_time = time.perf_counter()

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            check=False, capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        runtime = time.perf_counter() - start_time

        # Print output in real-time style
        print(result.stdout)
        if result.stderr:
            print("STDERR:")
            print(result.stderr)

        success = result.returncode == 0
        return success, runtime, result.stdout

    except subprocess.TimeoutExpired:
        runtime = time.perf_counter() - start_time
        error_msg = f"TEST TIMEOUT after {runtime:.1f}s"
        print(error_msg)
        return False, runtime, error_msg

    except Exception as e:
        runtime = time.perf_counter() - start_time
        error_msg = f"TEST ERROR: {e}"
        print(error_msg)
        return False, runtime, error_msg


def extract_performance_metrics(output: str) -> dict[str, str]:
    """Extract performance metrics from test output."""
    metrics = {}

    # Look for speedup patterns
    lines = output.split("\n")
    for line in lines:
        stripped_line = line.strip()

        # Extract speedup values
        if "speedup:" in stripped_line.lower() or "Speedup factor:" in stripped_line:
            try:
                # Find the number followed by 'x'
                # Standard library imports
                import re

                match = re.search(r"(\d+\.?\d*)x", stripped_line)
                if match:
                    metrics["speedup"] = match.group(1) + "x"
            except Exception:
                pass

        # Extract improvement percentages
        if "improvement:" in line.lower() and "%" in line:
            try:
                # Standard library imports
                import re

                match = re.search(r"(\d+\.?\d*)%", line)
                if match:
                    metrics["improvement"] = match.group(1) + "%"
            except Exception:
                pass

        # Extract memory usage
        if "memory" in line.lower() and "mb" in line.lower():
            try:
                # Standard library imports
                import re

                match = re.search(r"(\d+\.?\d*)\s*mb", line.lower())
                if match:
                    metrics["memory"] = match.group(1) + "MB"
            except Exception:
                pass

        # Extract cache statistics
        if "cache" in line.lower() and (
            "entries" in line.lower() or "size" in line.lower()
        ):
            try:
                # Standard library imports
                import re

                match = re.search(r"(\d+)\s*(entries|size)", line.lower())
                if match:
                    metrics["cache_entries"] = match.group(1)
            except Exception:
                pass

    return metrics


def generate_performance_report(results: list[tuple[str, bool, float, str]]) -> str:
    """Generate a comprehensive performance report."""
    report = []
    report.append("=" * 80)
    report.append("PERFORMANCE TEST SUMMARY REPORT")
    report.append("=" * 80)

    # Overall statistics
    total_tests = len(results)
    passed_tests = sum(1 for _, success, _, _ in results if success)
    total_runtime = sum(runtime for _, _, runtime, _ in results)

    report.append("\nOVERALL RESULTS:")
    report.append(f"  Tests Run:      {total_tests}")
    report.append(f"  Tests Passed:   {passed_tests}")
    report.append(f"  Tests Failed:   {total_tests - passed_tests}")
    report.append(f"  Success Rate:   {(passed_tests / total_tests) * 100:.1f}%")
    report.append(f"  Total Runtime:  {total_runtime:.2f}s")

    # Individual test results
    report.append("\nINDIVIDUAL TEST RESULTS:")
    report.append("-" * 50)

    for test_name, success, runtime, output in results:
        status = "✓ PASSED" if success else "✗ FAILED"
        report.append(f"\n{test_name}:")
        report.append(f"  Status:   {status}")
        report.append(f"  Runtime:  {runtime:.2f}s")

        # Extract and display performance metrics
        metrics = extract_performance_metrics(output)
        if metrics:
            report.append("  Metrics:")
            for key, value in metrics.items():
                report.append(f"    {key.replace('_', ' ').title()}: {value}")

    # Performance optimization summary
    report.append("\n" + "=" * 80)
    report.append("PERFORMANCE OPTIMIZATION VALIDATION")
    report.append("=" * 80)

    optimization_found = False

    for test_name, _success, _runtime, output in results:
        metrics = extract_performance_metrics(output)

        if "speedup" in metrics:
            try:
                speedup_value = float(metrics["speedup"].replace("x", ""))
                if speedup_value > 1.5:  # Significant improvement
                    report.append(
                        f"✓ {test_name}: {metrics['speedup']} performance improvement",
                    )
                    optimization_found = True
            except Exception:
                pass

        if "improvement" in metrics:
            try:
                improvement_value = float(metrics["improvement"].replace("%", ""))
                if improvement_value > 50:  # Significant improvement
                    report.append(
                        f"✓ {test_name}: {metrics['improvement']} performance improvement",
                    )
                    optimization_found = True
            except Exception:
                pass

    if not optimization_found:
        report.append("! No significant performance improvements detected")
        report.append(
            "  This may indicate that optimizations are not working as expected",
        )

    # Test quality assessment
    report.append("\nTEST QUALITY ASSESSMENT:")

    if passed_tests == total_tests:
        report.append("✓ All performance tests passed - system is performing well")
    elif passed_tests >= total_tests * 0.8:
        report.append("! Most tests passed - minor performance issues detected")
    else:
        report.append("✗ Many tests failed - significant performance issues detected")

    # Recommendations
    report.append("\nRECOMMENDATIONS:")

    if passed_tests == total_tests and optimization_found:
        report.append("✓ Performance optimizations are working correctly")
        report.append("✓ System is ready for production workloads")
    else:
        report.append("! Review failed tests and investigate performance bottlenecks")
        report.append(
            "! Consider running tests in isolation to identify specific issues",
        )

    report.append("\n" + "=" * 80)

    return "\n".join(report)


def main() -> int:
    """Run all performance tests and generate report."""
    print("=" * 80)
    print("SHOTBOT PERFORMANCE TEST SUITE")
    print("=" * 80)

    project_dir = Path(__file__).parent
    print(f"Project directory: {project_dir}")
    print(f"Python version: {sys.version}")

    # Define test scripts in order of execution
    test_scripts = [
        "standalone_regex_performance_test.py",
        "standalone_cache_performance_test.py",
        "standalone_memory_performance_test.py",
        "standalone_integration_performance_test.py",
    ]

    # Validate that all test scripts exist
    missing_scripts = []
    for script_name in test_scripts:
        script_path = project_dir / script_name
        if not script_path.exists():
            missing_scripts.append(script_name)

    if missing_scripts:
        print("\n✗ ERROR: Missing test scripts:")
        for script in missing_scripts:
            print(f"   - {script}")
        print("\nPlease ensure all test scripts are present before running.")
        return 1

    print(f"\n✓ Found {len(test_scripts)} test scripts:")
    for script in test_scripts:
        print(f"   - {script}")

    # Run all tests
    print("\nStarting performance test execution...")
    start_time = time.perf_counter()

    results = []

    for script_name in test_scripts:
        script_path = project_dir / script_name
        test_name = (
            script_name.replace("standalone_", "")
            .replace("_performance_test.py", "")
            .replace("_", " ")
            .title()
        )

        success, runtime, output = run_test_script(script_path)
        results.append((test_name, success, runtime, output))

    total_execution_time = time.perf_counter() - start_time

    # Generate and display comprehensive report
    print("\n\nGenerating performance report...")
    report = generate_performance_report(results)
    print(report)

    # Save report to file
    report_file = project_dir / "performance_test_report.txt"
    try:
        with report_file.open("w") as f:
            f.write("Performance Test Report\n")
            f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Execution Time: {total_execution_time:.2f}s\n\n")
            f.write(report)
        print(f"\n✓ Performance report saved to: {report_file}")
    except Exception as e:
        print(f"\n! Could not save report file: {e}")

    # Determine exit code
    passed_tests = sum(1 for _, success, _, _ in results if success)
    total_tests = len(results)

    if passed_tests == total_tests:
        print(f"\n✓ ALL PERFORMANCE TESTS PASSED ({passed_tests}/{total_tests})")
        return 0
    print(f"\n✗ SOME PERFORMANCE TESTS FAILED ({passed_tests}/{total_tests})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
