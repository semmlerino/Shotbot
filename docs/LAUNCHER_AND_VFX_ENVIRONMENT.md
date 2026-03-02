# Launcher System & VFX Environment

This document defines launcher behavior assumptions for the BlueBolt environment.

## Launcher Role

`CommandLauncher` is the production entrypoint for DCC launches with shot context.
It coordinates workspace setup, environment handling, and app dispatch.
Internally, it delegates to the `launch/` subpackage: `CommandBuilder`, `EnvironmentManager`, `ProcessExecutor`, and `ProcessVerifier`.

Supported DCCs: `3de`, `maya`, `nuke`, `rv`, `publish`.

## Environment Assumptions

1. Rez is initialized during shell startup.
2. `ws` sets workspace context (show/sequence/shot), not Rez initialization.
3. Launcher shell commands must use `bash -ilc` so `ws` is available.

## Shell Flow

High-level launch sequence:

`bash -ilc "ws <show>/<seq>/<shot> && <app command>"`

Why this matters:

- `-i` loads `.bashrc` where `workspace/ws` is defined
- `-l` preserves login-shell initialization behavior
- command runs with established workspace variables

When Rez wrapping is active (`has_rez_wrapper=True`), the outer shell uses `sh -c` for speed, wrapping an inner `bash -ilc` command that provides workspace context.

## Rez Mode

`REZ_MODE` in `config.py` controls wrapping strategy:

- `AUTO` (default): skip additional wrapping when `REZ_USED` is already set
- `DISABLED`: never wrap with Rez
- `FORCE`: always wrap with app-specific Rez packages

For BlueBolt, `AUTO` is the intended mode.

## Launch Verification

`Config.LAUNCH_VERIFICATION_ENABLED` (default `True`) enables async verification that GUI app launches succeed. Controlled by `LAUNCH_VERIFICATION_TIMEOUT_SEC` (60s) and `LAUNCH_VERIFICATION_POLL_SEC` (0.5s).

## Debugging Checklist

```bash
# rez state
echo "$REZ_USED"

# workspace command availability
type ws

# inspect workspace env after ws
ws <show>/<seq>/<shot> && env | grep -E '^(SHOW|SEQUENCE|SHOT|WORKSPACE|REZ_)'
```

## Integration Notes

- `ProcessPoolManager` supports launcher workflows by handling subprocess-heavy paths.
- Maya/SGTK context handling behavior is launcher-specific and should be validated in integration tests after refactors. SGTK environment variables and integration details are managed by the launcher's environment configuration.
