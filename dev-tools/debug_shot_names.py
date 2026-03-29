#!/usr/bin/env python3
"""Debug script to investigate missing shot names in VFX environment.

This script helps identify why shot names aren't appearing in the VFX environment
by checking the workspace command output and parsing logic.
"""

# Standard library imports
import os
import sys
from pathlib import Path


# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Local application imports
from config import Config
from shots.shot_parser import OptimizedShotParser
from workers.process_pool_manager import ProcessPoolManager


def debug_environment() -> None:
    """Debug the environment setup."""
    print("=== ENVIRONMENT DEBUG ===")
    print(f"SHOWS_ROOT from config: {Config.Paths.SHOWS_ROOT}")
    print(f"SHOWS_ROOT from env: {os.environ.get('SHOWS_ROOT', 'NOT SET')}")
    print(f"Working directory: {Path.cwd()}")
    print()


def debug_workspace_output() -> list[str]:
    """Debug the actual workspace command output."""
    print("=== WORKSPACE COMMAND DEBUG ===")
    try:
        # Get ProcessPoolManager instance
        pool = ProcessPoolManager.get_instance()

        # Execute workspace command
        print("Executing 'ws -sg' command...")
        output = pool.execute_workspace_command("ws -sg", cache_ttl=0)  # No cache

        print(f"Command output length: {len(output)} characters")
        lines = output.strip().split("\n") if output.strip() else []
        print(f"Number of lines: {len(lines)}")

        if output.strip():
            lines = output.strip().split("\n")
            print("\nFirst 5 lines of output:")
            for i, line in enumerate(lines[:5]):
                print(f"  {i + 1}: {line!r}")

            if len(lines) > 5:
                print(f"  ... and {len(lines) - 5} more lines")

        else:
            print("OUTPUT IS EMPTY!")
            return []

        return lines if output.strip() else []

    except Exception as e:
        print(f"ERROR executing workspace command: {e}")
        # Standard library imports
        import traceback

        traceback.print_exc()
        return []


def debug_parser_matching(lines: list[str]) -> bool:
    """Debug the parser regex matching."""
    print("\n=== PARSER DEBUG ===")

    parser = OptimizedShotParser()
    print(f"Parser regex pattern: {parser._ws_pattern.pattern}")
    print()

    successful_parses = 0
    failed_parses = 0

    for i, line in enumerate(lines[:10]):  # Test first 10 lines
        print(f"Line {i + 1}: {line!r}")

        # Test if regex matches
        match = parser._ws_pattern.search(line)
        if match:
            print(f"  ✅ Regex match: {match.groups()}")

            # Test full parsing
            result = parser.parse_workspace_line(line)
            if result:
                print(
                    f"  ✅ Parse result: show={result.show}, seq={result.sequence}, shot={result.shot}"
                )
                successful_parses += 1
            else:
                print("  ❌ Parse failed despite regex match")
                failed_parses += 1
        else:
            print("  ❌ No regex match")
            failed_parses += 1

            # Try to suggest what might be wrong
            if "workspace" in line:
                print("     💡 Line contains 'workspace' but doesn't match regex")
                if Config.Paths.SHOWS_ROOT not in line:
                    print(
                        f"     💡 Line doesn't contain expected SHOWS_ROOT: {Config.Paths.SHOWS_ROOT}"
                    )

                    # Try to extract the actual path
                    parts = line.split()
                    if len(parts) >= 2:
                        actual_path = parts[1]
                        print(f"     💡 Actual path in line: {actual_path}")
        print()

    print(
        f"Summary: {successful_parses} successful parses, {failed_parses} failed parses"
    )
    return successful_parses > 0


def suggest_fixes() -> None:
    """Suggest potential fixes based on the debugging results."""
    print("\n=== SUGGESTED FIXES ===")

    # Check if SHOWS_ROOT environment variable is different
    env_shows_root = os.environ.get("SHOWS_ROOT")
    config_shows_root = Config.Paths.SHOWS_ROOT

    if env_shows_root and env_shows_root != config_shows_root:
        print(f"🔧 SHOWS_ROOT environment variable is set to: {env_shows_root}")
        print(f"   But Config.Paths.SHOWS_ROOT is: {config_shows_root}")
        print("   This mismatch could cause parsing failures!")
        print("   Try setting SHOWS_ROOT environment variable to match your VFX setup.")

    print("🔧 Enable verbose debugging:")
    print("   export SHOTBOT_DEBUG_VERBOSE=1")
    print("   python shotbot.py")

    print("🔧 Try running with mock data to compare:")
    print("   python shotbot.py --mock")


def main() -> None:
    """Main debugging function."""
    print("ShotBot Shot Names Debug Tool")
    print("=" * 50)

    # Debug environment
    debug_environment()

    # Debug workspace output
    lines = debug_workspace_output()

    if not lines:
        print("No workspace output to debug. Exiting.")
        return

    # Debug parser matching
    has_successful_parses = debug_parser_matching(lines)

    if not has_successful_parses:
        print("\n❌ NO SUCCESSFUL PARSES FOUND!")
        print("This explains why shot names aren't appearing.")

    # Suggest fixes
    suggest_fixes()


if __name__ == "__main__":
    main()
