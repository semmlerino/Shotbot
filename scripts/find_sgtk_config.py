#!/usr/bin/env python3
"""Diagnostic script to find SGTK/ShotGrid Toolkit configuration files.

Run this on the BlueBolt VFX server to locate SGTK config, engines, and hooks.
This helps diagnose file dialog and environment bootstrap issues.

Usage:
    python find_sgtk_config.py
    python find_sgtk_config.py --verbose
"""

import os
import sys
from pathlib import Path


def print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f" {title}")
    print("=" * 60)


def print_env_vars() -> None:
    """Print SGTK-related environment variables."""
    print_header("SGTK/ShotGrid Environment Variables")

    prefixes = ("SGTK_", "SHOTGUN_", "TK_", "TANK_")
    found = False

    for key, value in sorted(os.environ.items()):
        if any(key.startswith(p) for p in prefixes):
            print(f"  {key}={value}")
            found = True

    # Also check workspace-related vars
    workspace_vars = ["SHOW", "SEQUENCE", "SHOT", "WORKSPACE_PATH", "REZ_USED"]
    print("\n  Workspace variables:")
    for var in workspace_vars:
        value = os.environ.get(var, "<not set>")
        print(f"    {var}={value}")

    if not found:
        print("  No SGTK_*/SHOTGUN_*/TK_*/TANK_* variables found")


def find_sgtk_module() -> None:
    """Try to import sgtk and get info from it."""
    print_header("SGTK Module Information")

    try:
        import sgtk

        print(f"  sgtk module found: {sgtk.__file__}")
        print(f"  sgtk version: {getattr(sgtk, '__version__', 'unknown')}")

        # Try to get current engine
        try:
            engine = sgtk.platform.current_engine()
            if engine:
                print(f"  Current engine: {engine.name}")
                print(f"  Engine location: {engine.disk_location}")
                print(f"  Context: {engine.context}")
            else:
                print("  No engine currently running")
        except Exception as e:  # noqa: BLE001
            print(f"  Could not get current engine: {e}")

    except ImportError:
        print("  sgtk module not importable (expected outside DCC)")
        print("  Run this inside Maya/Nuke for full info")


def search_paths() -> list[Path]:
    """Get list of paths to search for SGTK config."""
    paths = []

    # Common BlueBolt/VFX paths
    common_paths = [
        "/software/bluebolt",
        "/software/shotgun",
        "/software/shotgrid",
        "/software/sgtk",
        "/software/toolkit",
        "/software/rez/packages",
        "/nethome",
        str(Path("~/.shotgun").expanduser()),
        str(Path("~/.shotgrid").expanduser()),
        str(Path("~/Library/Caches/Shotgun").expanduser()),  # macOS
        "/shows",  # Show-level config
    ]

    # Add paths from environment
    env_paths = [
        os.environ.get("SHOTGUN_HOME"),
        os.environ.get("TANK_CURRENT_PC"),
        os.environ.get("TK_CORE_PATH"),
    ]

    paths.extend(Path(p) for p in common_paths + env_paths if p and Path(p).exists())

    return paths


def find_files(
    base_paths: list[Path], patterns: list[str], max_depth: int = 5
) -> list[Path]:
    """Find files matching patterns under base paths."""
    found = []

    for base in base_paths:
        try:
            for pattern in patterns:
                # Use rglob but limit depth
                for match in base.rglob(pattern):
                    # Check depth
                    try:
                        rel = match.relative_to(base)
                        if len(rel.parts) <= max_depth:
                            found.append(match)
                    except ValueError:
                        pass
        except PermissionError:
            pass
        except Exception as e:  # noqa: BLE001
            print(f"  Error searching {base}: {e}")

    return found


def find_sgtk_configs(verbose: bool = False) -> None:  # noqa: ARG001
    """Find SGTK configuration files."""
    print_header("Searching for SGTK Configuration Files")

    base_paths = search_paths()
    print(f"  Searching in: {[str(p) for p in base_paths]}")

    # Patterns to find
    config_patterns = [
        "tk-maya",
        "tk-nuke",
        "tk-multi-workfiles*",
        "tk-multi-launchapp",
        "before_app_launch.py",
        "app_launch.py",
        "tank_configs",
        "pipeline_configuration",
        "config/core",
        "config/env",
    ]

    print("\n  Looking for SGTK engines and apps...")

    for pattern in config_patterns:
        matches = find_files(base_paths, [f"*{pattern}*"], max_depth=6)
        if matches:
            print(f"\n  {pattern}:")
            for m in matches[:10]:  # Limit output
                print(f"    {m}")
            if len(matches) > 10:
                print(f"    ... and {len(matches) - 10} more")


