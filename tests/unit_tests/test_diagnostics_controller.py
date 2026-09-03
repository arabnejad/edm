from __future__ import annotations

from concurrent.futures import Future
from unittest.mock import Mock

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.diagnostics import DockerConnectionStatus
from easy_docker_manager.docker.container_client import (
    DockerContainerClient,
    DockerDaemonDetails,
)
from easy_docker_manager.ui.diagnostics_controller import DiagnosticsController


def test_opening_diagnostics_starts_docker_request_and_applies_its_result() -> None:
    state = TerminalSessionState()
    background_executor = Mock(spec=BackgroundExecutor)
    docker_container_client = Mock(spec=DockerContainerClient)
    completed_future: Future[DockerDaemonDetails] = Future()
    background_executor.submit.return_value = completed_future
    controller = DiagnosticsController(
        state,
        background_executor,
        docker_container_client,
    )

    assert controller.open_diagnostics_popup() is True
    assert state.diagnostics_popup_report is not None
    assert (
        state.diagnostics_popup_report.docker_connection_status
        == DockerConnectionStatus.CHECKING
    )
    assert background_executor.submit.call_args.args == (
        docker_container_client.get_docker_daemon_details,
    )
    completion_callback = background_executor.submit.call_args.kwargs["on_complete"]

    docker_daemon_details = DockerDaemonDetails(
        daemon_version="28.3.3",
        api_version="1.51",
        operating_system="linux",
        architecture="amd64",
    )
    completed_future.set_result(docker_daemon_details)
    assert completion_callback(completed_future) is True
    assert (
        state.diagnostics_popup_report.docker_connection_status
        == DockerConnectionStatus.CONNECTED
    )
    assert state.diagnostics_popup_report.docker_daemon_details == docker_daemon_details


def test_docker_error_is_shown_only_when_diagnostics_is_still_open() -> None:
    state = TerminalSessionState()
    background_executor = Mock(spec=BackgroundExecutor)
    docker_container_client = Mock(spec=DockerContainerClient)
    completed_future: Future[DockerDaemonDetails] = Future()
    background_executor.submit.return_value = completed_future
    controller = DiagnosticsController(
        state,
        background_executor,
        docker_container_client,
    )

    controller.open_diagnostics_popup()
    completion_callback = background_executor.submit.call_args.kwargs["on_complete"]
    completed_future.set_exception(RuntimeError("Docker is unavailable"))
    assert completion_callback(completed_future) is True
    assert state.diagnostics_popup_report is not None
    report = state.diagnostics_popup_report
    assert report.docker_connection_status == DockerConnectionStatus.FAILED
    assert report.docker_connection_error_message == "Docker is unavailable"

    assert controller.close_diagnostics_popup() is True
    assert controller.close_diagnostics_popup() is False


def test_result_is_discarded_after_diagnostics_popup_closes() -> None:
    state = TerminalSessionState()
    background_executor = Mock(spec=BackgroundExecutor)
    docker_container_client = Mock(spec=DockerContainerClient)
    completed_future: Future[DockerDaemonDetails] = Future()
    background_executor.submit.return_value = completed_future
    controller = DiagnosticsController(
        state,
        background_executor,
        docker_container_client,
    )

    controller.open_diagnostics_popup()
    completion_callback = background_executor.submit.call_args.kwargs["on_complete"]
    controller.close_diagnostics_popup()
    completed_future.set_result(DockerDaemonDetails("28.3.3", "1.51", "linux", "amd64"))

    assert completion_callback(completed_future) is False
    assert state.diagnostics_popup_report is None


def test_reopening_diagnostics_ignores_the_previous_docker_result() -> None:
    state = TerminalSessionState()
    background_executor = Mock(spec=BackgroundExecutor)
    docker_container_client = Mock(spec=DockerContainerClient)
    previous_future: Future[DockerDaemonDetails] = Future()
    previous_future.set_running_or_notify_cancel()
    current_future: Future[DockerDaemonDetails] = Future()
    background_executor.submit.side_effect = [previous_future, current_future]
    controller = DiagnosticsController(
        state,
        background_executor,
        docker_container_client,
    )

    controller.open_diagnostics_popup()
    previous_completion_callback = background_executor.submit.call_args.kwargs[
        "on_complete"
    ]
    controller.close_diagnostics_popup()
    controller.open_diagnostics_popup()
    current_completion_callback = background_executor.submit.call_args.kwargs[
        "on_complete"
    ]

    previous_future.set_result(DockerDaemonDetails("old", "old", "old", "old"))
    assert previous_completion_callback(previous_future) is False
    assert state.diagnostics_popup_report is not None
    assert (
        state.diagnostics_popup_report.docker_connection_status
        == DockerConnectionStatus.CHECKING
    )

    current_details = DockerDaemonDetails("29.0", "1.52", "linux", "amd64")
    current_future.set_result(current_details)
    assert current_completion_callback(current_future) is True
    assert state.diagnostics_popup_report.docker_daemon_details == current_details
