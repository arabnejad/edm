"""Turn Docker's raw resource counters into data for the Stats tab."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from easy_docker_manager.core.containers import ContainerResourceStatsSnapshot


@dataclass
class _ParsedCpuStats:
    usage_percent: Optional[float]
    cores_used: Optional[float]
    limit_cores: Optional[float]
    limit_usage_percent: Optional[float]
    throttled_period_count: Optional[int]
    throttled_time_seconds: Optional[float]


@dataclass
class _ParsedMemoryStats:
    usage_bytes: Optional[int]
    cache_bytes: Optional[int]
    limit_bytes: Optional[int]
    available_bytes: Optional[int]
    usage_percent: Optional[float]
    swap_bytes: Optional[int]


@dataclass
class _ParsedNetworkStats:
    received_bytes: Optional[int]
    sent_bytes: Optional[int]
    received_packet_count: Optional[int]
    sent_packet_count: Optional[int]


@dataclass
class _ParsedBlockIOStats:
    read_bytes: Optional[int]
    written_bytes: Optional[int]


@dataclass
class _ParsedProcessStats:
    current_count: Optional[int]
    limit: Optional[int]


def build_container_resource_stats_snapshot(
    docker_stats_response: dict[str, Any],
    container_inspection_data: dict[str, Any],
    previous_resource_stats_snapshot: Optional[ContainerResourceStatsSnapshot] = None,
) -> ContainerResourceStatsSnapshot:
    """Build one Stats snapshot from Docker stats and inspection data.

    If an earlier sample is available, the cumulative byte counters from both
    samples are used to calculate network and disk transfer rates. The first
    sample has no earlier counters, so its rates remain unavailable.
    """
    stats_collected_at = _parse_docker_timestamp(docker_stats_response.get("read"))
    container_state = _get_dict_or_empty(container_inspection_data.get("State"))
    container_host_config = _get_dict_or_empty(
        container_inspection_data.get("HostConfig")
    )

    cpu_stats = _parse_cpu_stats(docker_stats_response, container_host_config)
    memory_stats = _parse_memory_stats(docker_stats_response)
    network_stats = _parse_network_stats(docker_stats_response)
    block_io_stats = _parse_block_io_stats(docker_stats_response)
    process_stats = _parse_process_stats(docker_stats_response)

    elapsed_seconds_between_samples = _calculate_elapsed_seconds_between_samples(
        previous_resource_stats_snapshot,
        stats_collected_at,
    )

    return ContainerResourceStatsSnapshot(
        collected_at=stats_collected_at,
        container_uptime_seconds=_calculate_container_uptime_seconds(
            container_state.get("StartedAt"),
            stats_collected_at,
        ),
        container_health_status=_parse_container_health_status(container_state),
        container_restart_count=_optional_integer(
            container_inspection_data.get("RestartCount")
        ),
        cpu_usage_percent=cpu_stats.usage_percent,
        cpu_cores_used=cpu_stats.cores_used,
        cpu_limit_cores=cpu_stats.limit_cores,
        cpu_limit_usage_percent=cpu_stats.limit_usage_percent,
        cpu_throttled_period_count=cpu_stats.throttled_period_count,
        cpu_throttled_time_seconds=cpu_stats.throttled_time_seconds,
        memory_usage_bytes=memory_stats.usage_bytes,
        memory_cache_bytes=memory_stats.cache_bytes,
        memory_limit_bytes=memory_stats.limit_bytes,
        memory_available_bytes=memory_stats.available_bytes,
        memory_usage_percent=memory_stats.usage_percent,
        memory_swap_bytes=memory_stats.swap_bytes,
        network_received_bytes=network_stats.received_bytes,
        network_receive_rate_bytes_per_second=_calculate_counter_rate(
            network_stats.received_bytes,
            (
                previous_resource_stats_snapshot.network_received_bytes
                if previous_resource_stats_snapshot is not None
                else None
            ),
            elapsed_seconds_between_samples,
        ),
        network_sent_bytes=network_stats.sent_bytes,
        network_send_rate_bytes_per_second=_calculate_counter_rate(
            network_stats.sent_bytes,
            (
                previous_resource_stats_snapshot.network_sent_bytes
                if previous_resource_stats_snapshot is not None
                else None
            ),
            elapsed_seconds_between_samples,
        ),
        network_received_packet_count=network_stats.received_packet_count,
        network_sent_packet_count=network_stats.sent_packet_count,
        block_read_bytes=block_io_stats.read_bytes,
        block_read_rate_bytes_per_second=_calculate_counter_rate(
            block_io_stats.read_bytes,
            (
                previous_resource_stats_snapshot.block_read_bytes
                if previous_resource_stats_snapshot is not None
                else None
            ),
            elapsed_seconds_between_samples,
        ),
        block_written_bytes=block_io_stats.written_bytes,
        block_write_rate_bytes_per_second=_calculate_counter_rate(
            block_io_stats.written_bytes,
            (
                previous_resource_stats_snapshot.block_written_bytes
                if previous_resource_stats_snapshot is not None
                else None
            ),
            elapsed_seconds_between_samples,
        ),
        current_process_and_thread_count=process_stats.current_count,
        process_and_thread_limit=process_stats.limit,
    )


def _parse_cpu_stats(
    docker_stats_response: dict[str, Any],
    container_host_config: dict[str, Any],
) -> _ParsedCpuStats:
    """Read CPU usage, limits, and throttling from one Docker response."""
    current_cpu_stats = _get_dict_or_empty(docker_stats_response.get("cpu_stats"))
    previous_cpu_stats = _get_dict_or_empty(docker_stats_response.get("precpu_stats"))
    current_cpu_usage = _get_dict_or_empty(current_cpu_stats.get("cpu_usage"))
    previous_cpu_usage = _get_dict_or_empty(previous_cpu_stats.get("cpu_usage"))

    current_total_usage = _optional_number(current_cpu_usage.get("total_usage"))
    previous_total_usage = _optional_number(previous_cpu_usage.get("total_usage"))
    current_system_usage = _optional_number(current_cpu_stats.get("system_cpu_usage"))
    previous_system_usage = _optional_number(previous_cpu_stats.get("system_cpu_usage"))
    online_cpu_count = _get_online_cpu_count_from_stats(
        current_cpu_stats,
        current_cpu_usage,
    )

    usage_percent: Optional[float] = None
    if (
        current_total_usage is not None
        and previous_total_usage is not None
        and current_system_usage is not None
        and previous_system_usage is not None
        and online_cpu_count is not None
    ):
        container_cpu_delta = current_total_usage - previous_total_usage
        system_cpu_delta = current_system_usage - previous_system_usage
        if container_cpu_delta >= 0 and system_cpu_delta > 0:
            usage_percent = (
                container_cpu_delta / system_cpu_delta * online_cpu_count * 100.0
            )

    cores_used = usage_percent / 100.0 if usage_percent is not None else None
    cpu_limit_cores = _get_configured_cpu_limit_in_cores(container_host_config)
    cpu_limit_usage_percent = (
        cores_used / cpu_limit_cores * 100.0
        if cores_used is not None and cpu_limit_cores is not None
        else None
    )

    throttling_data = _get_dict_or_empty(current_cpu_stats.get("throttling_data"))
    throttled_time_nanoseconds = _optional_number(throttling_data.get("throttled_time"))
    throttled_time_microseconds = _optional_number(
        throttling_data.get("throttled_usec")
    )
    throttled_time_seconds = None
    if throttled_time_nanoseconds is not None:
        throttled_time_seconds = throttled_time_nanoseconds / 1_000_000_000
    elif throttled_time_microseconds is not None:
        throttled_time_seconds = throttled_time_microseconds / 1_000_000

    return _ParsedCpuStats(
        usage_percent=usage_percent,
        cores_used=cores_used,
        limit_cores=cpu_limit_cores,
        limit_usage_percent=cpu_limit_usage_percent,
        throttled_period_count=_optional_integer(
            throttling_data.get("throttled_periods")
        ),
        throttled_time_seconds=throttled_time_seconds,
    )


def _parse_memory_stats(
    docker_stats_response: dict[str, Any],
) -> _ParsedMemoryStats:
    """Read memory usage, cache, limits, available memory, and swap."""
    memory_stats = _get_dict_or_empty(docker_stats_response.get("memory_stats"))
    memory_details = _get_dict_or_empty(memory_stats.get("stats"))
    raw_usage_bytes = _optional_integer(memory_stats.get("usage"))
    cache_bytes = _first_available_integer(
        memory_details,
        "inactive_file",
        "total_inactive_file",
        "cache",
    )
    usage_bytes = raw_usage_bytes
    if raw_usage_bytes is not None and cache_bytes is not None:
        usage_bytes = max(0, raw_usage_bytes - cache_bytes)

    limit_bytes = _optional_positive_integer(memory_stats.get("limit"))
    available_bytes = (
        max(0, limit_bytes - usage_bytes)
        if limit_bytes is not None and usage_bytes is not None
        else None
    )
    usage_percent = (
        usage_bytes / limit_bytes * 100.0
        if usage_bytes is not None and limit_bytes is not None
        else None
    )

    return _ParsedMemoryStats(
        usage_bytes=usage_bytes,
        cache_bytes=cache_bytes,
        limit_bytes=limit_bytes,
        available_bytes=available_bytes,
        usage_percent=usage_percent,
        swap_bytes=_first_available_integer(
            memory_details,
            "swap",
            "total_swap",
        ),
    )


def _parse_network_stats(
    docker_stats_response: dict[str, Any],
) -> _ParsedNetworkStats:
    """Add network counters from every interface in the container."""
    raw_networks = docker_stats_response.get("networks")
    if not isinstance(raw_networks, dict):
        return _ParsedNetworkStats(None, None, None, None)

    return _ParsedNetworkStats(
        received_bytes=_sum_network_interface_counter(raw_networks, "rx_bytes"),
        sent_bytes=_sum_network_interface_counter(raw_networks, "tx_bytes"),
        received_packet_count=_sum_network_interface_counter(
            raw_networks,
            "rx_packets",
        ),
        sent_packet_count=_sum_network_interface_counter(raw_networks, "tx_packets"),
    )


def _parse_block_io_stats(
    docker_stats_response: dict[str, Any],
) -> _ParsedBlockIOStats:
    """Add block-device read and write byte counters from the Docker sample."""
    block_io_stats = _get_dict_or_empty(docker_stats_response.get("blkio_stats"))
    raw_entries = block_io_stats.get("io_service_bytes_recursive")
    if not isinstance(raw_entries, list):
        return _ParsedBlockIOStats(None, None)

    read_bytes = 0
    written_bytes = 0
    for raw_entry in raw_entries:
        entry = _get_dict_or_empty(raw_entry)
        operation_name = str(entry.get("op") or "").casefold()
        byte_count = _optional_integer(entry.get("value"))
        if byte_count is None:
            continue
        if operation_name == "read":
            read_bytes += byte_count
        elif operation_name == "write":
            written_bytes += byte_count
    return _ParsedBlockIOStats(read_bytes, written_bytes)


def _parse_process_stats(
    docker_stats_response: dict[str, Any],
) -> _ParsedProcessStats:
    """Read Docker's current and allowed process-and-thread counts."""
    process_stats = _get_dict_or_empty(docker_stats_response.get("pids_stats"))
    return _ParsedProcessStats(
        current_count=_optional_integer(process_stats.get("current")),
        limit=_optional_positive_integer(process_stats.get("limit")),
    )


