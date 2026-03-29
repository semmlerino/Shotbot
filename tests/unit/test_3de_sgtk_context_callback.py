"""Tests for the 3DE SGTK context callback startup script."""

from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


pytestmark = [pytest.mark.unit]

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "3de_sgtk_context_callback.py"
)


def _load_callback_module(tde4: object):
    """Load the callback script as a fresh module with injected 3DE globals."""
    module_name = f"test_3de_sgtk_context_callback_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    module.tde4 = tde4
    spec.loader.exec_module(module)
    return module


class FakeContext:
    """Minimal SGTK context test double."""

    def __init__(
        self, label: str, task: str | None = None, step: str | None = None
    ) -> None:
        self.label = label
        self.task = task
        self.step = step

    def __str__(self) -> str:
        return self.label


@pytest.fixture(autouse=True)
def clear_sgtk_module() -> None:
    """Keep sys.modules clean between tests."""
    original = sys.modules.pop("sgtk", None)
    try:
        yield
    finally:
        sys.modules.pop("sgtk", None)
        if original is not None:
            sys.modules["sgtk"] = original


class TestThreeDESgtkContextCallback:
    """Test 3DE startup context promotion logic."""

    def test_attempt_updates_context_from_shotbot_file_path(
        self, monkeypatch: pytest.MonkeyPatch, mocker
    ) -> None:
        """The callback upgrades Shot context to task context when engine is ready."""
        monkeypatch.delenv("SGTK_FILE_TO_OPEN", raising=False)
        tde4 = SimpleNamespace(
            getProjectPath=lambda: "",
            setOpenProjectCallbackFunction=mocker.MagicMock(),
        )
        module = _load_callback_module(tde4)

        current_context = FakeContext("Shot BOB_205_017_430")
        new_context = FakeContext(
            "mm-default BOB_205_017_430, Shot BOB_205_017_430",
            task="mm-default",
        )
        engine = SimpleNamespace(
            context=current_context,
            sgtk=SimpleNamespace(context_from_path=lambda _path: new_context),
        )
        change_context = mocker.MagicMock(
            side_effect=lambda ctx: setattr(engine, "context", ctx)
        )
        sys.modules["sgtk"] = types.SimpleNamespace(
            platform=SimpleNamespace(
                current_engine=lambda: engine,
                change_context=change_context,
            )
        )

        monkeypatch.setenv(
            "SGTK_FILE_TO_OPEN",
            "/shows/bob2/shots/BOB_205_017/BOB_205_017_430/mm/scene_v001.3de",
        )

        result = module._attempt_context_update()

        assert result == "done"
        change_context.assert_called_once_with(new_context)
        assert engine.context is new_context

    def test_attempt_returns_done_when_context_already_matches(
        self, monkeypatch: pytest.MonkeyPatch, mocker
    ) -> None:
        """The callback is a no-op when the full task context is already active."""
        monkeypatch.delenv("SGTK_FILE_TO_OPEN", raising=False)
        target_context = FakeContext(
            "mm-default BOB_205_017_430, Shot BOB_205_017_430",
            task="mm-default",
        )
        tde4 = SimpleNamespace(
            getProjectPath=lambda: (
                "/shows/bob2/shots/BOB_205_017/BOB_205_017_430/mm/scene_v001.3de"
            ),
            setOpenProjectCallbackFunction=mocker.MagicMock(),
        )
        module = _load_callback_module(tde4)

        engine = SimpleNamespace(
            context=target_context,
            sgtk=SimpleNamespace(context_from_path=lambda _path: target_context),
        )
        change_context = mocker.MagicMock()
        sys.modules["sgtk"] = types.SimpleNamespace(
            platform=SimpleNamespace(
                current_engine=lambda: engine,
                change_context=change_context,
            )
        )

        result = module._attempt_context_update()

        assert result == "done"
        change_context.assert_not_called()

    def test_register_callback_starts_retry_when_engine_not_ready(
        self, monkeypatch: pytest.MonkeyPatch, mocker
    ) -> None:
        """Startup registers the open callback and starts retries for late engines."""
        monkeypatch.delenv("SGTK_FILE_TO_OPEN", raising=False)
        set_callback = mocker.MagicMock()
        tde4 = SimpleNamespace(
            getProjectPath=lambda: "",
            setOpenProjectCallbackFunction=set_callback,
        )
        module = _load_callback_module(tde4)

        monkeypatch.setenv(
            "SGTK_FILE_TO_OPEN",
            "/shows/bob2/shots/BOB_205_017/BOB_205_017_430/mm/scene_v001.3de",
        )
        monkeypatch.setattr(
            module,
            "_attempt_context_update",
            lambda **_kwargs: "retry",
        )

        started = []

        class FakeThread:
            def __init__(self, target, daemon):
                self.target = target
                self.daemon = daemon

            def start(self):
                started.append((self.target, self.daemon))

        monkeypatch.setattr(module.threading, "Thread", FakeThread)

        module._register_callback()

        set_callback.assert_called_once_with("_shotbot_update_sgtk_context")
        assert started == [(module._retry_context_update, True)]

    def test_get_target_project_path_prefers_open_project_then_env_fallback(
        self, monkeypatch: pytest.MonkeyPatch, mocker
    ) -> None:
        """The callback uses the actual project path when available."""
        monkeypatch.delenv("SGTK_FILE_TO_OPEN", raising=False)
        tde4 = SimpleNamespace(
            getProjectPath=lambda: "/actual/project.3de",
            setOpenProjectCallbackFunction=mocker.MagicMock(),
        )
        module = _load_callback_module(tde4)

        monkeypatch.setenv("SGTK_FILE_TO_OPEN", "/from/env.3de")
        assert module._get_target_project_path() == "/actual/project.3de"

        module.tde4 = SimpleNamespace(
            getProjectPath=lambda: "",
            setOpenProjectCallbackFunction=mocker.MagicMock(),
        )
        assert module._get_target_project_path() == "/from/env.3de"
