# BlueBolt Rez Packages

This is the project-root reference for the BlueBolt remote Rez inventory that
was captured during the `cachetools` vendoring work on 2026-03-19.

## Source of truth

- Full captured list in-repo:
  `BLUEBOLT_REZ_PACKAGES_FULL.md`
- Original Claude project memory copy:
  `~/.claude/projects/-mnt-c-CustomScripts-Python-shotbot/memory/reference_rez_packages.md`
- Generated with:
  `rez-search --type package --format '{name}-{version}'`
- Last checked:
  `2026-03-19`

## Key finding

`cachetools` is not available as a Rez package on the BlueBolt remote.
Shotbot should keep the vendored `cachetools/` copy in the bundle.

## Relevant packages confirmed present

- `PySide6-6.5.3`
- `PySide6-6.8.2.1`
- `PySide6_Addons-6.5.3`
- `PySide6_Addons-6.8.2.1`
- `PySide6_Essentials-6.5.3`
- `PySide6_Essentials-6.8.2.1`
- `ImageIO-2.37.2`
- `Jinja2-3.1.6`
- `Pillow-9.5.0`
- `PyYAML-6.0.2`
- `Fileseq-2.1.2`
- `GitPython-3.1.46`
- `uv-0.9.22`

## Refresh on the remote

Full list:

```bash
rez-search --type package --format '{name}-{version}' | sort
```

Single-package check:

```bash
rez-search --type package --format '{name}-{version}' | rg '^cachetools-'
```

## Related paths

Relevant package roots previously inspected in this project:

- `/software/rez/packages`
- `/software/bluebolt/rez/packages`
- `$REZ_PACKAGES_PATH`

The full snapshot is now committed in this repo as `BLUEBOLT_REZ_PACKAGES_FULL.md`.
