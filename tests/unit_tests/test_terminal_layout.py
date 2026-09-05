from __future__ import annotations

import urwid

from easy_docker_manager.config.settings_definitions import SettingsMenuState
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_actions import (
    ContainerActionMenuState,
    ContainerLifecycleAction,
)
from easy_docker_manager.core.container_sorting import (
    ContainerSortField,
    ContainerSortMenuState,
)
from easy_docker_manager.core.docker_connections import (
    DockerConnectionMenuState,
    DockerConnectionTransport,
    DockerContextDetails,
)
from easy_docker_manager.core.running_container_list import RunningContainerList
from easy_docker_manager.core.tabs import ContainerTabKey, TabName
from easy_docker_manager.core.terminal_session_state import (
    FocusArea,
    TerminalSessionState,
)
from easy_docker_manager.diagnostics import create_initial_diagnostics_report
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
    palette = {
        name: (foreground, background)
        for name, foreground, background in view.build_urwid_style_palette()
    }

    assert view.layout is not None
    assert {
        "app_title",
        "repository_link",
        "border_active",
        "border_inactive",
        "selected",
        "active_detail_tab",
        "highlight",
        "error",
        "export_menu_selected",
        "export_path_cursor",
        "diagnostics_value",
        "settings_menu_selected",
        "settings_value",
        "container_action_menu_selected",
        "docker_connection_menu_selected",
    } <= palette.keys()
    assert palette["diagnostics_popup"] == ("light gray", "default")
    assert palette["diagnostics_value"] == ("yellow", "default")
    assert palette["settings_menu_selected"] == (
        "white,bold",
        "light cyan",
    )
    assert palette["container_action_menu_selected"] == (
        "white,bold",
        "light cyan",
    )
    assert palette["docker_connection_menu_selected"] == (
        "white,bold",
        "light cyan",
    )


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


def test_title_panel_shows_terminal_logo_version_and_repository_inside_border() -> None:
    view = TerminalLayoutView(AppConfig(), installed_edm_version="1.2.0")
    title_panel = view.running_container_list_panel.widget.contents[0][0]

    rendered_title_canvas = title_panel.render((80,))
    rendered_title_lines = [line.decode() for line in rendered_title_canvas.text]
    rendered_title = "\n".join(rendered_title_lines)

    assert "github.com/arabnejad/edm" in rendered_title
    assert "███████╗  ██████╗   ███╗   ███╗" in rendered_title
    assert "╚══════╝  ╚═════╝   ╚═╝     ╚═╝" in rendered_title
    assert "Easy Docker Manager" in rendered_title
    assert "(v1.2.0)" in rendered_title
    assert "https://" not in rendered_title
    assert "\x1b" not in rendered_title
    assert len(rendered_title_lines) == 12
    assert rendered_title_lines[9].strip("│ ") == ""
    assert "─" in rendered_title_lines[-1]


def test_shortcut_footer_fits_connection_and_settings_at_minimum_width() -> None:
    view = TerminalLayoutView(AppConfig(), installed_edm_version="1.2.0")
    state = TerminalSessionState()

    view.render(state, [], lambda line: line)

    footer_line = view.layout.render((120, 30)).text[-1].decode()
    assert " a Actions" in footer_line
    assert " c Connect" in footer_line
    assert " p Settings" in footer_line


def test_container_action_popup_shows_actions_and_confirmation() -> None:
    menu_state = ContainerActionMenuState(
        container_id="container-1",
        container_name="web",
        available_actions=[
            ContainerLifecycleAction.RESTART,
            ContainerLifecycleAction.STOP,
        ],
    )
    state = TerminalSessionState(container_action_menu_state=menu_state)
    view = TerminalLayoutView(AppConfig(), installed_edm_version="1.2.0")

    view.render(state, [], lambda line: line)

    rendered_text = b"\n".join(view.layout.render((120, 30)).text).decode()
    assert "Container Actions" in rendered_text
    assert "> Restart container" in rendered_text
    assert "Stop container" in rendered_text

    menu_state.is_awaiting_confirmation = True
    view.render(state, [], lambda line: line)
    rendered_text = b"\n".join(view.layout.render((120, 30)).text).decode()
    assert 'Restart container "web"?' in rendered_text
    assert "Enter Confirm" in rendered_text

    menu_state.selected_action_index = 1
    view.render(state, [], lambda line: line)
    rendered_text = b"\n".join(view.layout.render((120, 30)).text).decode()
    assert 'Stop container "web"?' in rendered_text
    assert "The container will stop and disappear from the" in rendered_text
    assert "running-container list." in rendered_text


