from __future__ import annotations

from concurrent.futures import Future
from unittest.mock import Mock

import pytest
from docker import DockerClient

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.docker_connections import (
    DockerConnectionMenuState,
    DockerConnectionTransport,
    DockerContextDetails,
)
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.docker_contexts import DockerContextReader
from easy_docker_manager.docker.docker_sdk_container_client import (
    DockerSDKContainerClient,
)
from easy_docker_manager.ui.docker_connection_controller import (
    DockerConnectionController,
)


def _local_context() -> DockerContextDetails:
    return DockerContextDetails(
        "default",
        "unix:///var/run/docker.sock",
        DockerConnectionTransport.LOCAL,
    )


def _remote_context() -> DockerContextDetails:
    return DockerContextDetails(
        "staging",
        "ssh://docker@staging",
        DockerConnectionTransport.SSH,
    )


def _remote_tls_context() -> DockerContextDetails:
    return DockerContextDetails(
        "production",
        "tcp://production.example.com:2376",
        DockerConnectionTransport.TCP,
        has_required_tls_certificate_files=True,
        verifies_tls_server_certificate=True,
    )


def _get_open_docker_connection_menu(
    state: TerminalSessionState,
) -> DockerConnectionMenuState:
    active_popup = state.active_popup
    assert isinstance(active_popup, DockerConnectionMenuState)
    return active_popup


def _create_controller(
    state: TerminalSessionState,
    contexts: list[DockerContextDetails],
) -> tuple[
    DockerConnectionController,
    Mock,
    Mock,
    Mock,
    Mock,
]:
    background_executor = Mock(spec=BackgroundExecutor)
    docker_manager = Mock(spec=DockerManager)
    docker_manager.is_container_action_in_progress = False
    context_reader = Mock(spec=DockerContextReader)
    context_reader.list_configured_docker_contexts.return_value = contexts
    docker_sdk_container_client = Mock(spec=DockerSDKContainerClient)
    create_validated_docker_client_for_context = Mock(spec=lambda: DockerClient)
    controller = DockerConnectionController(
        state,
        AppConfig(docker_request_timeout_seconds=3.5),
        background_executor,
        docker_manager,
        context_reader,
        docker_sdk_container_client,
        create_validated_docker_client_for_context=(
            create_validated_docker_client_for_context
        ),
    )
    return (
        controller,
        background_executor,
        docker_manager,
        docker_sdk_container_client,
        create_validated_docker_client_for_context,
    )


def test_open_menu_selects_the_active_context() -> None:
    local_context = _local_context()
    remote_context = _remote_context()
    state = TerminalSessionState(active_docker_context=remote_context)
    controller, _, _, _, _ = _create_controller(
        state,
        [local_context, remote_context],
    )

    assert controller.open_docker_connection_menu()

    menu_state = _get_open_docker_connection_menu(state)
    assert menu_state.selected_context_index == 1
    assert menu_state.active_context_name == "staging"


@pytest.mark.parametrize("remote_context", [_remote_context(), _remote_tls_context()])
def test_enter_creates_and_validates_selected_context_client_in_background(
    remote_context: DockerContextDetails,
) -> None:
    local_context = _local_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, background_executor, _, _, create_validated_client = _create_controller(
        state,
        [local_context, remote_context],
    )
    docker_context_validation_future: Future[DockerClient] = Future()
    background_executor.submit.return_value = docker_context_validation_future
    controller.open_docker_connection_menu()

    assert controller.handle_menu_keypress("down")
    assert controller.handle_menu_keypress("enter")

    assert background_executor.submit.call_args.args == (
        create_validated_client,
        remote_context,
        3.5,
    )
    menu_state = _get_open_docker_connection_menu(state)
    assert menu_state.context_name_being_validated == remote_context.context_name


def test_successful_validation_reuses_client_and_refreshes_containers() -> None:
    local_context = _local_context()
    remote_context = _remote_context()
    state = TerminalSessionState(active_docker_context=local_context)
    state.status_message = "1 running containers"
    controller, background_executor, docker_manager, sdk_client, _ = _create_controller(
        state,
        [local_context, remote_context],
    )
    validated_docker_client = Mock(spec=DockerClient)
    docker_context_validation_future: Future[DockerClient] = Future()
    background_executor.submit.return_value = docker_context_validation_future
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")
    controller.handle_menu_keypress("enter")
    completion_callback = background_executor.submit.call_args.kwargs["on_complete"]

    docker_context_validation_future.set_result(validated_docker_client)
    assert completion_callback(docker_context_validation_future)

    docker_manager.reset_after_docker_context_change.assert_called_once_with()
    sdk_client.switch_docker_connection.assert_called_once_with(validated_docker_client)
    docker_manager.start_container_list_refresh.assert_called_once_with(force=True)
    assert state.active_docker_context == remote_context
    assert state.active_popup is None
    assert state.status_message == 'Connecting to Docker context "staging"...'


