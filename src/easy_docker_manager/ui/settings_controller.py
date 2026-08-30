"""Handle keyboard input from the settings popup."""

from __future__ import annotations

from dataclasses import asdict
from typing import Union

from easy_docker_manager.config.app_config_store import AppConfigStore
from easy_docker_manager.config.settings_definitions import (
    SETTINGS_FIELD_DEFINITIONS,
    SettingDefinition,
    SettingInputType,
    SettingsMenuState,
)
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.terminal_session_state import TerminalSessionState


class SettingsController:
    """Edit a configuration draft and save it for the next EDM run.

    KeyboardController sends every key here while the settings popup is open.
    Values are checked with AppConfig before they enter the draft. Saving only
    writes config.json; the running application keeps its current settings.
    """

    def __init__(
        self,
        state: TerminalSessionState,
        app_config_store: AppConfigStore,
    ) -> None:
        self.state = state
        self.app_config_store = app_config_store

    def open_settings_menu(self) -> bool:
        """Open settings with the values currently saved in config.json."""
        if self.state.settings_menu_state is not None:
            return False
        self.state.settings_menu_state = SettingsMenuState(
            draft_config=self.app_config_store.load_and_sync()
        )
        return True

    def handle_menu_keypress(self, key: str) -> bool:
        """Apply one keypress to the open settings menu."""
        menu_state = self.state.settings_menu_state
        if menu_state is None:
            return False
        if menu_state.editing_value_text is not None:
            return self._handle_value_editing_keypress(key)

        if key == "esc":
            self.state.settings_menu_state = None
            return True
        if key == "up":
            return self._move_selected_setting(-1)
        if key in {"down", "tab"}:
            return self._move_selected_setting(1)
        if key in {"left", "right", " ", "enter"}:
            return self._change_or_start_editing_selected_setting(key)
        if key in {"s", "S"}:
            return self._save_settings()
        if key in {"d", "D"}:
            return self._restore_default_settings()
        return False

    def _move_selected_setting(self, setting_offset: int) -> bool:
        """Move the selected row without wrapping around the menu."""
        menu_state = self._open_menu_state()
        old_index = menu_state.selected_setting_index
        menu_state.selected_setting_index = max(
            0,
            min(
                len(SETTINGS_FIELD_DEFINITIONS) - 1,
                old_index + setting_offset,
            ),
        )
        self._clear_menu_messages(menu_state)
        return menu_state.selected_setting_index != old_index

    def _change_or_start_editing_selected_setting(self, key: str) -> bool:
        """Edit a number or change the selected Boolean or choice value."""
        menu_state = self._open_menu_state()
        setting = menu_state.selected_setting
        if setting.input_type in {
            SettingInputType.INTEGER,
            SettingInputType.DECIMAL,
        }:
            if key != "enter":
                return False
            current_value = getattr(
                menu_state.draft_config,
                setting.config_field_name,
            )
            menu_state.editing_value_text = str(current_value)
            self._clear_menu_messages(menu_state)
            return True

        if setting.input_type == SettingInputType.BOOLEAN:
            current_value = getattr(
                menu_state.draft_config,
                setting.config_field_name,
            )
            return self._replace_draft_setting(setting, not current_value)

        current_choice = getattr(
            menu_state.draft_config,
            setting.config_field_name,
        )
        current_index = setting.choices.index(current_choice)
        direction = -1 if key == "left" else 1
        new_choice = setting.choices[(current_index + direction) % len(setting.choices)]
        return self._replace_draft_setting(setting, new_choice)

    def _handle_value_editing_keypress(self, key: str) -> bool:
        """Edit the selected numeric value until Enter accepts it."""
        menu_state = self._open_menu_state()
        setting = menu_state.selected_setting
        editing_text = menu_state.editing_value_text
        if editing_text is None:
            return False

        if key == "esc":
            menu_state.editing_value_text = None
            menu_state.error_message = ""
            return True
        if key == "enter":
            return self._accept_edited_numeric_value(setting, editing_text)
        if key == "backspace":
            if not editing_text:
                return False
            menu_state.editing_value_text = editing_text[:-1]
            menu_state.error_message = ""
            return True
        if len(key) != 1 or not key.isprintable():
            return False
        if key.isdigit() or (
            key == "."
            and setting.input_type == SettingInputType.DECIMAL
            and "." not in editing_text
        ):
            menu_state.editing_value_text = f"{editing_text}{key}"
            menu_state.error_message = ""
            return True
        return False

    def _accept_edited_numeric_value(
        self,
        setting: SettingDefinition,
        editing_text: str,
    ) -> bool:
        """Validate the typed number and store it in the draft."""
        menu_state = self._open_menu_state()
        try:
            new_value: Union[int, float]
            if setting.input_type == SettingInputType.INTEGER:
                new_value = int(editing_text)
            else:
                new_value = float(editing_text)
        except ValueError:
            menu_state.error_message = "Enter a valid number."
            return True

        try:
            updated_config = self._build_config_with_updated_setting(
                menu_state.draft_config,
                setting.config_field_name,
                new_value,
            )
        except (TypeError, ValueError) as exc:
            menu_state.error_message = str(exc)
            return True

        menu_state.draft_config = updated_config
        menu_state.editing_value_text = None
        self._clear_menu_messages(menu_state)
        return True

    def _replace_draft_setting(
        self,
        setting: SettingDefinition,
        new_value: object,
    ) -> bool:
        """Store a selected Boolean or choice value in the draft."""
        menu_state = self._open_menu_state()
        old_value = getattr(menu_state.draft_config, setting.config_field_name)
        if old_value == new_value:
            return False
        menu_state.draft_config = self._build_config_with_updated_setting(
            menu_state.draft_config,
            setting.config_field_name,
            new_value,
        )
        self._clear_menu_messages(menu_state)
        return True

    def _save_settings(self) -> bool:
        """Write the draft to config.json and leave the menu open."""
        menu_state = self._open_menu_state()
        menu_state.error_message = ""
        if not self.app_config_store.save(menu_state.draft_config):
            menu_state.status_message = ""
            menu_state.error_message = (
                "Unable to save config.json. Check the EDM application log."
            )
            return True
        menu_state.status_message = "Settings saved. Restart EDM to apply them."
        return True

    def _restore_default_settings(self) -> bool:
        """Replace the draft with defaults without saving it yet."""
        menu_state = self._open_menu_state()
        menu_state.draft_config = AppConfig()
        menu_state.editing_value_text = None
        menu_state.error_message = ""
        menu_state.status_message = "Defaults loaded. Press s to save them."
        return True

    def _open_menu_state(self) -> SettingsMenuState:
        """Return the open menu state used by private input handlers."""
        menu_state = self.state.settings_menu_state
        if menu_state is None:
            raise RuntimeError("Settings menu is not open")
        return menu_state

    @staticmethod
    def _build_config_with_updated_setting(
        draft_config: AppConfig,
        config_field_name: str,
        new_value: object,
    ) -> AppConfig:
        """Return a validated copy with one changed setting."""
        config_values = asdict(draft_config)
        config_values[config_field_name] = new_value
        return AppConfig(**config_values)

    @staticmethod
    def _clear_menu_messages(menu_state: SettingsMenuState) -> None:
        """Remove an old save or validation message after another edit."""
        menu_state.error_message = ""
        menu_state.status_message = ""


__all__ = ["SettingsController"]