def test_docker_connection_popup_shows_contexts_and_selected_endpoint() -> None:
    local_context = DockerContextDetails(
        "default",
        "unix:///var/run/docker.sock",
        DockerConnectionTransport.LOCAL,
    )
    remote_context = DockerContextDetails(
        "staging",
        "ssh://docker@staging",
        DockerConnectionTransport.SSH,
    )
    state = TerminalSessionState(
        active_docker_context=local_context,
        docker_connection_menu_state=DockerConnectionMenuState(
            [local_context, remote_context],
            active_context_name="default",
            selected_context_index=1,
        ),
    )
    view = TerminalLayoutView(AppConfig(), installed_edm_version="1.2.0")

    view.render(state, [], lambda line: line)

    rendered_text = b"\n".join(view.layout.render((120, 30)).text).decode()
    assert "Docker Connections" in rendered_text
    assert "localhost" in rendered_text
    assert "> staging" in rendered_text
    assert "ssh://docker@staging" in rendered_text
    assert "Not checked" in rendered_text


def test_render_shows_diagnostics_above_other_popups() -> None:
    state = TerminalSessionState(
        diagnostics_popup_report=create_initial_diagnostics_report(),
        container_sort_menu_state=ContainerSortMenuState(
            selected_sort_field=ContainerSortField.DOCKER_ORDER,
            sort_descending=False,
        ),
    )
    view = TerminalLayoutView(AppConfig(), installed_edm_version="1.2.0")

    view.render(state, ["Select a running container."], lambda line: line)

    assert isinstance(view.layout.original_widget, urwid.Overlay)
    rendered_text = b"\n".join(view.layout.render((120, 30)).text).decode()
    assert "Help & Diagnostics" in rendered_text
    assert "Keyboard shortcuts" in rendered_text
    assert "EDM version:" in rendered_text
    assert "Connection:" in rendered_text
    assert "Checking..." in rendered_text
    assert "Esc Close" in rendered_text
    assert "Sort Containers" not in rendered_text


def test_render_shows_editable_settings_popup() -> None:
    menu_state = SettingsMenuState(AppConfig())
    state = TerminalSessionState(settings_menu_state=menu_state)
    view = TerminalLayoutView(AppConfig(), installed_edm_version="1.2.0")

    view.render(state, ["Select a running container."], lambda line: line)

    assert isinstance(view.layout.original_widget, urwid.Overlay)
    rendered_text = b"\n".join(view.layout.render((120, 30)).text).decode()
    assert "Settings" in rendered_text
    assert "Container list interval: 2.0 seconds" in rendered_text
    assert "Application logging" in rendered_text
    assert "Log level: INFO" in rendered_text
    assert "s Save" in rendered_text


def test_settings_popup_shows_numeric_editing_and_save_message() -> None:
    menu_state = SettingsMenuState(
        AppConfig(),
        editing_value_text="3.5",
        status_message="Settings saved. Restart EDM to apply them.",
    )
    state = TerminalSessionState(settings_menu_state=menu_state)
    view = TerminalLayoutView(AppConfig(), installed_edm_version="1.2.0")

    view.render(state, [], lambda line: line)

    rendered_text = b"\n".join(view.layout.render((120, 30)).text).decode()
    assert "Container list interval: 3.5_" in rendered_text
    assert "Settings saved. Restart EDM to apply them." in rendered_text


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


def test_container_panel_shows_active_remote_context_name() -> None:
    remote_context = DockerContextDetails(
        "staging",
        "ssh://docker@staging",
        DockerConnectionTransport.SSH,
    )
    view = TerminalLayoutView(AppConfig())
    state = TerminalSessionState(active_docker_context=remote_context)

    view.render(state, [], lambda line: line)

    rendered_text = b"\n".join(view.layout.render((120, 30)).text).decode()
    assert "staging (active)" in rendered_text


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
    assert " f Filter" in view.shortcut_footer_text.get_text()[0]


def test_container_panel_shows_compose_sections_and_plain_container_rows(
    container_summary_factory,
) -> None:
    view = TerminalLayoutView(AppConfig())
    running_container_list = RunningContainerList(
        [
            container_summary_factory(
                "api",
                name="example-api-1",
                compose_project_name="example",
            ),
            container_summary_factory(
                "worker",
                name="example-worker-1",
                compose_project_name="example",
            ),
            container_summary_factory(
                "monitor",
                name="monitor-web-1",
                compose_project_name="monitor",
            ),
            container_summary_factory("standalone", name="cadvisor"),
        ]
    )
    running_container_list.rebuild_displayed_containers(
        ContainerSortField.DOCKER_ORDER,
        False,
        "",
    )
    state = TerminalSessionState(
        running_container_list=running_container_list,
        selected_container_index=0,
    )

    view.render(state, ["Loading..."], lambda line: line)

    container_rows = view.running_container_list_panel.container_rows
    rendered_container_rows = "\n".join(
        line.decode() for row in container_rows for line in row.render((60,)).text
    )
    assert len(container_rows) == 4
    assert "example (2)" in rendered_container_rows
    assert "monitor (1)" in rendered_container_rows
    assert "Standalone" not in rendered_container_rows
    assert "cadvisor (running)" in rendered_container_rows
    assert "─" in rendered_container_rows


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
