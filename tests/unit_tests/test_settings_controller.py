from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Optional
from unittest.mock import Mock

from easy_docker_manager.config.app_config_store import AppConfigStore
from easy_docker_manager.config.settings_definitions import (
    SETTINGS_FIELD_DEFINITIONS,
)
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.ui.settings_controller import SettingsController


def _open_settings_controller(
    config_path: Path,
    saved_config: Optional[AppConfig] = None,
) -> tuple[SettingsController, TerminalSessionState, AppConfigStore]:
    config_store = AppConfigStore(config_path)
    assert config_store.save(saved_config if saved_config is not None else AppConfig())
    state = TerminalSessionState()
    controller = SettingsController(state, config_store)
    assert controller.open_settings_menu()
    return controller, state, config_store


def test_settings_menu_includes_every_app_config_field() -> None:
    assert {setting.config_field_name for setting in SETTINGS_FIELD_DEFINITIONS} == {
        config_field.name for config_field in fields(AppConfig)
    }


def test_open_settings_menu_loads_saved_values(tmp_path: Path) -> None:
    controller, state, _config_store = _open_settings_controller(
        tmp_path / "config.json",
        AppConfig(container_list_refresh_interval_seconds=5.0),
    )

    assert not controller.open_settings_menu()
    assert state.settings_menu_state is not None
    assert (
        state.settings_menu_state.draft_config.container_list_refresh_interval_seconds
        == 5.0
    )


def test_numeric_setting_is_edited_and_validated(tmp_path: Path) -> None:
    controller, state, _config_store = _open_settings_controller(
        tmp_path / "config.json"
    )
    menu_state = state.settings_menu_state
    assert menu_state is not None

    assert controller.handle_menu_keypress("enter")
    assert menu_state.editing_value_text == "2.0"
    for _character in range(3):
        controller.handle_menu_keypress("backspace")
    controller.handle_menu_keypress("0")
    assert controller.handle_menu_keypress("enter")

    assert menu_state.editing_value_text == "0"
    assert "must be positive" in menu_state.error_message

    controller.handle_menu_keypress("backspace")
    controller.handle_menu_keypress("3")
    assert controller.handle_menu_keypress("enter")
    assert menu_state.editing_value_text is None
    assert menu_state.draft_config.container_list_refresh_interval_seconds == 3.0


def test_escape_cancels_value_edit_before_closing_menu(tmp_path: Path) -> None:
    controller, state, _config_store = _open_settings_controller(
        tmp_path / "config.json"
    )
    menu_state = state.settings_menu_state
    assert menu_state is not None

    controller.handle_menu_keypress("enter")
    controller.handle_menu_keypress("9")

    assert controller.handle_menu_keypress("esc")
    assert state.settings_menu_state is menu_state
    assert menu_state.editing_value_text is None
    assert controller.handle_menu_keypress("esc")
    assert state.settings_menu_state is None


def test_boolean_and_choice_settings_change_with_arrow_keys(tmp_path: Path) -> None:
    controller, state, _config_store = _open_settings_controller(
        tmp_path / "config.json"
    )
    menu_state = state.settings_menu_state
    assert menu_state is not None

    menu_state.selected_setting_index = 9
    assert controller.handle_menu_keypress("right")
    assert menu_state.draft_config.colors_enabled is False

    menu_state.selected_setting_index = 10
    assert controller.handle_menu_keypress("right")
    assert menu_state.draft_config.application_log_level == "WARNING"
    assert controller.handle_menu_keypress("left")
    assert menu_state.draft_config.application_log_level == "INFO"


def test_save_writes_draft_and_reports_restart_requirement(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    controller, state, _config_store = _open_settings_controller(config_path)
    menu_state = state.settings_menu_state
    assert menu_state is not None
    menu_state.selected_setting_index = 9
    controller.handle_menu_keypress("right")

    assert controller.handle_menu_keypress("s")

    saved_values = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved_values["colors_enabled"] is False
    assert menu_state.status_message == "Settings saved. Restart EDM to apply them."


def test_failed_save_keeps_menu_open_and_shows_error(tmp_path: Path) -> None:
    config_store = Mock(spec=AppConfigStore)
    config_store.load_and_sync.return_value = AppConfig()
    config_store.save.return_value = False
    state = TerminalSessionState()
    controller = SettingsController(state, config_store)
    controller.open_settings_menu()

    assert controller.handle_menu_keypress("s")
    assert state.settings_menu_state is not None
    assert "Unable to save config.json" in state.settings_menu_state.error_message


def test_defaults_replace_draft_but_are_not_saved_automatically(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    controller, state, _config_store = _open_settings_controller(
        config_path,
        AppConfig(colors_enabled=False),
    )
    menu_state = state.settings_menu_state
    assert menu_state is not None

    assert controller.handle_menu_keypress("d")
    assert menu_state.draft_config == AppConfig()
    assert "Press s to save" in menu_state.status_message
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))["colors_enabled"] is False
    )
