"""Reader for Maya version-up comments stored by the Maya version_up script.

The Maya version_up script saves optional per-version comments to
``~/.maya_version_up/{base}.json``, where *base* is the filename stem before
the ``_v###`` version token. Each JSON file maps full scene paths to comments.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


# Same pattern the Maya version_up script uses to extract the base name.
_VERSION_RE = re.compile(r"^(?P<base>.*?)[_-]?v\d+$")

_COMMENTS_DIR = Path.home() / ".maya_version_up"


def _parse_base(stem: str) -> str | None:
    """Extract the base name before the version token.

    Mirrors the Maya ``version_up.parse_version()`` logic so that shotbot
    reads from the same JSON file the script writes to.
    """
    m = _VERSION_RE.match(stem)
    if m:
        return m.group("base")
    return None


def load_maya_comments(scene_paths: list[Path]) -> dict[str, str]:
    """Load version-up comments for a list of Maya scene paths.

    Reads from ``~/.maya_version_up/{base}.json``, matching the storage
    format used by the Maya version_up script.

    Args:
        scene_paths: Maya scene file paths to look up comments for.

    Returns:
        Dict mapping ``str(path)`` to comment for paths that have one.

    """
    if not _COMMENTS_DIR.is_dir():
        return {}

    # Group paths by base name to minimise file reads.
    bases_needed: dict[str, list[Path]] = {}
    for path in scene_paths:
        base = _parse_base(path.stem)
        if base:
            bases_needed.setdefault(base, []).append(path)

    comments: dict[str, str] = {}
    for base, paths in bases_needed.items():
        json_path = _COMMENTS_DIR / f"{base}.json"
        try:
            with json_path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue

        if not isinstance(data, dict):
            continue

        for path in paths:
            path_str = str(path)
            if path_str in data and isinstance(data[path_str], str):
                comments[path_str] = data[path_str]

    return comments
