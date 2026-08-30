"""Describe the settings shown in EDM's settings editor."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from easy_docker_manager.core.config import (
    APPLICATION_LOG_LEVEL_NAMES,
    AppConfig,
)


class SettingInputType(str, Enum):
    """Describe how one setting can be changed in the popup."""

    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    CHOICE = "choice"


@dataclass(frozen=True)
class SettingDefinition:
    """Describe one AppConfig field shown in the settings popup."""

    config_field_name: str
    section_title: str
    display_label: str
    input_type: SettingInputType
    display_suffix: str = ""
    choices: tuple[str, ...] = ()


SETTINGS_FIELD_DEFINITIONS = (
    SettingDefinition(
        "container_list_refresh_interval_seconds",
        "Refresh",
        "Container list interval",
        SettingInputType.DECIMAL,
        " seconds",
    ),
    SettingDefinition(
        "tab_refresh_interval",
        "Refresh",
        "Active tab interval",
        SettingInputType.DECIMAL,
        " seconds",
    ),
    SettingDefinition(
        "initial_log_tail_lines",
        "Logs",
        "Initial log lines",
        SettingInputType.INTEGER,
    ),
    SettingDefinition(
        "max_log_lines",
        "Logs",
        "Maximum cached lines",
        SettingInputType.INTEGER,
    ),
    SettingDefinition(
        "max_log_line_chars",
        "Logs",
        "Maximum characters per line",
        SettingInputType.INTEGER,
    ),
    SettingDefinition(
        "tab_content_cache_max_entries",
        "Cache",
        "Maximum tab entries",
        SettingInputType.INTEGER,
    ),
    SettingDefinition(
        "tab_content_cache_max_bytes",
        "Cache",
        "Maximum cache size",
        SettingInputType.INTEGER,
        " bytes",
    ),
    SettingDefinition(
        "docker_request_timeout",
        "Docker",
        "Request timeout",
        SettingInputType.DECIMAL,
        " seconds",
    ),
    SettingDefinition(
        "max_background_worker_threads",
        "Docker",
        "Background worker threads",
        SettingInputType.INTEGER,
    ),
    SettingDefinition(
        "colors_enabled",
        "Display",
        "Colors",
        SettingInputType.BOOLEAN,
    ),
    SettingDefinition(
        "application_log_level",
        "Application logging",
        "Log level",
        SettingInputType.CHOICE,
        choices=APPLICATION_LOG_LEVEL_NAMES,
    ),
    SettingDefinition(
        "application_log_to_stdout",
        "Application logging",
        "Write to stdout",
        SettingInputType.BOOLEAN,
    ),
)


@dataclass
class SettingsMenuState:
    """Keep the draft values and current position while settings are open."""

    draft_config: AppConfig
    selected_setting_index: int = 0
    editing_value_text: Optional[str] = None
    error_message: str = ""
    status_message: str = ""

    @property
    def selected_setting(self) -> SettingDefinition:
        """Return the field currently selected in the settings popup."""
        return SETTINGS_FIELD_DEFINITIONS[self.selected_setting_index]


__all__ = [
    "SETTINGS_FIELD_DEFINITIONS",
    "SettingDefinition",
    "SettingInputType",
    "SettingsMenuState",
]
