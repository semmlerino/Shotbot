# Launcher System & VFX Environment

This document defines launcher behavior assumptions for the BlueBolt environment.

## Launcher Role

`CommandLauncher` is the production entrypoint for DCC launches with shot context.
It coordinates workspace setup, environment handling, and app dispatch.
Internally, it delegates to the `launch/` subpackage: `CommandBuilder`, `EnvironmentManager`, `ProcessExecutor`, and `ProcessVerifier`.

Supported DCCs: `3de`, `maya`, `nuke`, `rv`, `publish`.

## Environment Assumptions

1. `ws` sets workspace context (show/sequence/shot), not Rez initialization.
2. DCC launches resolve explicit Rez packages for the target app unless `REZ_MODE` is `DISABLED`.
3. Launcher shell commands use `bash -ilc` for the outer shell so `ws` is available before the Rez command runs.

## Shell Flow

High-level launch sequence:

`bash -ilc "ws <show>/<seq>/<shot> && rez env <packages> -- bash -lc '<app command>'"`

Why this matters:

- `-i` loads `.bashrc` where `workspace/ws` is defined
- `-l` preserves login-shell initialization behavior
- `ws` runs in the studio shell before Rez resolves the DCC context
- the inner Rez command only executes the app payload; it does not re-enter an interactive login shell

The launcher no longer treats `REZ_USED` as sufficient for DCC launches. A base Rez shell is not assumed to contain the correct Maya/Nuke/RV packages.

## Rez Mode

`REZ_MODE` in `config.py` controls wrapping strategy:

- `AUTO` (default): resolve the configured app packages for each DCC launch
- `DISABLED`: never wrap with Rez
- `FORCE`: always wrap with app-specific Rez packages

For BlueBolt, `AUTO` is the intended mode.

## Launch Verification

`Config.LAUNCH_VERIFICATION_ENABLED` (default `True`) enables async verification that GUI app launches succeed. Controlled by `LAUNCH_VERIFICATION_TIMEOUT_SEC` (60s) and `LAUNCH_VERIFICATION_POLL_SEC` (0.5s).

## Debugging Checklist

```bash
# rez state
echo "$REZ_USED"
rez context

# workspace command availability
type ws

# inspect workspace env after ws
ws <show>/<seq>/<shot> && env | grep -E '^(SHOW|SEQUENCE|SHOT|WORKSPACE|REZ_)'
```

## Integration Notes

- `ProcessPoolManager` supports launcher workflows by handling subprocess-heavy paths.
- Maya/SGTK context handling behavior is launcher-specific and should be validated in integration tests after refactors. SGTK environment variables and integration details are managed by the launcher's environment configuration.
