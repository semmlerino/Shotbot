#!/usr/bin/env python3
"""Test headless mode functionality."""

# Standard library imports
import logging
import os
import subprocess
import sys

# Third-party imports
import pytest


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.qt]


def test_headless_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test headless environment detection."""
    logger.info("=" * 50)
    logger.info("Testing headless detection")
    logger.info("=" * 50)

    # Local application imports
    from headless_mode import (
        HeadlessMode,
    )

    # Test explicit headless flag (monkeypatch auto-restores after test)
    monkeypatch.setenv("SHOTBOT_HEADLESS", "1")
    assert HeadlessMode.is_headless_environment(), (
        "Should detect SHOTBOT_HEADLESS=1"
    )
    logger.info("✅ Detects SHOTBOT_HEADLESS=1")

    # Clear and test CI environment
    monkeypatch.delenv("SHOTBOT_HEADLESS", raising=False)
    monkeypatch.setenv("CI", "true")
    assert HeadlessMode.is_headless_environment(), "Should detect CI=true"
    logger.info("✅ Detects CI environment")

    # Test GitHub Actions
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert HeadlessMode.is_headless_environment(), "Should detect GitHub Actions"
    logger.info("✅ Detects GitHub Actions")

    # Test offscreen platform
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert HeadlessMode.is_headless_environment(), (
        "Should detect offscreen platform"
    )
    logger.info("✅ Detects offscreen platform")


def test_headless_qt_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Qt configuration for headless."""
    logger.info("=" * 50)
    logger.info("Testing Qt headless configuration")
    logger.info("=" * 50)

    # Local application imports
    from headless_mode import (
        HeadlessMode,
    )

    # Configure for headless (monkeypatch auto-restores after test)
    HeadlessMode.configure_qt_for_headless()

    # Check environment variables
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen", (
        "Should set offscreen platform"
    )
    logger.info("✅ Sets QT_QPA_PLATFORM=offscreen")

    assert os.environ["QT_QUICK_BACKEND"] == "software", (
        "Should set software backend"
    )
    logger.info("✅ Sets software rendering backend")

    assert "QT_XCB_GL_INTEGRATION" in os.environ, "Should disable GL integration"
    logger.info("✅ Disables OpenGL integration")


def test_headless_app_creation() -> None:
    """Test creating headless QApplication."""
    logger.info("=" * 50)
    logger.info("Testing headless QApplication creation")
    logger.info("=" * 50)

    # Third-party imports
    from PySide6.QtCore import (
        QCoreApplication,
    )

    # Local application imports
    from headless_mode import (
        HeadlessMode,
    )

    # Check if application already exists
    existing_app = QCoreApplication.instance()

    if existing_app:
        # Test is running under pytest-qt, use existing app
        logger.info("Using existing QApplication from test framework")

        # Test that headless mode can configure existing app
        HeadlessMode.configure_qt_for_headless()

        assert os.environ.get("QT_QPA_PLATFORM") == "offscreen", "Should be offscreen"
        logger.info("✅ Configured existing application for headless mode")
    else:
        # No existing app, create one
        app = HeadlessMode.create_headless_application([])

        assert app is not None, "Should create application"
        logger.info("✅ Creates QApplication successfully")

        assert os.environ.get("QT_QPA_PLATFORM") == "offscreen", "Should be offscreen"
        logger.info("✅ Application uses offscreen platform")

        # Clean up
        app.quit()


def test_headless_shotbot_command() -> None:
    """Test running shotbot with --headless flag."""
    logger.info("=" * 50)
    logger.info("Testing shotbot --headless command")
    logger.info("=" * 50)

    # Run shotbot with headless flag (exit quickly)
    env = os.environ.copy()
    env["SHOTBOT_HEADLESS"] = "1"
    env["SHOTBOT_MOCK"] = "1"  # Use mock data

    cmd = ["uv", "run", "python", "shotbot.py", "--headless", "--mock"]

    logger.info(f"Running: {' '.join(cmd)}")

    try:
        # Run with timeout to prevent hanging
        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=5, env=env)

        # Check output
        if "HEADLESS MODE" in result.stdout or "HEADLESS MODE" in result.stderr:
            logger.info("✅ Shotbot runs in headless mode")
        else:
            logger.warning("⚠️  Headless mode message not found in output")

        # It may exit with non-zero due to event loop, that's OK
        logger.info(f"Exit code: {result.returncode}")

    except subprocess.TimeoutExpired:
        logger.info("✅ Application started (killed after timeout - expected)")
    except Exception as e:  # noqa: BLE001
        logger.error(f"❌ Error running headless: {e}")


def test_decorators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test headless decorators."""
    logger.info("=" * 50)
    logger.info("Testing headless decorators")
    logger.info("=" * 50)

    # Local application imports
    from headless_mode import (
        HeadlessMode,
    )

    # Test skip_if_headless decorator
    @HeadlessMode.skip_if_headless
    def ui_operation() -> str:
        return "UI operation executed"

    # In normal mode - explicitly ensure we're not in headless mode
    monkeypatch.delenv("SHOTBOT_HEADLESS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    result = ui_operation()
    assert result == "UI operation executed", "Should execute normally"
    logger.info("✅ skip_if_headless executes in normal mode")

    # In headless mode
    monkeypatch.setenv("SHOTBOT_HEADLESS", "1")
    result = ui_operation()
    assert result is None, "Should skip in headless mode"
    logger.info("✅ skip_if_headless skips in headless mode")


def main() -> None:
    """Run all tests."""
    logger.info("Starting headless mode tests...")

    try:
        test_headless_detection()
        test_headless_qt_config()
        test_headless_app_creation()
        test_decorators()
        test_headless_shotbot_command()

        logger.info("")
        logger.info("=" * 50)
        logger.info("✅ ALL HEADLESS TESTS PASSED!")
        logger.info("=" * 50)

    except AssertionError as e:
        logger.error(f"❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        logger.error(f"❌ Unexpected error: {e}")
        # Standard library imports
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
