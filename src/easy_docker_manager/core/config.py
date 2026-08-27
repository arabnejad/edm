"""Define and validate EDM's configuration settings."""

from __future__ import annotations

from dataclasses import dataclass

from easy_docker_manager.core.log_text import MIN_LOG_LINE_CHARS


@dataclass(frozen=True)
class AppConfig:
    """Store the settings EDM reads when it starts.

    The Docker client, worker pool, cache, loaders, and terminal interface all
    share this object. It cannot be changed after creation because EDM does not
    reload settings while running. Edit config.json and restart EDM to use new
    values.
    """

    container_list_refresh_interval_seconds: float = 2.0
    tab_refresh_interval: float = 2.0
    initial_log_tail_lines: int = 100
    max_log_lines: int = 2000
    max_log_line_chars: int = 4000
    tab_content_cache_max_entries: int = 50
    tab_content_cache_max_bytes: int = 25_000_000
    docker_request_timeout: float = 10.0
    max_background_worker_threads: int = 4
    colors_enabled: bool = True

    def __post_init__(self) -> None:
        """Reject invalid settings before the application starts."""
        if self.container_list_refresh_interval_seconds <= 0:
            raise ValueError("container_list_refresh_interval_seconds must be positive")
        if self.tab_refresh_interval <= 0:
            raise ValueError("tab_refresh_interval must be positive")
        if self.initial_log_tail_lines <= 0:
            raise ValueError("initial_log_tail_lines must be positive")
        if self.max_log_lines <= 0:
            raise ValueError("max_log_lines must be positive")
        if self.max_log_line_chars < MIN_LOG_LINE_CHARS:
            raise ValueError(
                f"max_log_line_chars must be at least {MIN_LOG_LINE_CHARS}"
            )
        if self.tab_content_cache_max_entries <= 0:
            raise ValueError("tab_content_cache_max_entries must be positive")
        if self.tab_content_cache_max_bytes <= 0:
            raise ValueError("tab_content_cache_max_bytes must be positive")
        if self.docker_request_timeout <= 0:
            raise ValueError("docker_request_timeout must be positive")
        if self.max_background_worker_threads <= 0:
            raise ValueError("max_background_worker_threads must be positive")


__all__ = ["AppConfig"]
