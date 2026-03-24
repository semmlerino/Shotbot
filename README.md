# ShotBot - Matchmove Shot Launcher

Shotbot is a PySide6 desktop tool for matchmove workflow execution in a VFX studio pipeline.
It provides shot browsing and one-click application launching with workspace context.

## Workflow Scope

Shotbot is designed around this pipeline:

`3DEqualizer -> Maya -> Nuke -> Publish`

Primary use cases:

- Browse active shots from `ws -sg`
- Launch tools in shot context (`3de`, `maya`, `nuke`, `rv`, `publish`)
- Browse other artists' 3DE scenes
- Resume prior work via Previous Shots

## Requirements

- Python `3.11+`
- Linux shell environment for launcher execution
- Studio workspace command availability (`ws`)
- Rez command availability for production DCC launches unless `REZ_MODE` is explicitly disabled
- A valid SGTK bootstrap source in the launched DCC environment
  (`Rez` package startup, site wrapper, or Shotbot startup scripts)

## Quick Start

```bash
# install dependencies
uv sync

# run in production/VFX mode
uv run python shotbot.py
```

## Development Mode (No VFX Environment)

```bash
# run with mock data (no ws, no facility filesystem)
uv run python shotbot.py --mock
# or
SHOTBOT_MOCK=1 uv run python shotbot.py
```

## Headless And Diagnostics

```bash
# headless CI-style launch (uses mock mode automatically)
uv run python shotbot.py --headless --mock

# auto-capture a screenshot after N seconds
# current implementation writes to C:\temp\shotbot_auto.png
uv run python shotbot.py --mock --screenshot 10
```

## Development Commands

```bash
# lint + format
uv run ruff check .
uv run ruff format .

# type checking
uv run basedpyright

# primary test suite (single worker via xdist, primary CI gate)
uv run pytest tests/

# parallel isolation check (secondary CI gate)
uv run pytest tests/ -n auto

# dead code detection (generate trace first, then analyze)
uv run python scripts/generate_skylos_trace.py
uv run skylos . --table --exclude-folder tests --exclude-folder archive
```

For the full Skylos workflow, including broader trace coverage (`--markexpr`), partial-trace handling, and whitelist guidance, see `docs/SKYLOS_DEAD_CODE_DETECTION.md`.

Test policy: serial is the default local run and the main correctness gate in CI.
Parallel is retained as a secondary isolation check for shared-state and teardown bugs,
not because it is dramatically faster.

For full testing policy and troubleshooting, see `tests/fixtures/README.md` and `pyproject.toml`.

## Documentation

See `docs/README.md` for the active documentation index and root reference docs.

## Configuration Notes

- User settings persist via Qt `QSettings` (`~/.config/ShotBot/ShotBot.conf` on Linux).
- App launch mappings are configured in `config.py`.
- `SHOTBOT_SCRIPTS_DIR` should point at the deployed `scripts/` directory if the
  facility does not provide `~/Python/Shotbot/scripts`. Shotbot injects this
  path into `NUKE_PATH` and `PYTHON_CUSTOM_SCRIPTS_3DE4` for file-launch hooks.
- Shotbot manages workspace and Rez shell setup, but it does not currently
  perform a full SGTK bootstrap on its own. See `docs/LAUNCHER_AND_VFX_ENVIRONMENT.md`
  for the production launcher contract.
