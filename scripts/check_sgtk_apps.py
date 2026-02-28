#!/usr/bin/env python
"""Run INSIDE Maya to check registered apps before/after file operations.

Run this BEFORE and AFTER using SG File Open to see what changes.

In Maya Script Editor (Python):
    exec(open(os.environ.get('SHOTBOT_SCRIPTS_DIR', str(Path.home() / 'Python/Shotbot/scripts')) + '/check_sgtk_apps.py').read())
"""


print("=" * 60)
print(" SGTK Apps & Commands Check")
print("=" * 60)

try:
    import sgtk
    engine = sgtk.platform.current_engine()

    if engine:
        # 1. List all registered apps
        print("\n[1] Registered Apps:")
        for name in sorted(engine.apps.keys()):
            print(f"    {name}")

        # 2. List all registered commands (menu items)
        print("\n[2] Registered Commands (Menu Items):")
        for cmd_name in sorted(engine.commands.keys()):
            cmd = engine.commands[cmd_name]
            props = cmd.get("properties", {})
            app = props.get("app")
            app_name = app.name if app else "unknown"
            print(f"    {cmd_name} ({app_name})")

        # 3. Check for publish app
        print("\n[3] Key Apps Status:")
        key_apps = [
            "tk-multi-publish2",
            "tk-multi-loader2",
            "tk-multi-breakdown",
            "tk-multi-snapshot",
            "tk-multi-workfiles2",
            "tk-multi-shotgunpanel",
        ]
        for app_name in key_apps:
            status = "LOADED" if app_name in engine.apps else "NOT LOADED"
            print(f"    {app_name}: {status}")

        # 4. Check context
        print("\n[4] Current Context:")
        print(f"    Project: {engine.context.project}")
        print(f"    Entity: {engine.context.entity}")
        print(f"    Task: {engine.context.task}")
        print(f"    Step: {engine.context.step}")

        # 5. Check environment
        print("\n[5] Current Environment:")
        try:
            env = engine.sgtk.pipeline_configuration.get_environment(
                "shot_step", engine.context
            )
            print("    Environment: shot_step")
            print(f"    Engines: {list(env.get_engines())}")
        except Exception as e:
            print(f"    Could not get environment: {e}")

        # 6. Try to manually trigger post-file-open
        print("\n[6] Attempting to trigger context change...")
        try:
            # This might trigger app re-registration
            engine.change_context(engine.context)
            print("    Context change triggered - check menu again")
        except Exception as e:
            print(f"    Error: {e}")

    else:
        print("No engine running!")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
