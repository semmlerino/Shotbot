"""Configuration storage and management for custom launchers.

NOTE: This file is part of an obsolete launcher implementation and is not used
in the current codebase. The active launcher system uses launcher_manager.py
instead. This file is kept for reference only and should not be imported.

This module provides persistent storage for custom launcher configurations.
It handles cross-platform config directory detection, atomic file operations,
automatic backups, and configuration migration.

Key features:
- Cross-platform config directory detection (Linux, macOS, Windows)
- Atomic writes with temporary files to prevent corruption
- Automatic backups before saves with cleanup
- JSON schema validation and migration support
- Comprehensive error handling and logging
- Import/export functionality

Configuration is stored in platform-appropriate locations:
- Linux: ~/.config/shotbot/custom_launchers.json
- macOS: ~/Library/Application Support/shotbot/custom_launchers.json
- Windows: %APPDATA%/shotbot/custom_launchers.json

Example:
    # Create configuration manager
    config = LauncherConfig()

    # Load existing launchers
    launchers = config.load_launchers()

    # Add a new launcher
    config.add_launcher(my_launcher)

    # Validate configuration
    errors = config.validate_config_file()
"""

import json
import logging
import platform
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# from launcher_model import Launcher, validate_launcher_schema
# Note: This file is not used in the current implementation.
# The active launcher system uses launcher_manager.py instead.

# Set up logger for this module
logger = logging.getLogger(__name__)


class LauncherConfigError(Exception):
    """Base exception for launcher configuration errors."""

    pass


