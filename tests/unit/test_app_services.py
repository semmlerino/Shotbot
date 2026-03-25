"""Tests for app_services build functions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_build_models_does_not_start_background_refresh():
    """build_models() loads cache synchronously but must not start the async thread."""
    from app_services import build_models

    mock_infra = MagicMock()
    mock_infra.shot_cache = MagicMock()
    mock_infra.shot_cache.get_shots_with_ttl.return_value = []
    mock_infra.process_pool = MagicMock()

    with patch("shots.shot_model.ShotModel._start_background_refresh") as mock_bg:
        models = build_models(mock_infra, parent=None)
        mock_bg.assert_not_called()
