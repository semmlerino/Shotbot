"""Cache directory resolution from environment variables."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resolve_default_cache_dir() -> Path:
    """Resolve the default cache directory from environment variables.

    Priority:
    1. SHOTBOT_TEST_CACHE_DIR env var (explicit test override)
    2. pytest in sys.modules or SHOTBOT_MODE=test → cache_test
    3. SHOTBOT_MODE=mock → cache/mock
    4. Production → cache/production
    """
    test_cache_dir = os.getenv("SHOTBOT_TEST_CACHE_DIR")
    if test_cache_dir:
        return Path(test_cache_dir)
    if "pytest" in sys.modules or os.getenv("SHOTBOT_MODE") == "test":
        return Path.home() / ".shotbot" / "cache_test"
    if os.getenv("SHOTBOT_MODE") == "mock":
        return Path.home() / ".shotbot" / "cache" / "mock"
    return Path.home() / ".shotbot" / "cache" / "production"