def find_workfiles_config() -> None:
    """Specifically look for tk-multi-workfiles2 configuration."""
    print_header("tk-multi-workfiles2 Configuration (File Dialog)")

    # This is what controls launch_at_startup
    patterns = [
        "**/tk-multi-workfiles2.yml",
        "**/tk-multi-workfiles2/**/*.yml",
        "**/workfiles2*.yml",
    ]

    base_paths = search_paths()

    for pattern in patterns:
        for base in base_paths:
            try:
                matches = list(base.glob(pattern))
                for m in matches[:5]:
                    print(f"  Found: {m}")
                    # Try to read and show launch_at_startup setting
                    try:
                        content = m.read_text()
                        if "launch_at_startup" in content:
                            # Find the line
                            for line in content.split("\n"):
                                if "launch_at_startup" in line:
                                    print(f"    -> {line.strip()}")
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass


def find_engine_startup() -> None:
    """Find engine startup files that might handle SGTK_FILE_TO_OPEN."""
    print_header("Engine Startup Files (SGTK_FILE_TO_OPEN handling)")

    patterns = [
        "**/tk-maya/**/startup.py",
        "**/tk-maya/**/engine.py",
        "**/tk-nuke/**/startup.py",
        "**/tk-nuke/**/engine.py",
        "**/tk-nuke/**/bootstrap.py",
    ]

    base_paths = search_paths()

    for pattern in patterns:
        for base in base_paths:
            try:
                matches = list(base.glob(pattern))
                for m in matches[:5]:
                    print(f"  Found: {m}")
                    # Check if SGTK_FILE_TO_OPEN is referenced
                    try:
                        content = m.read_text()
                        if "SGTK_FILE_TO_OPEN" in content:
                            print("    -> Contains SGTK_FILE_TO_OPEN reference!")
                        if "file_to_open" in content.lower():
                            print("    -> Contains 'file_to_open' reference")
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass


def list_rez_packages() -> None:
    """List potentially relevant rez packages."""
    print_header("Rez Packages (SGTK-related)")

    rez_paths = [
        "/software/rez/packages",
        "/software/bluebolt/rez/packages",
        os.environ.get("REZ_PACKAGES_PATH", ""),
    ]

    sgtk_keywords = ["shotgun", "shotgrid", "sgtk", "toolkit", "tank", "maya", "nuke"]

    for rez_path in rez_paths:
        if not rez_path or not Path(rez_path).exists():
            continue

        print(f"\n  {rez_path}:")
        try:
            for item in sorted(Path(rez_path).iterdir()):
                if item.is_dir():
                    name_lower = item.name.lower()
                    if any(kw in name_lower for kw in sgtk_keywords):
                        print(f"    {item.name}/")
                        # List versions
                        try:
                            versions = sorted(item.iterdir())[:3]
                            for v in versions:
                                if v.is_dir():
                                    print(f"      {v.name}")
                        except Exception:  # noqa: BLE001
                            pass
        except PermissionError:
            print("    Permission denied")
        except Exception as e:  # noqa: BLE001
            print(f"    Error: {e}")


def main() -> None:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print("\n" + "=" * 60)
    print(" SGTK/ShotGrid Configuration Finder")
    print(" Run on BlueBolt VFX server to locate config files")
    print("=" * 60)

    print_env_vars()
    find_sgtk_module()
    list_rez_packages()
    find_sgtk_configs(verbose)
    find_workfiles_config()
    find_engine_startup()

    print_header("Next Steps")
    print("""
  1. Share the output of this script
  2. If possible, run this INSIDE Maya after launching:
     - Open Maya Script Editor
     - Run: exec(open('/path/to/find_sgtk_config.py').read())
  3. Look for tk-multi-workfiles2.yml with 'launch_at_startup' setting
  4. Look for engine startup.py files that handle SGTK_FILE_TO_OPEN
    """)


if __name__ == "__main__":
    main()