def _get_online_cpu_count_from_stats(
    current_cpu_stats: dict[str, Any],
    current_cpu_usage: dict[str, Any],
) -> Optional[float]:
    """Return the CPU count Docker used for this sample."""
    online_cpu_count = _optional_number(current_cpu_stats.get("online_cpus"))
    if online_cpu_count is not None and online_cpu_count > 0:
        return online_cpu_count
    per_cpu_usage = current_cpu_usage.get("percpu_usage")
    if isinstance(per_cpu_usage, list) and per_cpu_usage:
        return float(len(per_cpu_usage))
    return None


def _get_configured_cpu_limit_in_cores(
    container_host_config: dict[str, Any],
) -> Optional[float]:
    """Return the configured CPU limit as a number of cores."""
    nano_cpus = _optional_number(container_host_config.get("NanoCpus"))
    if nano_cpus is not None and nano_cpus > 0:
        return nano_cpus / 1_000_000_000

    cpu_quota = _optional_number(container_host_config.get("CpuQuota"))
    cpu_period = _optional_number(container_host_config.get("CpuPeriod"))
    if (
        cpu_quota is not None
        and cpu_quota > 0
        and cpu_period is not None
        and cpu_period > 0
    ):
        return cpu_quota / cpu_period

    windows_cpu_count = _optional_number(container_host_config.get("CpuCount"))
    if windows_cpu_count is not None and windows_cpu_count > 0:
        return windows_cpu_count

    return _count_cpus_in_set(container_host_config.get("CpusetCpus"))


