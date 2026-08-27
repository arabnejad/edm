from __future__ import annotations

import urwid

from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_sorting import (
    ContainerSortField,
    ContainerSortMenuState,
)
from easy_docker_manager.core.running_container_list import RunningContainerList
from easy_docker_manager.core.tabs import ContainerTabKey, TabName
from easy_docker_manager.core.terminal_session_state import (
    FocusArea,
    TerminalSessionState,
)
from easy_docker_manager.tab_export.definitions import (
    TabExportMenuField,
    TabExportMenuState,
    TabExportPhase,
)
from easy_docker_manager.ui.container_details_panel import FocusableDetailLine
from easy_docker_manager.ui.tab_export_menu import _format_export_path
from easy_docker_manager.ui.terminal_layout import TerminalLayoutView


def test_focusable_detail_line_accepts_focus_and_returns_unhandled_keys() -> None:
    row = FocusableDetailLine("line")
    assert row.selectable()
    assert row.keypress((80,), "down") == "down"


def test_layout_builds_all_named_palette_entries() -> None:
    view = TerminalLayoutView(AppConfig())
    names = {entry[0] for entry in view.build_urwid_style_palette()}

    assert view.layout is not None
    assert {
        "app_title",
        "border_active",
        "border_inactive",
        "selected",
        "active_detail_tab",
        "highlight",
        "error",
        "export_menu_selected",
        "export_path_cursor",
    } <= names


def test_no_color_palette_uses_terminal_defaults_and_keeps_selection_visible() -> None:
    view = TerminalLayoutView(AppConfig(colors_enabled=False))
    palette = {
        name: (foreground, background)
        for name, foreground, background in view.build_urwid_style_palette()
    }

    assert {background for _foreground, background in palette.values()} == {"default"}
    assert all(
        foreground in {"default", "default,bold", "default,standout"}
        for foreground, _background in palette.values()
    )
    assert palette["selected"] == ("default,standout", "default")
    assert palette["border_active"] == ("default,bold", "default")


def test_render_shows_empty_container_state() -> None:
    view = TerminalLayoutView(AppConfig())
    state = TerminalSessionState(status_message="No running containers.")

    view.render(state, ["Select a running container."], lambda line: line)

    running_container_list_panel = view.running_container_list_panel
    details_panel = view.selected_container_details_panel
    assert (
        running_container_list_panel.container_rows[0].get_text()[0]
        == "No running containers."
    )
    assert (
        details_panel.container_title_text.get_text()[0] == "Container: none selected"
    )
    assert details_panel.detail_status_text.get_text()[0] == "No running containers."
    assert (
        running_container_list_panel.container_sort_text.get_text()[0]
        == " s  Sort: Docker order"
    )
    assert running_container_list_panel.container_filter_text.get_text()[0] == (
        " f  Filter: off"
    )
    rendered_text = b"\n".join(view.layout.render((120, 40)).text).decode()
    assert rendered_text.index("localhost (active)") < rendered_text.index(
        "Filter: off"
    )
    assert rendered_text.index("Filter: off") < rendered_text.index(
        "Sort: Docker order"
    )
    assert rendered_text.index("Sort: Docker order") < rendered_text.index(
        "No running containers."
    )
    assert rendered_text.index("No running containers.") < rendered_text.index(
        "Refresh 2s | Logs 100 lines"
    )


def test_render_shows_and_hides_container_sort_menu() -> None:
    view = TerminalLayoutView(AppConfig())
    state = TerminalSessionState(
        container_sort_menu_state=ContainerSortMenuState(
            selected_sort_field=ContainerSortField.IMAGE,
            sort_descending=True,
        ),
    )

    view.render(state, ["Select a running container."], lambda line: line)

    assert isinstance(view.layout.original_widget, urwid.Overlay)
    rendered_text = b"\n".join(view.layout.render((120, 40)).text).decode()
    assert "Sort Containers" in rendered_text
    assert "> Image" in rendered_text
    assert "Direction: Descending" in rendered_text
    assert "Enter Apply" in rendered_text

    state.container_sort_menu_state = None
    view.render(state, ["Select a running container."], lambda line: line)
    assert view.layout.original_widget is view._main_layout


