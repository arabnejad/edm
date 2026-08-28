"""Container data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ContainerSummary:
    """Container details displayed and sorted in the terminal UI.

    Docker supplies the id, name, status, image name, and creation time for
    every listed container, so all five fields are required. The sorting code
    still handles an explicitly empty image name or creation time by placing
    that container at the end in container-id order.
    """

    container_id: str
    name: str
    status: str
    image_name: str
    created_at: str


@dataclass
class ContainerProcessTable:
    """Store the column names and process rows returned by Docker top."""

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass
class ContainerResourceStatsSnapshot:
    """One container resource reading used by the Stats tab.

    Docker does not return every field on every operating system or cgroup
    version. A missing field stays as None so the Stats tab can show N/A rather
    than a misleading zero.
    """

    collected_at: datetime
    container_uptime_seconds: Optional[float]
    container_health_status: Optional[str]
    container_restart_count: Optional[int]
    cpu_usage_percent: Optional[float]
    cpu_cores_used: Optional[float]
    cpu_limit_cores: Optional[float]
    cpu_limit_usage_percent: Optional[float]
    cpu_throttled_period_count: Optional[int]
    cpu_throttled_time_seconds: Optional[float]
    memory_usage_bytes: Optional[int]
    memory_cache_bytes: Optional[int]
    memory_limit_bytes: Optional[int]
    memory_available_bytes: Optional[int]
    memory_usage_percent: Optional[float]
    memory_swap_bytes: Optional[int]
    network_received_bytes: Optional[int]
    network_receive_rate_bytes_per_second: Optional[float]
    network_sent_bytes: Optional[int]
    network_send_rate_bytes_per_second: Optional[float]
    network_received_packet_count: Optional[int]
    network_sent_packet_count: Optional[int]
    block_read_bytes: Optional[int]
    block_read_rate_bytes_per_second: Optional[float]
    block_written_bytes: Optional[int]
    block_write_rate_bytes_per_second: Optional[float]
    current_process_and_thread_count: Optional[int]
    process_and_thread_limit: Optional[int]


__all__ = [
    "ContainerProcessTable",
    "ContainerResourceStatsSnapshot",
    "ContainerSummary",
]
