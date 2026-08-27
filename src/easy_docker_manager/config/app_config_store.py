"""Load and save EDM runtime configuration as JSON."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from platformdirs import user_config_dir

from easy_docker_manager.constants import APP_NAME
from easy_docker_manager.core.config import AppConfig

logger = logging.getLogger(__name__)

CONFIG_FILE_NAME = "config.json"


class AppConfigStore:
    """Load and save AppConfig in the operating system's user config directory.

    AppConfig defines the settings supported by the installed EDM version.
    Loading keeps valid settings, adds missing defaults, removes unknown names,
    and rewrites the file. This keeps config.json in sync after a normal upgrade
    or downgrade without separate migration code.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        """Use config_path when given, otherwise use the platform default path."""
        self.config_path = (
            config_path if config_path is not None else default_config_path()
        )

    def load_and_sync(self) -> AppConfig:
        """Load valid settings, fill defaults, rewrite the file, and return them.

        For example, if config.json contains refresh_interval and an old setting
        that EDM no longer supports, the returned AppConfig keeps the valid
        refresh interval and fills every missing setting from current defaults.
        The rewritten file contains the current settings and drops the old one.
        """
        raw_config = self._read_json_object()
        app_config = self._build_app_config(raw_config)
        self.save(app_config)
        return app_config

    def save(self, app_config: AppConfig) -> None:
        """Write readable JSON to a temporary file, then replace config.json."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.config_path.with_suffix(
                f"{self.config_path.suffix}.tmp"
            )
            temporary_path.write_text(
                f"{json.dumps(asdict(app_config), indent=2, sort_keys=True)}\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.config_path)
        except OSError as exc:
            logger.warning("Unable to save config file %s: %s", self.config_path, exc)

    def _read_json_object(self) -> dict[str, Any]:
        """Read the JSON object, or return an empty object if it cannot be used."""
        if not self.config_path.exists():
            return {}

        try:
            loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Unable to load config file %s: %s", self.config_path, exc)
            return {}

        if isinstance(loaded, dict):
            return loaded

        logger.warning(
            "Ignoring config file %s because it is not a JSON object",
            self.config_path,
        )
        return {}

    def _build_app_config(self, raw_config: dict[str, Any]) -> AppConfig:
        """Build AppConfig from known valid values and current defaults."""
        defaults = asdict(AppConfig())
        normalized = defaults.copy()

        for key, default_value in defaults.items():
            if key not in raw_config:
                continue

            try:
                value = _convert_config_value(
                    raw_config[key],
                    type(default_value),
                )
            except TypeError:
                logger.warning("Ignoring invalid config value for %s", key)
                continue

            candidate = normalized.copy()
            candidate[key] = value
            try:
                AppConfig(**candidate)
            except (TypeError, ValueError) as exc:
                logger.warning("Ignoring invalid config value for %s: %s", key, exc)
            else:
                normalized[key] = value

        return AppConfig(**normalized)


def default_config_path() -> Path:
    """Return EDM's config.json path for the current operating system."""
    return Path(user_config_dir(appname=APP_NAME, appauthor=False)) / CONFIG_FILE_NAME


def _convert_config_value(value: Any, expected_type: type[Any]) -> Any:
    """Return a config value converted to its expected type.

    Integer JSON values are accepted for float settings. Other values must have
    exactly the expected type. TypeError is raised when the value cannot be
    used.

    For example:

        _convert_config_value(2, float) returns 2.0
        _convert_config_value(True, int) raises TypeError

    The second call fails because bool is a subclass of int in Python, but a
    Boolean is not a valid integer setting for EDM.
    """
    if expected_type is float and type(value) in {int, float}:
        return float(value)

    if type(value) is expected_type:
        return value

    raise TypeError(f"expected {expected_type.__name__}")


__all__ = ["AppConfigStore", "default_config_path"]
