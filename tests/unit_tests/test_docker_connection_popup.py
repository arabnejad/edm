from __future__ import annotations

import urwid

from easy_docker_manager.core.docker_connections import (
    DockerConnectionMenuState,
    DockerConnectionTransport,
    DockerContextDetails,
)
from easy_docker_manager.ui.docker_connection_popup import (
    _build_docker_context_row,
    build_docker_connection_popup_menu,
)


def _render_popup_text(menu_state: DockerConnectionMenuState) -> str:
    popup = build_docker_connection_popup_menu(menu_state, urwid.SolidFill(" "))
    return "\n".join(line.decode() for line in popup.render((120, 30)).text)


def test_popup_shows_context_statuses_and_selected_endpoint() -> None:
    contexts = [
        DockerContextDetails(
            "default",
            "unix:///var/run/docker.sock",
            DockerConnectionTransport.LOCAL,
        ),
        DockerContextDetails(
            "staging",
            "ssh://docker@staging",
            DockerConnectionTransport.SSH,
        ),
        DockerContextDetails(
            "production",
            "tcp://production:2376",
            DockerConnectionTransport.TCP,
        ),
        DockerContextDetails(
            "broken",
            "ssh://docker@broken",
            DockerConnectionTransport.SSH,
        ),
    ]
    menu_state = DockerConnectionMenuState(
        docker_contexts=contexts,
        active_context_name="default",
        selected_context_index=1,
        context_name_being_validated="staging",
        connection_error_messages={"broken": "connection refused"},
    )

    popup_text = _render_popup_text(menu_state)

    assert "localhost" in popup_text
    assert "Local socket" in popup_text
    assert "Active" in popup_text
    assert "> staging" in popup_text
    assert "Checking..." in popup_text
    assert "Unsupported" in popup_text
    assert "Unavailable" in popup_text
    assert "Endpoint: ssh://docker@staging" in popup_text


def test_popup_shows_context_discovery_error_when_list_is_empty() -> None:
    menu_state = DockerConnectionMenuState(
        docker_contexts=[],
        active_context_name="default",
        context_discovery_error_message="Could not read Docker contexts",
    )

    popup_text = _render_popup_text(menu_state)

    assert "No Docker contexts found." in popup_text
    assert "Endpoint: N/A" in popup_text
    assert "Could not read Docker contexts" in popup_text


def test_selected_row_uses_one_style_across_all_columns() -> None:
    contexts = [
        DockerContextDetails(
            "selected",
            "ssh://docker@selected",
            DockerConnectionTransport.SSH,
        ),
        DockerContextDetails(
            "not-selected",
            "ssh://docker@not-selected",
            DockerConnectionTransport.SSH,
        ),
    ]
    menu_state = DockerConnectionMenuState(
        docker_contexts=contexts,
        active_context_name="another-context",
    )

    selected_row = _build_docker_context_row(menu_state, 0)
    unselected_row = _build_docker_context_row(menu_state, 1)

    assert isinstance(selected_row, urwid.AttrMap)
    selected_status = selected_row.original_widget.contents[2][0]
    unselected_status = unselected_row.contents[2][0]
    assert selected_status.get_text() == ("Not checked", [])
    assert unselected_status.get_text() == ("Not checked", [("muted", 11)])