def _count_cpus_in_set(raw_cpu_set: Any) -> Optional[float]:
    """Count CPUs in a Docker cpuset value such as 0-2,4."""
    cpu_set = str(raw_cpu_set or "").strip()
    if not cpu_set:
        return None

    cpu_numbers: set[int] = set()
    try:
        for part in cpu_set.split(","):
            range_limits = part.split("-", 1)
            if len(range_limits) == 1:
                cpu_numbers.add(int(range_limits[0]))
                continue
            first_cpu = int(range_limits[0])
            last_cpu = int(range_limits[1])
            cpu_numbers.update(range(first_cpu, last_cpu + 1))
    except ValueError:
        return None
    return float(len(cpu_numbers)) if cpu_numbers else None


def _parse_container_health_status(
    container_state: dict[str, Any],
) -> Optional[str]:
    """Return the health-check status when the container has one."""
    health = _get_dict_or_empty(container_state.get("Health"))
    health_status = health.get("Status")
    return str(health_status) if health_status not in (None, "") else None


def _calculate_container_uptime_seconds(
    raw_started_at: Any,
    stats_collected_at: datetime,
) -> Optional[float]:
    """Return elapsed seconds between container startup and this sample."""
    started_at = _parse_optional_docker_timestamp(raw_started_at)
    if started_at is None:
        return None
    return max(0.0, (stats_collected_at - started_at).total_seconds())