def test_render_shows_export_form_and_sensitive_data_warning() -> None:
    view = TerminalLayoutView(AppConfig())
    state = TerminalSessionState(
        tab_export_menu_state=TabExportMenuState(
            container_tab_key=ContainerTabKey("container-1", TabName.ENV),
            container_name="web",
            file_path="/tmp/web-env.txt",
            file_path_cursor_index=len("/tmp/web-env.txt"),
            selected_field=TabExportMenuField.SCOPE,
        )
    )

    view.render(state, ["A=1"], lambda line: line)

    assert isinstance(view.layout.original_widget, urwid.Overlay)
    rendered_text = b"\n".join(view.layout.render((120, 40)).text).decode()
    assert "Export Env" in rendered_text
    assert "Container: web" in rendered_text
    assert "may contain passwords" in rendered_text
    assert "> Scope: Current view" in rendered_text
    assert "Enter Export" in rendered_text
    assert "q Quit EDM" not in rendered_text


def test_render_shows_export_overwrite_confirmation_and_progress() -> None:
    view = TerminalLayoutView(AppConfig())
    menu_state = TabExportMenuState(
        container_tab_key=ContainerTabKey("container-1", TabName.LOGS),
        container_name="web",
        file_path="/tmp/web-logs.log",
        file_path_cursor_index=len("/tmp/web-logs.log"),
        phase=TabExportPhase.CONFIRMING_OVERWRITE,
    )
    state = TerminalSessionState(tab_export_menu_state=menu_state)

    view.render(state, ["line"], lambda line: line)
    rendered_text = b"\n".join(view.layout.render((120, 40)).text).decode()
    assert "This file already exists" in rendered_text
    assert "Enter Overwrite" in rendered_text

    menu_state.phase = TabExportPhase.WRITING
    view.render(state, ["line"], lambda line: line)
    rendered_text = b"\n".join(view.layout.render((120, 40)).text).decode()
    assert "Writing the selected tab" in rendered_text
    assert "Please wait" in rendered_text


def test_export_path_cursor_and_validation_error_are_rendered() -> None:
    view = TerminalLayoutView(AppConfig())
    menu_state = TabExportMenuState(
        container_tab_key=ContainerTabKey("container-1", TabName.CONFIG),
        container_name="web",
        file_path="output.txt",
        file_path_cursor_index=3,
        error_message="Directory does not exist",
    )
    state = TerminalSessionState(tab_export_menu_state=menu_state)

    view.render(state, ["config"], lambda line: line)

    assert _format_export_path(menu_state) == [
        ("value", "out"),
        ("export_path_cursor", "p"),
        ("value", "ut.txt"),
    ]
    rendered_text = b"\n".join(view.layout.render((120, 40)).text).decode()
    assert "Directory does not exist" in rendered_text


def test_container_footer_shows_active_sort_direction() -> None:
    view = TerminalLayoutView(AppConfig())
    state = TerminalSessionState(
        container_sort_field=ContainerSortField.CREATED_AT,
        container_sort_descending=True,
    )

    view.render(state, ["Select a running container."], lambda line: line)

    assert (
        view.running_container_list_panel.container_sort_text.get_text()[0]
        == " s  Sort: Creation time descending"
    )


def test_container_panel_shows_filter_query_match_count_and_editing_state(
    container_summary_factory,
) -> None:
    view = TerminalLayoutView(AppConfig())
    running_container_list = RunningContainerList(
        [
            container_summary_factory("cache", image_name="redis:7"),
            container_summary_factory("web", image_name="python:3.12"),
            container_summary_factory("worker", image_name="python:3.12"),
        ]
    )
    running_container_list.rebuild_displayed_containers(
        ContainerSortField.DOCKER_ORDER,
        False,
        "redis",
    )
    state = TerminalSessionState(
        running_container_list=running_container_list,
        selected_container_index=0,
        container_filter_query="redis",
        container_filter_query_before_editing="",
    )

    view.render(state, ["Loading..."], lambda line: line)

    assert view.running_container_list_panel.container_filter_text.get_text()[0] == (
        " f  Filter: redis (1/3) [editing]"
    )
    assert " f  Filter" in view.shortcut_footer_text.get_text()[0]


