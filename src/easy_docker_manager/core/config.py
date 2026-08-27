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

    refresh_interval: float = 2.0
    tab_refresh_interval: float = 2.0
    log_tail: int = 100
    max_log_lines: int = 2000
    max_log_line_chars: int = 4000
    content_cache_size: int = 50
    content_cache_max_bytes: int = 25_000_000
    docker_request_timeout: float = 10.0
    max_workers: int = 4
    colors_enabled: bool = True

    def __post_init__(self) -> None:
        """Reject invalid settings before the application starts."""
        if self.refresh_interval <= 0:
            raise ValueError("refresh_interval must be positive")
        if self.tab_refresh_interval <= 0:
            raise ValueError("tab_refresh_interval must be positive")
        if self.log_tail <= 0:
            raise ValueError("log_tail must be positive")
        if self.max_log_lines <= 0:
            raise ValueError("max_log_lines must be positive")
        if self.max_log_line_chars < MIN_LOG_LINE_CHARS:
            raise ValueError(
                f"max_log_line_chars must be at least {MIN_LOG_LINE_CHARS}"
            )
        if self.content_cache_size <= 0:
            raise ValueError("content_cache_size must be positive")
        if self.content_cache_max_bytes <= 0:
            raise ValueError("content_cache_max_bytes must be positive")
        if self.docker_request_timeout <= 0:
            raise ValueError("docker_request_timeout must be positive")
        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")


__all__ = ["AppConfig"]
