from __future__ import annotations

import urwid

from easy_docker_manager.core import AppConfig
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.ui_session_state import FocusArea, UISessionState
from easy_docker_manager.ui.terminal_layout import (
    FocusableDetailLine,
    TerminalLayoutView,
)


def test_focusable_detail_line_accepts_focus_and_returns_unhandled_keys() -> None:
    row = FocusableDetailLine("line")
    assert row.selectable()
    assert row.keypress((80,), "down") == "down"


def test_layout_builds_all_named_palette_entries() -> None:
    view = TerminalLayoutView(AppConfig())
    names = {entry[0] for entry in view.build_palette()}

    assert view.layout is not None
    assert {
        "app_title",
        "border_active",
        "border_inactive",
        "selected",
        "active_detail_tab",
        "highlight",
        "error",
    } <= names


def test_render_shows_empty_container_state() -> None:
    view = TerminalLayoutView(AppConfig())
    state = UISessionState(status_message="No running containers.")

    view.render(state, ["Select a running container."], lambda line: line)

    assert view.container_rows[0].get_text()[0] == "No running containers."
    assert view.container_title_text.get_text()[0] == "Container: none selected"
    assert view.detail_status_text.get_text()[0] == "No running containers."


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

    selected_container = view.container_rows[0]
    assert isinstance(selected_container, urwid.AttrMap)
    assert selected_container.original_widget.get_text()[0] == "> web (running)"
    assert selected_container.get_attr_map()[None] == "selected_inactive"
    assert view.container_title_text.get_text()[0] == "Container: web"
    assert "Env" in view.detail_tabs_text.get_text()[0]
    assert view.search_query_text.get_text()[0] == "/PATH"
    assert view.container_panel is not None
    assert view.detail_panel is not None
    assert view.container_panel.get_attr_map()[None] == "border_inactive"
    assert view.detail_panel.get_attr_map()[None] == "border_active"
    assert isinstance(view.detail_rows[0], urwid.AttrMap)


def test_focus_detail_line_clamps_to_last_available_row(
    session_state_factory,
) -> None:
    view = TerminalLayoutView(AppConfig())
    state = session_state_factory()
    view.render(state, ["A", "B"], lambda line: line)

    view.focus_detail_line(20)

    assert view.detail_rows.focus == 1


def test_detail_line_widgets_are_reused_for_unchanged_lines() -> None:
    view = TerminalLayoutView(AppConfig())
    detail_view_key = ("container", TabName.LOGS, "")

    first_render = view._get_or_build_detail_line_widgets(
        ["A", "B"],
        detail_view_key,
        lambda line: line,
    )
    repeated_render = view._get_or_build_detail_line_widgets(
        ["A", "B"],
        detail_view_key,
        lambda line: line,
    )

    assert repeated_render is first_render


def test_log_update_reuses_overlapping_rows_and_builds_new_rows() -> None:
    view = TerminalLayoutView(AppConfig())
    detail_view_key = ("container", TabName.LOGS, "")
    first_render = view._get_or_build_detail_line_widgets(
        ["A", "B"],
        detail_view_key,
        lambda line: line,
    )

    updated_render = view._get_or_build_detail_line_widgets(
        ["B", "C"],
        detail_view_key,
        lambda line: line,
    )

    assert updated_render[0] is first_render[1]
    assert updated_render[1] is not first_render[0]
    assert updated_render[1].get_text()[0] == "C"


def test_context_change_rebuilds_detail_rows() -> None:
    view = TerminalLayoutView(AppConfig())
    first_context_render = view._get_or_build_detail_line_widgets(
        ["A"],
        ("container", TabName.LOGS, ""),
        lambda line: line,
    )
    changed_context_render = view._get_or_build_detail_line_widgets(
        ["A"],
        ("container", TabName.LOGS, "query"),
        lambda line: line,
    )

    assert changed_context_render[0] is not first_context_render[0]
