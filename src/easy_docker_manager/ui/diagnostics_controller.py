"""Open the diagnostics popup and load Docker details in the background."""

from __future__ import annotations

from concurrent.futures import Future
from typing import Optional

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.diagnostics import create_initial_diagnostics_report
from easy_docker_manager.docker.container_client import (
    DockerContainerClient,
    DockerDaemonDetails,
)


class DiagnosticsController:
    """Manage the diagnostics popup and its Docker version request.

    KeyboardController opens and closes the popup through this class. Opening
    shows application and file details at once, then starts the Docker request
    in BackgroundExecutor so a slow or unavailable daemon cannot freeze the
    terminal. The completion callback updates the report on the UI thread.
    """

    def __init__(
        self,
        state: TerminalSessionState,
        background_executor: BackgroundExecutor,
        docker_container_client: DockerContainerClient,
    ) -> None:
        self.state = state
        self.background_executor = background_executor
        self.docker_container_client = docker_container_client
        self._docker_daemon_details_future: Optional[Future[DockerDaemonDetails]] = None

    def open_diagnostics_popup(self) -> bool:
        """Open the popup and start a Docker version request when needed."""
        if self.state.diagnostics_popup_report is not None:
            return False

        self.state.diagnostics_popup_report = create_initial_diagnostics_report()
        if self._docker_daemon_details_future is None:
            self._docker_daemon_details_future = self.background_executor.submit(
                self.docker_container_client.get_docker_daemon_details,
                on_complete=self._apply_docker_daemon_details_result,
            )
        return True

    def close_diagnostics_popup(self) -> bool:
        """Close the popup while allowing an active Docker request to finish."""
        if self.state.diagnostics_popup_report is None:
            return False
        self.state.diagnostics_popup_report = None
        return True

    def _apply_docker_daemon_details_result(
        self,
        completed_future: Future[DockerDaemonDetails],
    ) -> bool:
        """Store the Docker result if it belongs to the current request.

        If the popup is still closed when Docker answers, the result is
        discarded. Reopening it later starts a fresh request.
        """
        if completed_future is not self._docker_daemon_details_future:
            return False
        self._docker_daemon_details_future = None

        diagnostics_report = self.state.diagnostics_popup_report
        if diagnostics_report is None:
            return False
        try:
            docker_daemon_details = completed_future.result()
        except Exception as exc:
            diagnostics_report.record_failed_docker_connection(exc)
        else:
            diagnostics_report.record_successful_docker_connection(
                docker_daemon_details
            )
        return True


__all__ = ["DiagnosticsController"]
