"""Load and prepare text for each container detail tab."""

from __future__ import annotations

from abc import ABC, abstractmethod

from easy_docker_manager.core import AppConfig, ContainerProcessTable
from easy_docker_manager.core.log_text import trim_log_text
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.docker.base import ContainerDataSource, LogsUnavailableError
from easy_docker_manager.tabs.config_tab_formatter import format_container_config


class TabDataProvider(ABC):
    """Load the text for one detail tab: Logs, Env, Config, or Top.

    TabDataLoader calls the matching provider on a worker thread whenever the
    scheduler needs content for a selected container tab.
    """

    @abstractmethod
    def load_text(self, container_id: str) -> str:
        """Load the text shown for one container."""


class LogsTabDataProvider(TabDataProvider):
    """Load the first block of text shown in the Logs tab."""

    def __init__(
        self, container_data_source: ContainerDataSource, app_config: AppConfig
    ) -> None:
        self.container_data_source = container_data_source
        self.app_config = app_config

    def load_text(self, container_id: str) -> str:
        """Load the configured number of recent lines for the Logs tab.

        The scheduler uses this only for the first load. Later log updates use
        the separate incremental polling path.
        """
        content = self.container_data_source.get_logs(
            container_id, self.app_config.log_tail
        )
        return trim_log_text(
            content,
            max_lines=self.app_config.max_log_lines,
            max_line_chars=self.app_config.max_log_line_chars,
        )


class EnvTabDataProvider(TabDataProvider):
    """Load and sort the environment values shown in the Env tab."""

    def __init__(self, container_data_source: ContainerDataSource) -> None:
        self.container_data_source = container_data_source

    def load_text(self, container_id: str) -> str:
        """Load environment variables and sort them by name for display."""
        environment_variables = self.container_data_source.get_environment_variables(
            container_id
        )
        if not environment_variables:
            return ""
        return "\n".join(
            f"{name}={value}" for name, value in sorted(environment_variables.items())
        )


class ConfigTabDataProvider(TabDataProvider):
    """Load Docker inspection data and format the Config tab."""

    def __init__(self, container_data_source: ContainerDataSource) -> None:
        self.container_data_source = container_data_source

    def load_text(self, container_id: str) -> str:
        """Load and group the container configuration for display."""
        config_data = self.container_data_source.get_docker_inspection_data(
            container_id
        )
        return format_container_config(config_data)


class TopTabDataProvider(TabDataProvider):
    """Load and format the container process list for the Top tab."""

    def __init__(self, container_data_source: ContainerDataSource) -> None:
        self.container_data_source = container_data_source

    def load_text(self, container_id: str) -> str:
        """Load the container process list and convert its rows to text."""
        processes = self.container_data_source.get_process_list(container_id)
        return _format_process_list(processes)


class TabDataLoader:
    """Choose the provider that loads a requested container tab.

    The scheduler calls this on a worker thread. It maps each TabName to a
    TabDataProvider and returns text only; it does not update UI state or caches.
    """

    def __init__(
        self,
        container_data_source: ContainerDataSource,
        app_config: AppConfig,
    ) -> None:
        """Create the provider used for each supported tab."""
        self._providers_by_tab: dict[TabName, TabDataProvider] = {
            TabName.LOGS: LogsTabDataProvider(container_data_source, app_config),
            TabName.ENV: EnvTabDataProvider(container_data_source),
            TabName.CONFIG: ConfigTabDataProvider(container_data_source),
            TabName.TOP: TopTabDataProvider(container_data_source),
        }

    def load_tab_text(self, container_id: str, tab_name: TabName) -> str:
        """Use the tab's provider to load text for one container."""
        return self._providers_by_tab[tab_name].load_text(container_id)


def _format_process_list(processes: ContainerProcessTable) -> str:
    """Join Docker process columns and rows into Top tab lines."""
    lines = [" ".join(processes.columns)] if processes.columns else []
    lines.extend(" ".join(row) for row in processes.rows)
    return "\n".join(lines)


def format_logs_unavailable_message(exc: LogsUnavailableError) -> str:
    """Build the message shown when Docker cannot read a container's logs."""
    return (
        "Logs unavailable: this container uses Docker logging "
        f"driver '{exc.driver}', so Docker cannot read logs for it. "
        "Enable a readable logging driver such as 'json-file', 'local', "
        "or 'journald' to view logs here."
    )


__all__ = [
    "ConfigTabDataProvider",
    "EnvTabDataProvider",
    "LogsTabDataProvider",
    "TabDataProvider",
    "TabDataLoader",
    "TopTabDataProvider",
    "format_logs_unavailable_message",
]
