# ShotBot - Matchmove Shot Launcher

Shotbot is a PySide6 desktop tool for matchmove workflow execution at BlueBolt.
It provides shot browsing and one-click DCC launching with workspace context.

## Workflow Scope

Shotbot is designed around this pipeline:

`3DEqualizer -> Maya -> Nuke -> Publish`

Primary use cases:

- Browse active shots from `ws -sg`
- Launch DCCs in shot context (`3de`, `maya`, `nuke`, `rv`, `publish`)
- Browse other artists' 3DE scenes
- Resume prior work via Previous Shots

## Requirements

- Python `3.11+`
- Linux shell environment for launcher execution
- BlueBolt workspace command availability (`ws`)

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

## Development Commands

```bash
# lint + format
uv run ruff check .
uv run ruff format .

# type checking
uv run basedpyright

# primary test suite (serial, primary CI gate)
uv run pytest tests/

# parallel isolation check (secondary CI gate)
uv run pytest tests/ -n auto --dist=loadgroup

# dead code detection (generate trace first, then analyze)
uv run python scripts/generate_skylos_trace.py
uv run skylos . --table --exclude-folder tests --exclude-folder archive
```

For the full Skylos workflow, including broader trace coverage (`--markexpr`), partial-trace handling, and whitelist guidance, see `docs/SKYLOS_DEAD_CODE_DETECTION.md`.

Test policy: serial is the default local run and the main correctness gate in CI.
Parallel is retained as a secondary isolation check for shared-state and teardown bugs,
not because it is dramatically faster.

For full testing policy and troubleshooting, see `UNIFIED_TESTING_V2.md`.

## Documentation

- `docs/README.md` - Active docs index
- `docs/THREADING_ARCHITECTURE.md` - Threading model and guardrails
- `docs/SIGNAL_ROUTING.md` - MainWindow signal-routing invariants
- `docs/CACHING_ARCHITECTURE.md` - Cache behavior and lifecycle
- `docs/LAUNCHER_AND_VFX_ENVIRONMENT.md` - Launcher and BlueBolt shell behavior
- `docs/DEPLOYMENT_SYSTEM.md` - Bundle/deploy workflow and recovery
- `segfault.md` - Crash triage playbook

## Configuration Notes

- User settings persist via Qt `QSettings` (`~/.config/ShotBot/ShotBot.conf` on Linux).
- App launch mappings are configured in `config.py`.
