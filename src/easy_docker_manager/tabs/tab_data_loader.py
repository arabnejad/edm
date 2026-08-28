"""Load Docker data and turn it into text for the container detail tabs."""

from __future__ import annotations

from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.containers import ContainerProcessTable
from easy_docker_manager.core.log_text import apply_limits_to_log_content
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.docker.container_client import (
    ContainerLogsUnavailableError,
    DockerContainerClient,
)
from easy_docker_manager.tabs.config_tab_formatter import (
    format_container_inspection_data,
)
from easy_docker_manager.tabs.resource_stats_formatter import (
    format_container_resource_stats_tab_text,
)


class ContainerTabTextLoader:
    """Load display text for a container's Logs, Env, Config, Stats, or Top tab.

    SelectedTabContentLoader runs this in a worker thread. It loads the Docker
    data needed by the requested tab and returns the text shown in that tab.
    This class does not update session state, caches, or Urwid widgets.
    """

    def __init__(
        self,
        docker_container_client: DockerContainerClient,
        app_config: AppConfig,
    ) -> None:
        self.docker_container_client = docker_container_client
        self.app_config = app_config

    def load_tab_text(self, container_id: str, tab_name: TabName) -> str:
        """Load and format the text for one container tab."""
        if tab_name == TabName.LOGS:
            return self._load_initial_container_logs_tab_text(container_id)
        if tab_name == TabName.ENV:
            return self._load_container_environment_tab_text(container_id)
        if tab_name == TabName.CONFIG:
            return self._load_container_config_tab_text(container_id)
        if tab_name == TabName.STATS:
            return self._load_container_resource_stats_tab_text(container_id)
        if tab_name == TabName.TOP:
            return self._load_container_top_tab_text(container_id)
        raise ValueError(f"Unsupported tab: {tab_name!r}")

    def _load_initial_container_logs_tab_text(self, container_id: str) -> str:
        """Load and limit the text shown when the container's Logs tab opens."""
        content = self.docker_container_client.get_container_logs(
            container_id,
            self.app_config.initial_log_tail_lines,
        )
        return apply_limits_to_log_content(
            content,
            max_lines=self.app_config.max_log_lines,
            max_line_chars=self.app_config.max_log_line_chars,
        )

    def _load_container_environment_tab_text(self, container_id: str) -> str:
        """Load, sort, and format text for the container's Env tab."""
        environment_variables = (
            self.docker_container_client.get_container_environment_variables(
                container_id
            )
        )
        return "\n".join(
            f"{name}={value}" for name, value in sorted(environment_variables.items())
        )

    def _load_container_config_tab_text(self, container_id: str) -> str:
        """Load inspection data and format text for the container's Config tab."""
        inspection_data = self.docker_container_client.get_container_inspection_data(
            container_id
        )
        return format_container_inspection_data(inspection_data)

    def _load_container_top_tab_text(self, container_id: str) -> str:
        """Load Docker's process table and format text for the container's Top tab."""
        process_table = self.docker_container_client.get_container_top_process_table(
            container_id
        )
        return _format_process_table(process_table)

    def _load_container_resource_stats_tab_text(self, container_id: str) -> str:
        """Load and format one current sample for the container's Stats tab."""
        resource_stats_snapshot = (
            self.docker_container_client.get_container_resource_stats(container_id)
        )
        return format_container_resource_stats_tab_text(
            resource_stats_snapshot,
            self.app_config.tab_refresh_interval,
        )


def _format_process_table(processes: ContainerProcessTable) -> str:
    """Join Docker process columns and rows into Top tab lines."""
    lines = [" ".join(processes.columns)] if processes.columns else []
    lines.extend(" ".join(row) for row in processes.rows)
    return "\n".join(lines)


def build_logs_unavailable_error_message(
    logs_unavailable_error: ContainerLogsUnavailableError,
) -> str:
    """Build the message shown when Docker cannot read a container's logs."""
    return (
        "Logs unavailable: this container uses Docker logging "
        "driver "
        f"'{logs_unavailable_error.logging_driver_name}', so Docker cannot read "
        "logs for it. "
        "Enable a readable logging driver such as 'json-file', 'local', "
        "or 'journald' to view logs here."
    )


__all__ = [
    "ContainerTabTextLoader",
    "build_logs_unavailable_error_message",
]
