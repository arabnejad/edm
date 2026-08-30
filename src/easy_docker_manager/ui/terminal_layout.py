"""Join the terminal panels and popups into one Urwid layout."""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional, Union

import urwid

from easy_docker_manager.config.settings_definitions import SettingsMenuState
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_sorting import ContainerSortMenuState
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.diagnostics import get_installed_edm_version
from easy_docker_manager.tab_export.definitions import TabExportMenuState
from easy_docker_manager.ui.container_details_panel import (
    SelectedContainerDetailsPanel,
)
from easy_docker_manager.ui.container_sort_menu import (
    build_container_sort_popup_menu,
)
from easy_docker_manager.ui.diagnostics_popup import build_diagnostics_popup
from easy_docker_manager.ui.formatting import MarkupSegment
from easy_docker_manager.ui.running_container_list_panel import (
    RunningContainerListPanel,
)
from easy_docker_manager.ui.settings_popup import build_settings_popup_menu
from easy_docker_manager.ui.tab_export_menu import build_tab_export_popup_menu


class TerminalLayoutView:
    """Combine EDM's panels, footer, and active popup.

    TerminalController calls render() with the current session state and the
    lines to display. RunningContainerListPanel updates the left side,
    SelectedContainerDetailsPanel updates the right side, and this object
    chooses whether a sorting, export, settings, or diagnostics popup appears above
    them. This class does not load Docker data, write files, or change
    navigation state.
    """

    def __init__(
        self,
        app_config: AppConfig,
        installed_edm_version: Optional[str] = None,
    ) -> None:
        self.app_config = app_config
        resolved_edm_version = (
            installed_edm_version
            if installed_edm_version is not None
            else get_installed_edm_version()
        )
        self.running_container_list_panel = RunningContainerListPanel(
            app_config,
            resolved_edm_version,
        )
        self.selected_container_details_panel = SelectedContainerDetailsPanel()
        self.shortcut_footer_text = urwid.Text(
            self._build_keyboard_shortcut_footer_content(), wrap="clip"
        )

        main_columns = urwid.Columns(
            [
                ("weight", 35, self.running_container_list_panel.widget),
                ("weight", 65, self.selected_container_details_panel.widget),
            ],
            dividechars=1,
            focus_column=0,
        )
        self._main_layout = urwid.Frame(
            main_columns,
            footer=urwid.AttrMap(self.shortcut_footer_text, "footer"),
        )
        self.layout = urwid.WidgetPlaceholder(self._main_layout)

    def build_urwid_style_palette(self) -> list[tuple[str, str, str]]:
        """Return the color styles passed to Urwid when EDM starts.

        No-color mode keeps selection visible with bold or reversed text while
        leaving all foreground and background colors at the terminal default.
        """
        color_palette = [
            ("app_title", "light blue,bold", "default"),
            ("repository_link", "yellow,bold", "default"),
            ("footer", "light blue,bold", "default"),
            ("shortcut_key", "black,bold", "light green"),
            ("key", "yellow,bold", "default"),
            ("title_border", "light blue,bold", "default"),
            ("border_active", "white,bold", "default"),
            ("border_inactive", "dark gray", "default"),
            ("panel_header", "light gray", "default"),
            ("title", "light cyan,bold", "default"),
            ("accent", "yellow,bold", "default"),
            ("host", "light cyan", "default"),
            ("selected", "white,bold", "dark magenta"),
            ("selected_inactive", "white", "dark gray"),
            ("detail_selected", "black", "light gray"),
            ("container", "light gray", "default"),
            ("container_status", "light green", "default"),
            ("tab", "white", "default"),
            ("active_detail_tab", "black,bold", "white"),
            ("status", "dark gray", "default"),
            ("muted", "dark gray", "default"),
            ("value", "light cyan", "default"),
            ("status_ok", "light green", "default"),
            ("highlight", "black", "yellow"),
            ("error", "light red", "default"),
            ("log_time", "light cyan", "default"),
            ("log_info", "light gray", "default"),
            ("log_debug", "dark gray", "default"),
            ("log_warning", "yellow", "default"),
            ("log_error", "light red,bold", "default"),
            ("log_number", "light cyan", "default"),
            ("log_http", "light green", "default"),
            ("sort_menu", "light gray", "default"),
            ("sort_menu_title", "yellow,bold", "default"),
            ("sort_menu_selected", "white,bold", "light cyan"),
            ("export_menu", "light gray", "default"),
            ("export_menu_title", "light cyan,bold", "default"),
            ("export_menu_selected", "white,bold", "light cyan"),
            ("export_path_cursor", "black", "white"),
            ("export_warning", "yellow,bold", "default"),
            ("diagnostics_popup", "light gray", "default"),
            ("diagnostics_value", "yellow", "default"),
            ("settings_menu", "light gray", "default"),
            ("settings_menu_title", "light cyan,bold", "default"),
            ("settings_menu_selected", "white,bold", "light cyan"),
            ("settings_value", "yellow", "default"),
        ]
        if self.app_config.colors_enabled:
            return color_palette

        standout_styles = {
            "shortcut_key",
            "selected",
            "selected_inactive",
            "detail_selected",
            "active_detail_tab",
            "highlight",
            "sort_menu_selected",
            "export_menu_selected",
            "export_path_cursor",
            "settings_menu_selected",
        }
        bold_styles = {
            "app_title",
            "footer",
            "key",
            "title_border",
            "border_active",
            "title",
            "accent",
            "host",
            "status_ok",
            "error",
            "log_error",
            "sort_menu_title",
            "export_menu_title",
            "export_warning",
            "settings_menu_title",
        }
        monochrome_palette = []
        for style_name, _foreground, _background in color_palette:
            foreground = "default"
            if style_name in standout_styles:
                foreground = "default,standout"
            elif style_name in bold_styles:
                foreground = "default,bold"
            monochrome_palette.append((style_name, foreground, "default"))
        return monochrome_palette

    def render(
        self,
        state: TerminalSessionState,
        detail_lines: list[str],
        format_detail_line: Callable[[str], Union[str, list[MarkupSegment]]],
    ) -> None:
        """Update both panels and show the active popup, if there is one."""
        self.running_container_list_panel.render(state)
        self.selected_container_details_panel.render(
            state,
            detail_lines,
            format_detail_line,
        )

        if state.diagnostics_popup_report is not None:
            self.layout.original_widget = build_diagnostics_popup(
                state.diagnostics_popup_report,
                self._main_layout,
            )
        elif isinstance(state.settings_menu_state, SettingsMenuState):
            self.layout.original_widget = build_settings_popup_menu(
                state.settings_menu_state,
                self._main_layout,
            )
        elif isinstance(state.tab_export_menu_state, TabExportMenuState):
            self.layout.original_widget = build_tab_export_popup_menu(
                state.tab_export_menu_state,
                self._main_layout,
            )
        elif isinstance(state.container_sort_menu_state, ContainerSortMenuState):
            self.layout.original_widget = build_container_sort_popup_menu(
                state.container_sort_menu_state,
                self._main_layout,
            )
        else:
            self.layout.original_widget = self._main_layout

    def focus_detail_line(self, line_index: int) -> None:
        """Keep the requested detail line visible in the right panel."""
        self.selected_container_details_panel.move_focus_to_selected_detail_line(
            line_index
        )

    @staticmethod
    def _build_keyboard_shortcut_footer_content() -> list[MarkupSegment]:
        """Return the key labels shown across the bottom of the screen."""
        return [
            ("shortcut_key", " q "),
            ("footer", " Quit "),
            ("shortcut_key", " Enter "),
            ("footer", " Detail "),
            ("shortcut_key", " Esc "),
            ("footer", " List "),
            ("shortcut_key", " [ "),
            ("footer", " Prev "),
            ("shortcut_key", " ] "),
            ("footer", " Next "),
            ("shortcut_key", " / "),
            ("footer", " Search "),
            ("shortcut_key", " f "),
            ("footer", " Filter "),
            ("shortcut_key", " s "),
            ("footer", " Sort "),
            ("shortcut_key", " e "),
            ("footer", " Export "),
            ("shortcut_key", " h "),
            ("footer", " Help "),
            ("shortcut_key", " p "),
            ("footer", " Settings"),
        ]


__all__ = ["TerminalLayoutView"]
