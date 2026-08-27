from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.tab_export.definitions import (
    TabExportMenuField,
    TabExportPhase,
    TabExportScope,
)
from easy_docker_manager.tab_export.writer import (
    ExportFileAlreadyExistsError,
    TabExportFileError,
    TabExportWriter,
)
from easy_docker_manager.tabs.tab_text_filter import TabTextFilter
from easy_docker_manager.ui.tab_export_controller import TabExportController


@dataclass
class TabExportControllerTestSetup:
    tab_export_controller: TabExportController
    background_executor: Mock
    tab_export_writer: Mock
    export_future: Future


@pytest.fixture
def tab_export_controller_factory(tmp_path: Path):
    def create_controller(state: TerminalSessionState) -> TabExportControllerTestSetup:
        background_executor = Mock(spec=BackgroundExecutor)
        tab_export_writer = Mock(spec=TabExportWriter)
        export_future: Future = Future()
        background_executor.submit.return_value = export_future
        controller = TabExportController(
            state,
            TabTextFilter(),
            background_executor,
            tab_export_writer,
            tmp_path,
        )
        return TabExportControllerTestSetup(
            controller,
            background_executor,
            tab_export_writer,
            export_future,
        )

    return create_controller


def _cache_active_tab_content(
    state: TerminalSessionState, content: str = "logs"
) -> None:
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = content


def test_export_menu_uses_launch_directory_and_tab_extension(
    tab_export_controller_factory,
    session_state_factory,
    tmp_path: Path,
) -> None:
    state = session_state_factory()
    _cache_active_tab_content(state)
    controller = tab_export_controller_factory(state).tab_export_controller

    assert controller.open_tab_export_menu()

    menu_state = state.tab_export_menu_state
    assert menu_state is not None
    export_path = Path(menu_state.file_path)
    assert export_path.parent == tmp_path
    assert export_path.name.startswith("web-logs-")
    assert export_path.suffix == ".log"


def test_export_menu_reports_missing_selection_and_unloaded_content(
    tab_export_controller_factory,
    session_state_factory,
) -> None:
    empty_state = TerminalSessionState()
    empty_controller = tab_export_controller_factory(empty_state).tab_export_controller
    assert empty_controller.open_tab_export_menu()
    assert empty_state.status_message == "Select a container before exporting."

    state = session_state_factory(tab=TabName.CONFIG)
    controller = tab_export_controller_factory(state).tab_export_controller
    assert controller.open_tab_export_menu()
    assert state.tab_export_menu_state is None
    assert state.status_message == (
        "Wait for Config to finish loading before exporting."
    )


def test_current_view_export_uses_filtered_log_lines(
    tab_export_controller_factory,
    session_state_factory,
    tmp_path: Path,
) -> None:
    state = session_state_factory()
    _cache_active_tab_content(state, "INFO ready\nERROR failed")
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_search_queries[container_tab_key] = "ERROR"
    test_setup = tab_export_controller_factory(state)
    test_setup.tab_export_controller.open_tab_export_menu()
    menu_state = state.tab_export_menu_state
    assert menu_state is not None
    menu_state.file_path = "visible.log"

    assert test_setup.tab_export_controller.handle_menu_keypress("enter")

    worker_function, export_request = (
        test_setup.background_executor.submit.call_args.args
    )
    assert worker_function is test_setup.tab_export_writer.export_text
    assert export_request.target_path == tmp_path / "visible.log"
    assert export_request.tab_text_snapshot == "ERROR failed"
    assert not export_request.allow_overwrite
    assert menu_state.phase == TabExportPhase.WRITING


