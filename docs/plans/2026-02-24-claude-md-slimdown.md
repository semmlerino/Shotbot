# CLAUDE.md Slimdown — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce CLAUDE.md from 745 lines to ~250-300 lines by extracting verbose reference material into dedicated docs and condensing remaining sections.

**Architecture:** Extract 3 new docs from CLAUDE.md, rewrite CLAUDE.md as a concise working reference with pointers to extracted docs.

**Tech Stack:** Markdown files only — no code changes.

---

### Task 1: Create `docs/DEPLOYMENT_SYSTEM.md`

**Files:**
- Create: `docs/DEPLOYMENT_SYSTEM.md`

**Step 1: Write the extracted doc**

Combine these CLAUDE.md sections into one coherent doc:
- "Encoded Bundle System" (lines 74-91)
- "Import Errors and Debugging" (lines 159-198)
- "Auto-Push System" (lines 200-225)
- "Creating Deployment Bundle" (lines 134-142)
- "Deploying to Remote Environment" (lines 144-157)

Structure:
```
# Deployment System

## Overview
One paragraph: commit → auto-encode → push to encoded-releases → pull on VFX server → decode

## Encoded Bundle System
- How it works (5-step flow)
- Bundle files (shotbot_latest.txt, metadata)

## Auto-Push System
### Post-Commit Hook
### Background Push Script
### Troubleshooting
- Log files in .post-commit-output/

## Manual Bundle Operations
### Creating a Bundle
### Deploying to Remote

## Import Error Debugging
### Common Causes
### Fix Steps
```

Copy content verbatim from CLAUDE.md — just reorganize under new headings. Don't rewrite prose.

**Step 2: Commit**

```
docs: extract deployment system from CLAUDE.md
```

---

### Task 2: Create `docs/CACHING_ARCHITECTURE.md`

**Files:**
- Create: `docs/CACHING_ARCHITECTURE.md`

**Step 1: Write the extracted doc**

Take the "Caching System" section (lines 568-618) verbatim. Add a title header.

Structure:
```
# Caching Architecture

## Overview
One sentence: persistent caching with different strategies per data type.

## My Shots Cache
(verbatim from CLAUDE.md)

## Previous Shots Cache
(verbatim from CLAUDE.md)

## Other 3DE Scenes Cache
(verbatim from CLAUDE.md — strategy, implementation details, workflow, benefits)

## Clearing Cache
```

**Step 2: Commit**

```
docs: extract caching architecture from CLAUDE.md
```

---

### Task 3: Create `docs/LAUNCHER_AND_VFX_ENVIRONMENT.md`

**Files:**
- Create: `docs/LAUNCHER_AND_VFX_ENVIRONMENT.md`

**Step 1: Write the extracted doc**

Combine these CLAUDE.md sections:
- "Launcher System Architecture" (lines 620-655)
- "VFX Environment Architecture" (lines 657-745)

Structure:
```
# Launcher System & VFX Environment

## CommandLauncher
(verbatim: features, usage example, production stack)

## VFX Environment Architecture
### Shell Initialization Chain
### The `ws` Command
### Why `bash -ilc` is Required
### Key Environment Variables
### REZ_MODE Configuration
### Debugging VFX Environment Issues
```

**Step 2: Commit**

```
docs: extract launcher and VFX environment from CLAUDE.md
```

---

### Task 4: Rewrite CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (full rewrite)

**Step 1: Write the condensed CLAUDE.md**

Target: ~250-300 lines. Keep the same H2 structure where sections remain. Use this outline:

```markdown
# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview
(Keep lines 5-26 as-is — 22 lines, all useful context)

## Security Posture
Single-user tool on isolated VFX server. Do NOT flag security issues (shell=True,
eval, path traversal, etc.) — all acceptable. Focus reviews on correctness,
performance, maintainability, and Qt thread safety.

## Development Environment
- **Dev location**: `~/projects/shotbot` (Linux filesystem, symlinked from /mnt/c/...)
- **Production**: `/nethome/gabriel-h/Python/Shotbot/` (remote VFX server)
- **Deployment**: Encoded bundle via `encoded-releases` branch (see [docs/DEPLOYMENT_SYSTEM.md])
- **Dependencies**: Python 3.11+, PySide6, Pillow, psutil; install with `uv pip install -r requirements.txt`

## Development Commands
(Keep: run app, type check, lint, test commands — ~20 lines)
(Remove: deployment commands, test execution notes — covered by extracted docs and UNIFIED_TESTING_V2.md)

## Project Structure
(Keep lines 255-277 as-is)

## Threading Architecture
(Keep lines 279-286 as-is — already a pointer)

## Type Safety
(Keep lines 288-295 as-is)

## Singleton Pattern & Test Isolation
(Condense to ~15 lines)
- Two patterns: SingletonMixin (preferred) and legacy custom pattern
- All support `ClassName.reset()` for test isolation
- New singletons: inherit SingletonMixin, implement _initialize(), register in singleton_registry.py
- Existing singletons list (no code examples — read the source)

## Qt Widget Guidelines
(Condense to ~15 lines)
- RULE: All QWidget subclasses MUST accept `parent: QWidget | None = None` and pass to super().__init__(parent)
- Missing parent → Qt C++ crash (Fatal Python error: Aborted)
- Use `process_qt_events()` from tests.test_helpers for Qt state cleanup, not `qtbot.wait(1)`

## Testing
(~15 lines — quick start commands + pointer)
- Quick start commands (full regression, serial, single test)
- Pointer to UNIFIED_TESTING_V2.md for comprehensive guidance
- 3,500+ tests passing
- Coverage note: overall % is low due to excluded VFX/GUI code; core logic is 70-90%+

## Caching System
See [docs/CACHING_ARCHITECTURE.md](./docs/CACHING_ARCHITECTURE.md) for cache strategies, TTLs, and the incremental merge workflow.

## Launcher System & VFX Environment
See [docs/LAUNCHER_AND_VFX_ENVIRONMENT.md](./docs/LAUNCHER_AND_VFX_ENVIRONMENT.md) for CommandLauncher, shell init chain, `ws` command, Rez modes, and debugging.
```

**What's removed entirely (not extracted):**
- "Debugging Test Failures and Crashes" (lines 469-522) — operational recipes, covered by global CLAUDE.md
- Test coverage apologia (lines 535-566) — condensed to 2 lines
- Test fixture architecture table (lines 413-441) — discoverable from code, not needed in CLAUDE.md
- "Why This Architecture?" (lines 87-91) — obvious from context
- "Dependencies > Production Environment" (lines 248-253) — obvious
- Code examples in singleton section — read the source
- Both code examples in Qt widget section — one condensed inline example suffices

**Step 2: Verify no broken internal links**

Check that all `[text](./path)` links in the new CLAUDE.md point to files that exist.

**Step 3: Commit**

```
docs: slim CLAUDE.md from 745 to ~280 lines

Extract verbose reference sections to dedicated docs:
- docs/DEPLOYMENT_SYSTEM.md (auto-push, bundles, import debugging)
- docs/CACHING_ARCHITECTURE.md (cache strategies and workflows)
- docs/LAUNCHER_AND_VFX_ENVIRONMENT.md (launcher, VFX shell, Rez)

Condense remaining sections. No content lost — just reorganized.
```