class LauncherConfig:
    """Manages persistence and configuration of custom launchers."""

    # Configuration file schema version
    SCHEMA_VERSION = "1.0"

    # Default configuration structure
    DEFAULT_CONFIG = {
        "version": SCHEMA_VERSION,
        "created": "",
        "modified": "",
        "launchers": [],
    }

    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize launcher configuration manager.

        Args:
            config_dir: Custom configuration directory. If None, uses platform default.
        """
        self.config_dir = config_dir or self._get_default_config_dir()
        self.config_file = self.config_dir / "custom_launchers.json"
        self.backup_dir = self.config_dir / "backups"

        # Ensure directories exist
        self._ensure_directories()

        # Cache for loaded launchers
        self._launchers_cache: Optional[List[Launcher]] = None
        self._config_cache: Optional[Dict[str, Any]] = None
        self._last_modified: Optional[datetime] = None

    def _get_default_config_dir(self) -> Path:
        """Get platform-specific default configuration directory.

        Returns:
            Path to configuration directory
        """
        system = platform.system().lower()

        if system == "linux":
            # Linux: ~/.config/shotbot/
            config_base = Path.home() / ".config"
        elif system == "darwin":
            # macOS: ~/Library/Application Support/shotbot/
            config_base = Path.home() / "Library" / "Application Support"
        elif system == "windows":
            # Windows: %APPDATA%/shotbot/
            import os

            appdata = os.getenv("APPDATA")
            if appdata:
                config_base = Path(appdata)
            else:
                config_base = Path.home() / "AppData" / "Roaming"
        else:
            # Fallback to home directory
            logger.warning(f"Unknown platform '{system}', using home directory")
            config_base = Path.home() / ".shotbot"
            return config_base

        return config_base / "shotbot"

    def _ensure_directories(self):
        """Ensure configuration and backup directories exist."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Configuration directory: {self.config_dir}")
        except (OSError, PermissionError) as e:
            raise LauncherConfigError(
                f"Failed to create config directory {self.config_dir}: {e}"
            )

    def _get_file_modified_time(self) -> Optional[datetime]:
        """Get the modification time of the config file.

        Returns:
            Modification time or None if file doesn't exist
        """
        if not self.config_file.exists():
            return None

        try:
            timestamp = self.config_file.stat().st_mtime
            return datetime.fromtimestamp(timestamp)
        except (OSError, IOError) as e:
            logger.warning(f"Failed to get file modification time: {e}")
            return None

    def _invalidate_cache(self):
        """Invalidate cached data."""
        self._launchers_cache = None
        self._config_cache = None
        self._last_modified = None

    def _create_backup(self) -> Optional[Path]:
        """Create a backup of the current configuration file.

        Returns:
            Path to backup file if successful, None otherwise
        """
        if not self.config_file.exists():
            return None

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"custom_launchers_{timestamp}.json"
            backup_path = self.backup_dir / backup_name

            shutil.copy2(self.config_file, backup_path)
            logger.debug(f"Created backup: {backup_path}")

            # Clean up old backups (keep last 10)
            self._cleanup_old_backups()

            return backup_path

        except (OSError, IOError, PermissionError) as e:
            logger.error(f"Failed to create backup: {e}")
            return None

    def _cleanup_old_backups(self, keep_count: int = 10):
        """Clean up old backup files, keeping only the most recent ones.

        Args:
            keep_count: Number of backup files to keep
        """
        try:
            # Get all backup files
            backup_files = list(self.backup_dir.glob("custom_launchers_*.json"))

            if len(backup_files) <= keep_count:
                return

            # Sort by modification time (newest first)
            backup_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

            # Remove old backups
            for backup_file in backup_files[keep_count:]:
                try:
                    backup_file.unlink()
                    logger.debug(f"Removed old backup: {backup_file}")
                except OSError as e:
                    logger.warning(f"Failed to remove old backup {backup_file}: {e}")

        except (OSError, IOError) as e:
            logger.warning(f"Error cleaning up old backups: {e}")

    def _load_config_data(self) -> Dict[str, Any]:
        """Load raw configuration data from file.

        Returns:
            Configuration dictionary

        Raises:
            LauncherConfigError: If loading fails
        """
        if not self.config_file.exists():
            logger.debug("Configuration file does not exist, using defaults")
            return self.DEFAULT_CONFIG.copy()

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate basic structure
            if not isinstance(data, dict):
                raise LauncherConfigError(
                    "Configuration file must contain a JSON object"
                )

            # Ensure required fields exist
            if "launchers" not in data:
                data["launchers"] = []

            if "version" not in data:
                data["version"] = self.SCHEMA_VERSION

            logger.debug(
                f"Loaded configuration with {len(data.get('launchers', []))} launchers"
            )
            return data

        except FileNotFoundError:
            logger.debug("Configuration file not found, using defaults")
            return self.DEFAULT_CONFIG.copy()
        except PermissionError as e:
            raise LauncherConfigError(f"Permission denied reading config file: {e}")
        except json.JSONDecodeError as e:
            raise LauncherConfigError(f"Invalid JSON in config file: {e}")
        except (OSError, IOError) as e:
            raise LauncherConfigError(f"Error reading config file: {e}")

    def _save_config_data(self, data: Dict[str, Any]):
        """Save configuration data to file with atomic write.

        Args:
            data: Configuration data to save

        Raises:
            LauncherConfigError: If saving fails
        """
        try:
            # Create backup before saving
            self._create_backup()

            # Update timestamps
            now = datetime.now().isoformat()
            data["modified"] = now
            if "created" not in data or not data["created"]:
                data["created"] = now

            # Atomic write using temporary file
            temp_file = self.config_file.with_suffix(".tmp")

            try:
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                # Atomic move to final location
                temp_file.replace(self.config_file)
                logger.debug(f"Saved configuration to {self.config_file}")

                # Invalidate cache since file has changed
                self._invalidate_cache()

            except Exception:
                # Clean up temp file if something went wrong
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except OSError:
                        pass
                raise

        except PermissionError as e:
            raise LauncherConfigError(f"Permission denied writing config file: {e}")
        except (OSError, IOError) as e:
            raise LauncherConfigError(f"Error writing config file: {e}")

    def _migrate_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate configuration data to current schema version.

        Args:
            data: Configuration data to migrate

        Returns:
            Migrated configuration data
        """
        current_version = data.get("version", "1.0")

        if current_version == self.SCHEMA_VERSION:
            return data

        logger.info(
            f"Migrating configuration from version {current_version} to {self.SCHEMA_VERSION}"
        )

        # Add migration logic here for future schema changes
        # For now, just update the version
        data["version"] = self.SCHEMA_VERSION

        return data

    def load_launchers(self, force_reload: bool = False) -> List[Launcher]:
        """Load launchers from configuration file.

        Args:
            force_reload: If True, ignore cache and reload from file

        Returns:
            List of Launcher objects

        Raises:
            LauncherConfigError: If loading fails
        """
        # Check if we can use cached data
        if not force_reload and self._launchers_cache is not None:
            current_modified = self._get_file_modified_time()
            if current_modified == self._last_modified:
                logger.debug("Using cached launcher data")
                return self._launchers_cache

        try:
            # Load and migrate configuration
            data = self._load_config_data()
            data = self._migrate_config(data)

            # Parse launchers
            launchers = []
            launcher_data_list = data.get("launchers", [])

            for i, launcher_data in enumerate(launcher_data_list):
                try:
                    # Validate schema
                    errors = validate_launcher_schema(launcher_data)
                    if errors:
                        logger.error(f"Launcher {i} validation errors: {errors}")
                        continue

                    # Create launcher object
                    launcher = Launcher.from_dict(launcher_data)
                    launchers.append(launcher)

                except ValueError as e:
                    logger.error(f"Failed to load launcher {i}: {e}")
                    continue

            # Update cache
            self._launchers_cache = launchers
            self._config_cache = data
            self._last_modified = self._get_file_modified_time()

            logger.info(f"Loaded {len(launchers)} launchers from configuration")
            return launchers

        except Exception as e:
            logger.error(f"Failed to load launchers: {e}")
            raise LauncherConfigError(f"Failed to load launchers: {e}")

    def save_launchers(self, launchers: List[Launcher]):
        """Save launchers to configuration file.

        Args:
            launchers: List of Launcher objects to save

        Raises:
            LauncherConfigError: If saving fails
        """
        try:
            # Load current config data or use defaults
            try:
                data = self._load_config_data()
            except LauncherConfigError:
                data = self.DEFAULT_CONFIG.copy()

            # Convert launchers to dictionaries
            launcher_data_list = []
            for launcher in launchers:
                try:
                    launcher_dict = launcher.to_dict()

                    # Validate before saving
                    errors = validate_launcher_schema(launcher_dict)
                    if errors:
                        logger.error(
                            f"Launcher '{launcher.id}' validation errors: {errors}"
                        )
                        continue

                    launcher_data_list.append(launcher_dict)

                except Exception as e:
                    logger.error(f"Failed to serialize launcher '{launcher.id}': {e}")
                    continue

            # Update configuration
            data["launchers"] = launcher_data_list

            # Save to file
            self._save_config_data(data)

            logger.info(f"Saved {len(launcher_data_list)} launchers to configuration")

        except Exception as e:
            logger.error(f"Failed to save launchers: {e}")
            raise LauncherConfigError(f"Failed to save launchers: {e}")

    def add_launcher(self, launcher: Launcher):
        """Add a new launcher to the configuration.

        Args:
            launcher: Launcher to add

        Raises:
            LauncherConfigError: If launcher ID already exists or saving fails
        """
        launchers = self.load_launchers()

        # Check for duplicate ID
        if any(l.id == launcher.id for l in launchers):
            raise LauncherConfigError(
                f"Launcher with ID '{launcher.id}' already exists"
            )

        launchers.append(launcher)
        self.save_launchers(launchers)

        logger.info(f"Added launcher '{launcher.id}'")

    def update_launcher(self, launcher: Launcher):
        """Update an existing launcher in the configuration.

        Args:
            launcher: Launcher to update

        Raises:
            LauncherConfigError: If launcher not found or saving fails
        """
        launchers = self.load_launchers()

        # Find and replace launcher
        for i, existing in enumerate(launchers):
            if existing.id == launcher.id:
                launchers[i] = launcher
                self.save_launchers(launchers)
                logger.info(f"Updated launcher '{launcher.id}'")
                return

        raise LauncherConfigError(f"Launcher with ID '{launcher.id}' not found")

    def remove_launcher(self, launcher_id: str):
        """Remove a launcher from the configuration.

        Args:
            launcher_id: ID of launcher to remove

        Raises:
            LauncherConfigError: If launcher not found or saving fails
        """
        launchers = self.load_launchers()

        # Find and remove launcher
        for i, launcher in enumerate(launchers):
            if launcher.id == launcher_id:
                del launchers[i]
                self.save_launchers(launchers)
                logger.info(f"Removed launcher '{launcher_id}'")
                return

        raise LauncherConfigError(f"Launcher with ID '{launcher_id}' not found")

    def get_launcher_by_id(self, launcher_id: str) -> Optional[Launcher]:
        """Get a launcher by its ID.

        Args:
            launcher_id: ID of launcher to find

        Returns:
            Launcher object if found, None otherwise
        """
        launchers = self.load_launchers()

        for launcher in launchers:
            if launcher.id == launcher_id:
                return launcher

        return None

    def export_config(self, export_path: Path):
        """Export configuration to a file.

        Args:
            export_path: Path to export configuration to

        Raises:
            LauncherConfigError: If export fails
        """
        try:
            data = self._load_config_data()

            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Exported configuration to {export_path}")

        except Exception as e:
            raise LauncherConfigError(f"Failed to export configuration: {e}")

    def import_config(self, import_path: Path, merge: bool = False):
        """Import configuration from a file.

        Args:
            import_path: Path to import configuration from
            merge: If True, merge with existing config. If False, replace existing.

        Raises:
            LauncherConfigError: If import fails
        """
        try:
            # Load import data
            with open(import_path, "r", encoding="utf-8") as f:
                import_data = json.load(f)

            if not isinstance(import_data, dict):
                raise LauncherConfigError("Import file must contain a JSON object")

            if merge:
                # Merge with existing configuration
                existing_data = self._load_config_data()
                existing_launchers = existing_data.get("launchers", [])
                import_launchers = import_data.get("launchers", [])

                # Create mapping of existing launcher IDs
                existing_ids = {l.get("id") for l in existing_launchers if l.get("id")}

                # Add non-duplicate launchers
                merged_launchers = existing_launchers.copy()
                for launcher_data in import_launchers:
                    launcher_id = launcher_data.get("id")
                    if launcher_id and launcher_id not in existing_ids:
                        merged_launchers.append(launcher_data)

                import_data["launchers"] = merged_launchers

            # Migrate and save
            import_data = self._migrate_config(import_data)
            self._save_config_data(import_data)

            logger.info(f"Imported configuration from {import_path}")

        except FileNotFoundError:
            raise LauncherConfigError(f"Import file not found: {import_path}")
        except PermissionError as e:
            raise LauncherConfigError(f"Permission denied reading import file: {e}")
        except json.JSONDecodeError as e:
            raise LauncherConfigError(f"Invalid JSON in import file: {e}")
        except Exception as e:
            raise LauncherConfigError(f"Failed to import configuration: {e}")

    def validate_config_file(self) -> List[str]:
        """Validate the configuration file and return any issues.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        try:
            data = self._load_config_data()

            # Validate overall structure
            if not isinstance(data, dict):
                errors.append("Configuration must be a JSON object")
                return errors

            if "launchers" not in data:
                errors.append("Missing 'launchers' field")
                return errors

            if not isinstance(data["launchers"], list):
                errors.append("'launchers' field must be a list")
                return errors

            # Validate each launcher
            launcher_ids = set()
            for i, launcher_data in enumerate(data["launchers"]):
                # Check for duplicate IDs
                launcher_id = launcher_data.get("id")
                if launcher_id:
                    if launcher_id in launcher_ids:
                        errors.append(f"Duplicate launcher ID: {launcher_id}")
                    else:
                        launcher_ids.add(launcher_id)

                # Validate schema
                schema_errors = validate_launcher_schema(launcher_data)
                for error in schema_errors:
                    errors.append(f"Launcher {i}: {error}")

        except LauncherConfigError as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(f"Unexpected error validating config: {e}")

        return errors

    @property
    def config_path(self) -> Path:
        """Get the path to the configuration file."""
        return self.config_file

    @property
    def backup_path(self) -> Path:
        """Get the path to the backup directory."""
        return self.backup_dir
