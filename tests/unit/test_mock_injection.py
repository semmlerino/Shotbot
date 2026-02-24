#!/usr/bin/env python3
"""Test that mock injection works correctly without GUI."""

# Standard library imports
import logging
import os

import pytest


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@pytest.mark.allow_main_thread  # Intentionally tests sync mock injection from main thread
def test_mock_pool_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that mock process pool can be injected and used."""
    logger.info("=" * 50)
    logger.info("Testing mock pool injection...")
    logger.info("=" * 50)

    # Enable mock mode (monkeypatch auto-restores after test)
    monkeypatch.setenv("SHOTBOT_MOCK", "1")

    # Local application imports
    # Import test doubles first
    from tests.fixtures.doubles_library import TestProcessPool

    # Create mock pool with main-thread allowed (test runs from main thread)
    mock_pool = TestProcessPool(allow_main_thread=True)
    mock_pool.set_outputs(
        "workspace /shows/demo/shots/seq01/seq01_0010",
        "workspace /shows/demo/shots/seq01/seq01_0020",
    )

    # Now inject it BEFORE importing ProcessPoolManager
    import process_pool_manager

    process_pool_manager.ProcessPoolManager._instance = mock_pool
    logger.info("✅ Mock pool injected")

    # Now test that it works
    from process_pool_manager import ProcessPoolManager

    pool = ProcessPoolManager.get_instance()

    # This should use the mock, not try to run real ws command
    result = pool.execute_workspace_command("ws -sg")
    logger.info("✅ Mock ws -sg executed successfully")
    logger.info(f"   Result: {result[:100]}...")

    # Verify we got mock data
    assert "seq01_0010" in result, "Should contain mock workspace output"
    logger.info("✅ Mock data verified in output")


def test_mock_injection_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that environment variable pollution doesn't affect other tests."""
    logger.info("=" * 50)
    logger.info("Testing environment isolation...")
    logger.info("=" * 50)

    # First verify no mock is set
    assert "SHOTBOT_MOCK" not in os.environ, (
        "SHOTBOT_MOCK should not be set initially"
    )
    logger.info("✅ Initial state: SHOTBOT_MOCK not set")

    # Set mock mode (monkeypatch auto-restores after test)
    monkeypatch.setenv("SHOTBOT_MOCK", "1")
    assert os.environ.get("SHOTBOT_MOCK") == "1", "Should be set to 1"
    logger.info("✅ SHOTBOT_MOCK set to '1'")

    # Clear and verify it's gone
    monkeypatch.delenv("SHOTBOT_MOCK", raising=False)
    assert "SHOTBOT_MOCK" not in os.environ, (
        "SHOTBOT_MOCK should be removed"
    )
    logger.info("✅ SHOTBOT_MOCK successfully removed")

    # monkeypatch automatically restores environment after test
    logger.info("✅ Environment cleanup handled by monkeypatch")