def _calculate_elapsed_seconds_between_samples(
    previous_resource_stats_snapshot: Optional[ContainerResourceStatsSnapshot],
    current_stats_collected_at: datetime,
) -> Optional[float]:
    """Return elapsed seconds since the previous sample."""
    if previous_resource_stats_snapshot is None:
        return None
    elapsed_seconds = (
        current_stats_collected_at - previous_resource_stats_snapshot.collected_at
    ).total_seconds()
    return elapsed_seconds if elapsed_seconds > 0 else None


def _calculate_counter_rate(
    current_counter_value: Optional[int],
    previous_counter_value: Optional[int],
    elapsed_seconds: Optional[float],
) -> Optional[float]:
    """Return a per-second rate from two increasing byte counters."""
    if (
        current_counter_value is None
        or previous_counter_value is None
        or elapsed_seconds is None
        or current_counter_value < previous_counter_value
    ):
        return None
    return (current_counter_value - previous_counter_value) / elapsed_seconds


def _sum_network_interface_counter(
    network_interfaces: dict[str, Any],
    counter_name: str,
) -> Optional[int]:
    """Add the same Docker counter across every container network interface."""
    total = 0
    found_counter = False
    for raw_interface_counters in network_interfaces.values():
        interface_counters = _get_dict_or_empty(raw_interface_counters)
        counter = _optional_integer(interface_counters.get(counter_name))
        if counter is not None:
            total += counter
            found_counter = True
    return total if found_counter else None


def _parse_docker_timestamp(raw_value: Any) -> datetime:
    """Parse a Docker timestamp or use the current UTC time when it is missing."""
    parsed_timestamp = _parse_optional_docker_timestamp(raw_value)
    if parsed_timestamp is not None:
        return parsed_timestamp
    return datetime.now(timezone.utc)


def _parse_optional_docker_timestamp(raw_value: Any) -> Optional[datetime]:
    """Parse an ISO timestamp returned by Docker."""
    timestamp_text = str(raw_value or "").strip()
    if not timestamp_text or timestamp_text.startswith("0001-01-01"):
        return None
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed_timestamp.tzinfo is None:
        return parsed_timestamp.replace(tzinfo=timezone.utc)
    return parsed_timestamp


def _first_available_integer(
    values: dict[str, Any],
    *keys: str,
) -> Optional[int]:
    """Return the first integer present under the supplied keys."""
    for key in keys:
        value = _optional_integer(values.get(key))
        if value is not None:
            return value
    return None


def _optional_positive_integer(value: Any) -> Optional[int]:
    """Return a positive integer or None for missing and unlimited values."""
    integer_value = _optional_integer(value)
    if integer_value is None or integer_value <= 0:
        return None
    return integer_value


def _optional_integer(value: Any) -> Optional[int]:
    """Return value as an integer when Docker supplied a number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_number(value: Any) -> Optional[float]:
    """Return value as a float when Docker supplied a number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_dict_or_empty(value: Any) -> dict[str, Any]:
    """Return a dictionary value or an empty dictionary for another type."""
    return value if isinstance(value, dict) else {}


__all__ = ["build_container_resource_stats_snapshot"]