def test_failed_validation_keeps_the_current_context() -> None:
    local_context = _local_context()
    remote_context = _remote_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, background_executor, docker_manager, sdk_client, _ = _create_controller(
        state,
        [local_context, remote_context],
    )
    docker_context_validation_future: Future[DockerClient] = Future()
    background_executor.submit.return_value = docker_context_validation_future
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")
    controller.handle_menu_keypress("enter")
    completion_callback = background_executor.submit.call_args.kwargs["on_complete"]

    docker_context_validation_future.set_exception(
        RuntimeError("SSH authentication failed")
    )
    assert completion_callback(docker_context_validation_future)

    assert state.active_docker_context == local_context
    menu_state = _get_open_docker_connection_menu(state)
    assert menu_state.connection_error_messages == {
        "staging": "SSH authentication failed"
    }
    docker_manager.reset_after_docker_context_change.assert_not_called()
    sdk_client.switch_docker_connection.assert_not_called()


def test_tcp_context_without_certificates_explains_what_is_missing() -> None:
    local_context = _local_context()
    tcp_context = DockerContextDetails(
        "production",
        "tcp://production:2376",
        DockerConnectionTransport.TCP,
    )
    state = TerminalSessionState(active_docker_context=local_context)
    controller, background_executor, _, _, _ = _create_controller(
        state,
        [local_context, tcp_context],
    )
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")

    assert controller.handle_menu_keypress("enter")

    menu_state = _get_open_docker_connection_menu(state)
    assert "CA certificate" in menu_state.connection_error_messages["production"]
    background_executor.submit.assert_not_called()


def test_context_change_waits_for_running_container_action() -> None:
    local_context = _local_context()
    remote_context = _remote_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, background_executor, docker_manager, _, _ = _create_controller(
        state,
        [local_context, remote_context],
    )
    docker_manager.is_container_action_in_progress = True
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")

    assert controller.handle_menu_keypress("enter")

    menu_state = _get_open_docker_connection_menu(state)
    assert "Wait for" in menu_state.connection_error_messages["staging"]
    background_executor.submit.assert_not_called()


def test_open_menu_reports_context_discovery_failure() -> None:
    local_context = _local_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, _, _, _, _ = _create_controller(state, [])
    controller.docker_context_reader.list_configured_docker_contexts.side_effect = (
        RuntimeError("invalid Docker config")
    )

    assert controller.open_docker_connection_menu()
    assert not controller.open_docker_connection_menu()

    menu_state = _get_open_docker_connection_menu(state)
    assert menu_state.docker_contexts == []
    assert "invalid Docker config" in menu_state.context_discovery_error_message


def test_menu_closes_with_escape_and_ignores_keys_after_closing() -> None:
    local_context = _local_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, _, _, _, _ = _create_controller(state, [local_context])
    controller.open_docker_connection_menu()

    assert not controller.handle_menu_keypress("up")
    assert not controller.handle_menu_keypress("unknown")
    assert controller.handle_menu_keypress("esc")
    assert not controller.handle_menu_keypress("esc")


def test_enter_closes_menu_when_selected_context_is_already_active() -> None:
    local_context = _local_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, background_executor, _, _, _ = _create_controller(
        state,
        [local_context],
    )
    controller.open_docker_connection_menu()

    assert controller.handle_menu_keypress("enter")

    assert state.active_popup is None
    background_executor.submit.assert_not_called()


def test_enter_does_nothing_when_context_list_is_empty() -> None:
    state = TerminalSessionState(active_docker_context=_local_context())
    controller, background_executor, _, _, _ = _create_controller(state, [])
    controller.open_docker_connection_menu()

    assert not controller.handle_menu_keypress("enter")
    background_executor.submit.assert_not_called()


def test_context_switch_is_unavailable_for_custom_docker_client() -> None:
    local_context = _local_context()
    remote_context = _remote_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, background_executor, _, _, _ = _create_controller(
        state,
        [local_context, remote_context],
    )
    controller.docker_sdk_container_client = None
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")

    assert controller.handle_menu_keypress("enter")

    menu_state = _get_open_docker_connection_menu(state)
    assert "unavailable" in menu_state.connection_error_messages["staging"]
    background_executor.submit.assert_not_called()


