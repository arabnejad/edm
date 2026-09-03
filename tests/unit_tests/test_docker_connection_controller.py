from __future__ import annotations

from concurrent.futures import Future
from unittest.mock import Mock

import pytest
from docker import DockerClient

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.docker_connections import (
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
    docker_manager.is_container_lifecycle_action_in_progress = False
    context_reader = Mock(spec=DockerContextReader)
    context_reader.list_configured_docker_contexts.return_value = contexts
    docker_sdk_container_client = Mock(spec=DockerSDKContainerClient)
    create_validated_docker_client_for_context = Mock(spec=lambda: DockerClient)
    controller = DockerConnectionController(
        state,
        AppConfig(docker_request_timeout=3.5),
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

    menu_state = state.docker_connection_menu_state
    assert menu_state is not None
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
    validation_future: Future[DockerClient] = Future()
    background_executor.submit.return_value = validation_future
    controller.open_docker_connection_menu()

    assert controller.handle_menu_keypress("down")
    assert controller.handle_menu_keypress("enter")

    assert background_executor.submit.call_args.args == (
        create_validated_client,
        remote_context,
        3.5,
    )
    assert state.docker_connection_menu_state is not None
    assert (
        state.docker_connection_menu_state.context_name_being_validated
        == remote_context.context_name
    )


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
    validation_future: Future[DockerClient] = Future()
    background_executor.submit.return_value = validation_future
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")
    controller.handle_menu_keypress("enter")
    completion_callback = background_executor.submit.call_args.kwargs["on_complete"]

    validation_future.set_result(validated_docker_client)
    assert completion_callback(validation_future)

    docker_manager.reset_after_docker_context_change.assert_called_once_with()
    sdk_client.switch_docker_connection.assert_called_once_with(validated_docker_client)
    docker_manager.start_running_container_list_refresh.assert_called_once_with(
        force=True
    )
    assert state.active_docker_context == remote_context
    assert state.docker_connection_menu_state is None
    assert state.status_message == 'Connecting to Docker context "staging"...'


def test_failed_validation_keeps_the_current_context() -> None:
    local_context = _local_context()
    remote_context = _remote_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, background_executor, docker_manager, sdk_client, _ = _create_controller(
        state,
        [local_context, remote_context],
    )
    validation_future: Future[DockerClient] = Future()
    background_executor.submit.return_value = validation_future
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")
    controller.handle_menu_keypress("enter")
    completion_callback = background_executor.submit.call_args.kwargs["on_complete"]

    validation_future.set_exception(RuntimeError("SSH authentication failed"))
    assert completion_callback(validation_future)

    assert state.active_docker_context == local_context
    assert state.docker_connection_menu_state is not None
    assert state.docker_connection_menu_state.connection_error_messages == {
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

    assert state.docker_connection_menu_state is not None
    assert (
        "CA certificate"
        in state.docker_connection_menu_state.connection_error_messages["production"]
    )
    background_executor.submit.assert_not_called()


def test_context_change_waits_for_running_container_action() -> None:
    local_context = _local_context()
    remote_context = _remote_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, background_executor, docker_manager, _, _ = _create_controller(
        state,
        [local_context, remote_context],
    )
    docker_manager.is_container_lifecycle_action_in_progress = True
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")

    assert controller.handle_menu_keypress("enter")

    assert state.docker_connection_menu_state is not None
    assert (
        "Wait for"
        in state.docker_connection_menu_state.connection_error_messages["staging"]
    )
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

    assert state.docker_connection_menu_state is not None
    assert state.docker_connection_menu_state.docker_contexts == []
    assert (
        "invalid Docker config"
        in state.docker_connection_menu_state.context_discovery_error_message
    )


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

    assert state.docker_connection_menu_state is None
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

    assert state.docker_connection_menu_state is not None
    assert (
        "unavailable"
        in state.docker_connection_menu_state.connection_error_messages["staging"]
    )
    background_executor.submit.assert_not_called()


def test_menu_ignores_keys_while_context_validation_is_running() -> None:
    local_context = _local_context()
    remote_context = _remote_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, background_executor, _, _, _ = _create_controller(
        state,
        [local_context, remote_context],
    )
    background_executor.submit.return_value = Future()
    controller.open_docker_connection_menu()
    controller.handle_menu_keypress("down")
    controller.handle_menu_keypress("enter")

    assert not controller.handle_menu_keypress("esc")
    assert state.docker_connection_menu_state is not None


def test_old_context_validation_completion_is_ignored() -> None:
    local_context = _local_context()
    state = TerminalSessionState(active_docker_context=local_context)
    controller, _, _, _, _ = _create_controller(state, [local_context])

    assert not controller._apply_docker_context_validation_result(
        local_context,
        Future(),
    )
