"""Configuration management for launcher system.

This module handles persistence of launcher configurations to disk,
extracted from the original launcher_manager.py for better separation of concerns.
"""

from __future__ import annotations

# Standard library imports
import json
from pathlib import Path
from typing import TypedDict, cast

# Local application imports
from launcher.models import CustomLauncher
from logging_mixin import LoggingMixin


class ConfigData(TypedDict):
    """Type definition for configuration data structure."""

    version: str
    launchers: dict[
        str, dict[str, str | dict[str, str | bool | list[str] | None] | list[str]]
    ]
    terminal_preferences: list[str]


class LauncherConfigManager(LoggingMixin):
    """Manages persistence of custom launcher configurations."""

    def __init__(self, config_dir: str | Path | None = None) -> None:
        super().__init__()
        if config_dir is not None:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = Path.home() / ".shotbot"
        self.config_file = self.config_dir / "custom_launchers.json"
        self._ensure_config_dir()

    def _ensure_config_dir(self) -> None:
        """Ensure configuration directory exists."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.logger.error(
                f"Failed to create config directory {self.config_dir}: {e}"
            )
            raise

    def load_launchers(self) -> dict[str, CustomLauncher]:
        """Load launchers from configuration file."""
        if not self.config_file.exists():
            self.logger.debug(f"Config file {self.config_file} does not exist")
            return {}

        try:
            with self.config_file.open() as f:
                data = cast(
                    "dict[str, str | dict[str, dict[str, str | dict[str, str | bool | list[str] | None] | list[str]]] | list[str]]",
                    json.load(f),
                )

            launchers: dict[str, CustomLauncher] = {}
            raw_launchers_value = data.get("launchers", {})
            if not isinstance(raw_launchers_value, dict):
                self.logger.error(
                    f"Invalid launchers data type: {type(raw_launchers_value)}"
                )
                return {}

            raw_launchers: dict[
                str,
                dict[str, str | dict[str, str | bool | list[str] | None] | list[str]],
            ] = raw_launchers_value
            for launcher_id, launcher_data in raw_launchers.items():
                launcher_data["id"] = launcher_id
                launchers[launcher_id] = CustomLauncher.from_dict(launcher_data)

            self.logger.info(f"Loaded {len(launchers)} launchers from config")
            return launchers

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            self.logger.error(f"Failed to load launcher config: {e}")
            return {}

    def save_launchers(self, launchers: dict[str, CustomLauncher]) -> bool:
        """Save launchers to configuration file."""
        try:
            config_data: ConfigData = {
                "version": "1.0",
                "launchers": {},
                "terminal_preferences": ["gnome-terminal", "konsole", "xterm"],
            }

            for launcher_id, launcher in launchers.items():
                launcher_dict = launcher.to_dict()
                # Remove ID from nested dict as it's the key
                _ = launcher_dict.pop("id", None)
                config_data["launchers"][launcher_id] = launcher_dict

            with self.config_file.open("w") as f:
                json.dump(config_data, f, indent=2)

            self.logger.info(f"Saved {len(launchers)} launchers to config")
            return True

        except (OSError, TypeError, ValueError) as e:
            self.logger.error(f"Failed to save launcher config: {e}")
            return False