def test_full_tab_export_keeps_all_cached_text(
    tab_export_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    _cache_active_tab_content(state, "INFO ready\nERROR failed")
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_search_queries[container_tab_key] = "ERROR"
    test_setup = tab_export_controller_factory(state)
    test_setup.tab_export_controller.open_tab_export_menu()
    menu_state = state.tab_export_menu_state
    assert menu_state is not None
    menu_state.scope = TabExportScope.FULL_TAB
    menu_state.phase = TabExportPhase.CONFIRMING_OVERWRITE

    test_setup.tab_export_controller.handle_menu_keypress("enter")

    export_request = test_setup.background_executor.submit.call_args.args[1]
    assert export_request.tab_text_snapshot == "INFO ready\nERROR failed"
    assert export_request.allow_overwrite


def test_export_menu_edits_path_field_and_scope(
    tab_export_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    _cache_active_tab_content(state, "A=1")
    controller = tab_export_controller_factory(state).tab_export_controller
    controller.open_tab_export_menu()
    menu_state = state.tab_export_menu_state
    assert menu_state is not None
    menu_state.file_path = "out.txt"
    menu_state.file_path_cursor_index = 3

    assert controller.handle_menu_keypress("backspace")
    assert menu_state.file_path == "ou.txt"
    assert controller.handle_menu_keypress("down")
    assert menu_state.selected_field == TabExportMenuField.SCOPE
    assert controller.handle_menu_keypress("right")
    assert menu_state.scope == TabExportScope.FULL_TAB


def test_export_path_editor_handles_navigation_deletion_and_insertion(
    tab_export_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    _cache_active_tab_content(state)
    controller = tab_export_controller_factory(state).tab_export_controller
    controller.open_tab_export_menu()
    menu_state = state.tab_export_menu_state
    assert menu_state is not None
    menu_state.file_path = "abc"
    menu_state.file_path_cursor_index = 1

    assert controller.handle_menu_keypress("right")
    assert controller.handle_menu_keypress("home")
    assert not controller.handle_menu_keypress("backspace")
    assert controller.handle_menu_keypress("end")
    assert not controller.handle_menu_keypress("delete")
    assert controller.handle_menu_keypress("left")
    assert controller.handle_menu_keypress("delete")
    assert menu_state.file_path == "ab"
    assert controller.handle_menu_keypress("q")
    assert menu_state.file_path == "abq"
    assert not controller.handle_menu_keypress("f1")


def test_export_menu_rejects_unavailable_field_changes(
    tab_export_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    controller = tab_export_controller_factory(state).tab_export_controller
    assert not controller.handle_menu_keypress("down")
    assert not controller.handle_menu_keypress("right")
    assert not controller.handle_menu_keypress("esc")

    _cache_active_tab_content(state)
    controller.open_tab_export_menu()
    menu_state = state.tab_export_menu_state
    assert menu_state is not None
    assert not controller.open_tab_export_menu()
    assert not controller.handle_menu_keypress("up")
    assert controller.handle_menu_keypress("down")
    assert controller.handle_menu_keypress("right")
    assert controller.handle_menu_keypress("left")
    assert menu_state.scope == TabExportScope.CURRENT_VIEW

    menu_state.phase = TabExportPhase.WRITING
    assert not controller.handle_menu_keypress("up")
    assert not controller.handle_menu_keypress("right")
    assert not controller.handle_menu_keypress("x")
    assert not controller.handle_menu_keypress("esc")


def test_export_path_editor_enforces_its_length_limit(
    tab_export_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    _cache_active_tab_content(state)
    controller = tab_export_controller_factory(state).tab_export_controller
    controller.open_tab_export_menu()
    menu_state = state.tab_export_menu_state
    assert menu_state is not None
    menu_state.file_path = "x" * controller.MAX_EXPORT_PATH_CHARACTERS
    menu_state.file_path_cursor_index = len(menu_state.file_path)

    assert controller.handle_menu_keypress("y")
    assert "cannot exceed" in menu_state.error_message


def test_submit_export_validates_path_cache_and_active_export(
    tab_export_controller_factory,
    session_state_factory,
    monkeypatch,
) -> None:
    state = session_state_factory()
    test_setup = tab_export_controller_factory(state)
    controller = test_setup.tab_export_controller
    assert not controller.handle_menu_keypress("enter")

    _cache_active_tab_content(state)
    controller.open_tab_export_menu()
    menu_state = state.tab_export_menu_state
    assert menu_state is not None
    menu_state.file_path = " "
    assert controller.handle_menu_keypress("enter")
    assert menu_state.error_message == "Enter a file path before exporting."

    menu_state.file_path = "output.txt"
    monkeypatch.setattr(Path, "resolve", Mock(side_effect=OSError("bad path")))
    assert controller.handle_menu_keypress("enter")
    assert menu_state.error_message == "Invalid export path: bad path"


def test_submit_export_reports_removed_cache_and_active_file_write(
    tab_export_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    _cache_active_tab_content(state)
    test_setup = tab_export_controller_factory(state)
    controller = test_setup.tab_export_controller
    controller.open_tab_export_menu()
    menu_state = state.tab_export_menu_state
    assert menu_state is not None

    state.tab_content_cache.clear()
    assert controller.handle_menu_keypress("enter")
    assert menu_state.error_message.startswith("This tab is no longer loaded")

    _cache_active_tab_content(state)
    controller._active_export_future = Future()
    assert controller.handle_menu_keypress("enter")
    assert menu_state.error_message.startswith("Another export is still running")


def test_successful_export_closes_the_matching_menu(
    tab_export_controller_factory,
    session_state_factory,
    tmp_path: Path,
) -> None:
    state = session_state_factory()
    _cache_active_tab_content(state)
    test_setup = tab_export_controller_factory(state)
    test_setup.tab_export_controller.open_tab_export_menu()
    menu_state = state.tab_export_menu_state
    assert menu_state is not None
    menu_state.file_path = "saved.log"
    test_setup.tab_export_controller.handle_menu_keypress("enter")
    target_path = tmp_path / "saved.log"
    test_setup.export_future.set_result(target_path)
    completion_callback = test_setup.background_executor.submit.call_args.kwargs[
        "on_complete"
    ]

    assert completion_callback(test_setup.export_future)
    assert state.tab_export_menu_state is None
    assert state.status_message == f"Exported to {target_path}"


def test_existing_export_file_opens_overwrite_confirmation(
    tab_export_controller_factory,
    session_state_factory,
    tmp_path: Path,
) -> None:
    state = session_state_factory()
    _cache_active_tab_content(state)
    test_setup = tab_export_controller_factory(state)
    test_setup.tab_export_controller.open_tab_export_menu()
    menu_state = state.tab_export_menu_state
    assert menu_state is not None
    menu_state.file_path = "existing.log"
    test_setup.tab_export_controller.handle_menu_keypress("enter")
    target_path = tmp_path / "existing.log"
    test_setup.export_future.set_exception(ExportFileAlreadyExistsError(target_path))
    completion_callback = test_setup.background_executor.submit.call_args.kwargs[
        "on_complete"
    ]

    assert completion_callback(test_setup.export_future)
    assert menu_state.phase == TabExportPhase.CONFIRMING_OVERWRITE
    assert test_setup.tab_export_controller.handle_menu_keypress("esc")
    assert menu_state.phase == TabExportPhase.EDITING


@pytest.mark.parametrize(
    "export_error",
    [
        TabExportFileError(Path("output.log"), "permission denied"),
        RuntimeError("unexpected failure"),
    ],
)
def test_export_failure_keeps_the_menu_open_with_an_error(
    tab_export_controller_factory,
    session_state_factory,
    export_error: Exception,
) -> None:
    state = session_state_factory()
    _cache_active_tab_content(state)
    test_setup = tab_export_controller_factory(state)
    test_setup.tab_export_controller.open_tab_export_menu()
    menu_state = state.tab_export_menu_state
    assert menu_state is not None
    test_setup.tab_export_controller.handle_menu_keypress("enter")
    test_setup.export_future.set_exception(export_error)
    completion_callback = test_setup.background_executor.submit.call_args.kwargs[
        "on_complete"
    ]

    assert completion_callback(test_setup.export_future)
    assert state.tab_export_menu_state is menu_state
    assert menu_state.phase == TabExportPhase.EDITING
    assert str(export_error) in menu_state.error_message


def test_stale_export_completion_is_ignored(
    tab_export_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = tab_export_controller_factory(state)
    test_setup.tab_export_controller._active_export_future = Future()

    assert not test_setup.tab_export_controller._apply_tab_export_result(
        state.selected_container_tab_key,
        Path("old.log"),
        Future(),
    )


def test_default_export_file_name_removes_unsafe_characters() -> None:
    file_name = TabExportController._build_default_export_file_name(
        "../web api!",
        TabName.CONFIG,
    )

    assert file_name.startswith("web_api-config-")
    assert file_name.endswith(".txt")