def test_container_panel_explains_when_no_running_container_matches_filter(
    container_summary_factory,
) -> None:
    view = TerminalLayoutView(AppConfig())
    running_container_list = RunningContainerList(
        [
            container_summary_factory("web"),
            container_summary_factory("worker"),
        ]
    )
    running_container_list.rebuild_displayed_containers(
        ContainerSortField.DOCKER_ORDER,
        False,
        "redis",
    )
    state = TerminalSessionState(
        running_container_list=running_container_list,
        container_filter_query="redis",
    )

    view.render(state, ["Select a running container."], lambda line: line)

    assert view.running_container_list_panel.container_rows[0].get_text()[0] == (
        'No running containers match "redis".'
    )


def test_render_updates_container_header_tabs_search_and_focus(
    session_state_factory,
) -> None:
    view = TerminalLayoutView(AppConfig())
    state = session_state_factory(tab=TabName.ENV)
    state.active_focus_area = FocusArea.DETAIL
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_search_queries[container_tab_key] = "PATH"
    state.is_search_active = True

    view.render(state, ["PATH=/bin"], lambda line: [("value", line)])

    running_container_list_panel = view.running_container_list_panel
    details_panel = view.selected_container_details_panel
    selected_container = running_container_list_panel.container_rows[0]
    assert isinstance(selected_container, urwid.AttrMap)
    assert selected_container.original_widget.get_text()[0] == "> web (running)"
    assert selected_container.get_attr_map()[None] == "selected_inactive"
    assert details_panel.container_title_text.get_text()[0] == "Container: web"
    assert "Env" in details_panel.detail_tabs_text.get_text()[0]
    assert details_panel.search_query_text.get_text()[0] == "/PATH"
    assert running_container_list_panel.panel.get_attr_map()[None] == "border_inactive"
    assert details_panel.panel.get_attr_map()[None] == "border_active"
    assert isinstance(details_panel.detail_rows[0], urwid.AttrMap)


def test_focus_detail_line_clamps_to_last_available_row(
    session_state_factory,
) -> None:
    view = TerminalLayoutView(AppConfig())
    state = session_state_factory()
    view.render(state, ["A", "B"], lambda line: line)

    view.focus_detail_line(20)

    assert view.selected_container_details_panel.detail_rows.focus == 1


def test_tab_display_lines_are_reused_when_content_is_unchanged() -> None:
    view = TerminalLayoutView(AppConfig())
    details_panel = view.selected_container_details_panel
    detail_view_key = ("container", TabName.LOGS, "")

    first_display_lines = details_panel._get_cached_or_build_tab_display_lines(
        ["A", "B"],
        detail_view_key,
        lambda line: line,
    )
    cached_display_lines = details_panel._get_cached_or_build_tab_display_lines(
        ["A", "B"],
        detail_view_key,
        lambda line: line,
    )

    assert cached_display_lines is first_display_lines


def test_log_update_reuses_overlapping_display_lines() -> None:
    view = TerminalLayoutView(AppConfig())
    details_panel = view.selected_container_details_panel
    detail_view_key = ("container", TabName.LOGS, "")
    first_display_lines = details_panel._get_cached_or_build_tab_display_lines(
        ["A", "B"],
        detail_view_key,
        lambda line: line,
    )

    updated_display_lines = details_panel._get_cached_or_build_tab_display_lines(
        ["B", "C"],
        detail_view_key,
        lambda line: line,
    )

    assert updated_display_lines[0] is first_display_lines[1]
    assert updated_display_lines[1] is not first_display_lines[0]
    assert updated_display_lines[1].get_text()[0] == "C"


def test_context_change_rebuilds_tab_display_lines() -> None:
    view = TerminalLayoutView(AppConfig())
    details_panel = view.selected_container_details_panel
    first_context_display_lines = details_panel._get_cached_or_build_tab_display_lines(
        ["A"], ("container", TabName.LOGS, ""), lambda line: line
    )
    changed_context_display_lines = (
        details_panel._get_cached_or_build_tab_display_lines(
            ["A"], ("container", TabName.LOGS, "query"), lambda line: line
        )
    )

    assert changed_context_display_lines[0] is not first_context_display_lines[0]
