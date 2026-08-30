"""Build the in-app settings popup."""

from __future__ import annotations

import urwid

from easy_docker_manager.config.settings_definitions import (
    SETTINGS_FIELD_DEFINITIONS,
    SettingDefinition,
    SettingInputType,
    SettingsMenuState,
)


def build_settings_popup_menu(
    menu_state: SettingsMenuState,
    background_widget: urwid.Widget,
) -> urwid.Overlay:
    """Place the editable settings form above the main terminal layout."""
    popup_rows = _build_setting_rows(menu_state)
    popup_rows.extend(
        [
            urwid.AttrMap(urwid.Divider("─"), "title_border"),
            urwid.Text(
                "Up/Down Field   Enter Edit   Left/Right Change",
                wrap="clip",
            ),
            urwid.Text("s Save   d Defaults   Esc Cancel", wrap="clip"),
        ]
    )
    if menu_state.error_message:
        popup_rows.append(urwid.Text(("error", menu_state.error_message), wrap="clip"))
    elif menu_state.status_message:
        popup_rows.append(
            urwid.Text(("status_ok", menu_state.status_message), wrap="clip")
        )

    popup = urwid.AttrMap(
        urwid.LineBox(
            urwid.Filler(urwid.Pile(popup_rows), valign="top"),
            title="Settings",
            title_attr="settings_menu_title",
        ),
        "settings_menu",
    )
    return urwid.Overlay(
        popup,
        background_widget,
        align="center",
        width=82,
        valign="middle",
        height=29 if menu_state.error_message or menu_state.status_message else 28,
    )


def _build_setting_rows(menu_state: SettingsMenuState) -> list[urwid.Widget]:
    """Build section headings and one row for each editable setting."""
    rows: list[urwid.Widget] = []
    previous_section = ""
    for setting_index, setting in enumerate(SETTINGS_FIELD_DEFINITIONS):
        if setting.section_title != previous_section:
            if rows:
                rows.append(urwid.AttrMap(urwid.Divider("─"), "title_border"))
            rows.append(urwid.Text(("host", setting.section_title), wrap="clip"))
            previous_section = setting.section_title
        rows.append(_build_setting_row(menu_state, setting_index, setting))
    return rows


def _build_setting_row(
    menu_state: SettingsMenuState,
    setting_index: int,
    setting: SettingDefinition,
) -> urwid.Widget:
    """Build one setting row with its current draft value."""
    is_selected = setting_index == menu_state.selected_setting_index
    row_prefix = "> " if is_selected else "  "
    value_text = _format_setting_value(menu_state, setting, is_selected)
    row_text = f"{row_prefix}{setting.display_label}: {value_text}"
    if is_selected:
        return urwid.AttrMap(
            urwid.Text(row_text, wrap="clip"),
            "settings_menu_selected",
        )
    return urwid.Text(
        [
            f"{row_prefix}{setting.display_label}: ",
            ("settings_value", value_text),
        ],
        wrap="clip",
    )


def _format_setting_value(
    menu_state: SettingsMenuState,
    setting: SettingDefinition,
    is_selected: bool,
) -> str:
    """Return the draft value as it should appear in the popup."""
    if is_selected and menu_state.editing_value_text is not None:
        return f"{menu_state.editing_value_text}_"

    value = getattr(menu_state.draft_config, setting.config_field_name)
    if setting.input_type == SettingInputType.BOOLEAN:
        return "Enabled" if value else "Disabled"
    if setting.input_type == SettingInputType.INTEGER:
        return f"{value:,}{setting.display_suffix}"
    return f"{value}{setting.display_suffix}"


__all__ = ["build_settings_popup_menu"]