def test_escape_closes_the_popup_while_a_check_is_pending() -> None:
    local_context = _local_context()
    remote_context = _remote_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, background_executor, _, _, _ = _create_controller(
        state,
        [local_context, remote_context],
    )
    docker_context_validation_future: Future[DockerClient] = Future()
    background_executor.submit.return_value = docker_context_validation_future
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")
    controller.handle_menu_keypress("enter")

    completion_callback = background_executor.submit.call_args.kwargs["on_complete"]

    for key in ("up", "down", "enter", "unknown"):
        assert not controller.handle_menu_keypress(key)
    assert _get_open_docker_connection_menu(state).selected_context_index == 1
    background_executor.submit.assert_called_once()

    assert controller.handle_menu_keypress("esc")
    assert state.active_popup is None

    unused_client = Mock(spec=DockerClient)
    docker_context_validation_future.set_result(unused_client)
    assert not completion_callback(docker_context_validation_future)
    unused_client.close.assert_called_once_with()
    assert state.active_docker_context == local_context


@pytest.mark.parametrize("check_succeeds", [False, True])
def test_reopened_popup_ignores_the_previous_check(
    check_succeeds: bool,
) -> None:
    local_context = _local_context()
    remote_context = _remote_context()
    state = TerminalSessionState(active_docker_context=local_context)
    state.status_message = "Connected to localhost"
    controller, background_executor, docker_manager, sdk_client, _ = _create_controller(
        state,
        [local_context, remote_context],
    )
    docker_context_validation_future: Future[DockerClient] = Future()
    assert docker_context_validation_future.set_running_or_notify_cancel()
    background_executor.submit.return_value = docker_context_validation_future
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")
    controller.handle_menu_keypress("enter")
    completion_callback = background_executor.submit.call_args.kwargs["on_complete"]

    assert controller.handle_menu_keypress("esc")
    assert state.active_popup is None
    assert docker_context_validation_future.running()
    assert controller.open_docker_connection_menu()
    new_menu = _get_open_docker_connection_menu(state)

    unused_client = Mock(spec=DockerClient)
    if check_succeeds:
        docker_context_validation_future.set_result(unused_client)
    else:
        docker_context_validation_future.set_exception(
            RuntimeError("SSH authentication failed")
        )

    assert not completion_callback(docker_context_validation_future)

    if check_succeeds:
        unused_client.close.assert_called_once_with()
    else:
        unused_client.close.assert_not_called()
    assert state.active_popup is new_menu
    assert state.active_docker_context == local_context
    assert state.status_message == "Connected to localhost"
    assert new_menu.connection_error_messages == {}
    assert new_menu.context_name_being_validated is None
    docker_manager.reset_after_docker_context_change.assert_not_called()
    docker_manager.start_container_list_refresh.assert_not_called()
    sdk_client.switch_docker_connection.assert_not_called()


def test_dismissed_check_does_not_interrupt_a_new_connection_check() -> None:
    local_context = _local_context()
    remote_context = _remote_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, background_executor, docker_manager, sdk_client, _ = _create_controller(
        state,
        [local_context, remote_context],
    )
    old_future: Future[DockerClient] = Future()
    assert old_future.set_running_or_notify_cancel()
    new_future: Future[DockerClient] = Future()
    background_executor.submit.side_effect = [old_future, new_future]
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")
    controller.handle_menu_keypress("enter")
    old_callback = background_executor.submit.call_args.kwargs["on_complete"]

    controller.handle_menu_keypress("esc")
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")
    controller.handle_menu_keypress("enter")
    new_callback = background_executor.submit.call_args.kwargs["on_complete"]
    new_menu = _get_open_docker_connection_menu(state)

    old_client = Mock(spec=DockerClient)
    old_future.set_result(old_client)
    assert not old_callback(old_future)

    old_client.close.assert_called_once_with()
    assert state.active_popup is new_menu
    assert new_menu.context_name_being_validated == "staging"
    sdk_client.switch_docker_connection.assert_not_called()

    new_client = Mock(spec=DockerClient)
    new_future.set_result(new_client)
    assert new_callback(new_future)

    sdk_client.switch_docker_connection.assert_called_once_with(new_client)
    docker_manager.start_container_list_refresh.assert_called_once_with(force=True)
    new_client.close.assert_not_called()
    assert state.active_docker_context == remote_context
    assert state.active_popup is None


def test_unused_client_close_failure_does_not_break_the_interface() -> None:
    local_context = _local_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, _, _, _, _ = _create_controller(state, [local_context])

    unused_client = Mock(spec=DockerClient)
    unused_client.close.side_effect = RuntimeError("Connection already closed")
    completed_future: Future[DockerClient] = Future()
    completed_future.set_result(unused_client)

    assert not controller._apply_docker_context_validation_result(
        local_context,
        completed_future,
    )
    unused_client.close.assert_called_once_with()
    assert state.active_docker_context == local_context
