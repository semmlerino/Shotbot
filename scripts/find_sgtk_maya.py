#!/usr/bin/env python
"""Run this INSIDE Maya to find SGTK configuration.

In Maya Script Editor (Python tab), run:
    exec(open('/nethome/gabriel-h/Python/Shotbot/scripts/find_sgtk_maya.py').read())
"""

import os
import sys
from pathlib import Path


print("=" * 60)
print(" SGTK Configuration - Running Inside Maya")
print("=" * 60)

# 1. Environment variables
print("\n[1] SGTK Environment Variables:")
for key, value in sorted(os.environ.items()):
    if any(key.startswith(p) for p in ("SGTK_", "SHOTGUN_", "TK_", "TANK_")):
        print(f"    {key}={value}")

# 2. Workspace variables
print("\n[2] Workspace Variables:")
for var in ["SHOW", "SEQUENCE", "SHOT", "WORKSPACE_PATH", "PROJECT_PATH"]:
    print(f"    {var}={os.environ.get(var, '<not set>')}")

# 3. Try to import sgtk
print("\n[3] SGTK Module:")
try:
    import sgtk
    print(f"    sgtk location: {sgtk.__file__}")
    print(f"    sgtk version: {getattr(sgtk, '__version__', 'unknown')}")
except ImportError as e:
    print(f"    Cannot import sgtk: {e}")
    sgtk = None

# 4. Get current engine
print("\n[4] Current Engine:")
if sgtk:
    try:
        engine = sgtk.platform.current_engine()
        if engine:
            print(f"    Engine name: {engine.name}")
            print(f"    Engine version: {engine.version}")
            print(f"    Engine location: {engine.disk_location}")
            print(f"    Context: {engine.context}")
            print(f"    Context project: {engine.context.project}")
            print(f"    Context entity: {engine.context.entity}")

            # 5. Get pipeline configuration
            print("\n[5] Pipeline Configuration:")
            try:
                pc = engine.sgtk.pipeline_configuration
                print(f"    Config name: {pc.get_name()}")
                print(f"    Config path: {pc.get_path()}")
                print(f"    Config ID: {pc.get_shotgun_id()}")
            except Exception as e:
                print(f"    Error getting pipeline config: {e}")

            # 6. List registered apps
            print("\n[6] Registered Apps:")
            for app_name in sorted(engine.apps.keys()):
                app = engine.apps[app_name]
                print(f"    {app_name}: {app.disk_location}")

            # 7. Check workfiles2 specifically
            print("\n[7] tk-multi-workfiles2 Settings:")
            if "tk-multi-workfiles2" in engine.apps:
                wf = engine.apps["tk-multi-workfiles2"]
                print(f"    Location: {wf.disk_location}")
                # Try to get settings
                try:
                    settings = wf.settings
                    for key in ["launch_at_startup", "show_file_open", "file_extensions"]:
                        if key in settings:
                            print(f"    {key}: {settings[key]}")
                except Exception as e:
                    print(f"    Error reading settings: {e}")
            else:
                print("    tk-multi-workfiles2 not found in apps")

            # 8. Check for file_to_open handling
            print("\n[8] Checking for SGTK_FILE_TO_OPEN handling:")
            file_to_open = os.environ.get("SGTK_FILE_TO_OPEN")
            print(f"    SGTK_FILE_TO_OPEN={file_to_open}")

        else:
            print("    No engine currently running")
            print("    This means SGTK didn't bootstrap properly")
    except Exception as e:
        print(f"    Error: {e}")
        import traceback
        traceback.print_exc()
else:
    print("    Cannot check - sgtk not imported")

# 9. Check sys.path for sgtk locations
print("\n[9] SGTK-related paths in sys.path:")
for p in sys.path:
    if any(x in p.lower() for x in ["shotgun", "shotgrid", "sgtk", "toolkit", "tank"]):
        print(f"    {p}")

# 10. Check Maya's userSetup locations
print("\n[10] Maya Startup Scripts:")
try:
    script_paths = os.environ.get("MAYA_SCRIPT_PATH", "").split(":")
    for sp in script_paths:
        sp_path = Path(sp)
        if sp and sp_path.exists():
            user_setup = sp_path / "userSetup.py"
            if user_setup.exists():
                print(f"    Found: {user_setup}")
except Exception as e:
    print(f"    Error: {e}")

print("\n" + "=" * 60)
print(" Done - share this output")
print("=" * 60)
