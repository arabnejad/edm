"""Build the readable text shown in the Stats tab."""

from __future__ import annotations

from typing import Optional

from easy_docker_manager.core.containers import ContainerResourceStatsSnapshot


def format_container_resource_stats_tab_text(
    resource_stats_snapshot: ContainerResourceStatsSnapshot,
    refresh_interval_seconds: float,
) -> str:
    """Build the grouped text displayed in a container's Stats tab."""
    lines: list[str] = []

    _add_section(lines, "Sample")
    _add_field(
        lines,
        "Updated",
        resource_stats_snapshot.collected_at.astimezone().strftime("%H:%M:%S"),
    )
    _add_field(
        lines,
        "Refresh interval",
        f"{refresh_interval_seconds:.1f} seconds",
    )

    _add_section(lines, "Runtime")
    _add_field(
        lines,
        "Uptime",
        _format_uptime(resource_stats_snapshot.container_uptime_seconds),
    )
    _add_field(
        lines,
        "Health",
        resource_stats_snapshot.container_health_status or "not configured",
    )
    _add_field(
        lines,
        "Restart count",
        _format_integer(resource_stats_snapshot.container_restart_count),
    )

    _add_section(lines, "CPU")
    _add_field(
        lines,
        "Usage",
        _format_percentage(resource_stats_snapshot.cpu_usage_percent),
    )
    _add_field(
        lines,
        "Cores used",
        _format_decimal(resource_stats_snapshot.cpu_cores_used),
    )
    _add_field(
        lines,
        "CPU limit",
        _format_cpu_limit(resource_stats_snapshot.cpu_limit_cores),
    )
    _add_field(
        lines,
        "Limit used",
        _format_percentage(resource_stats_snapshot.cpu_limit_usage_percent),
    )
    _add_field(
        lines,
        "Throttled",
        _format_count(resource_stats_snapshot.cpu_throttled_period_count, "times"),
    )
    _add_field(
        lines,
        "Throttled time",
        _format_duration_seconds(resource_stats_snapshot.cpu_throttled_time_seconds),
    )

    _add_section(lines, "Memory")
    _add_field(
        lines,
        "Usage",
        _format_byte_count(resource_stats_snapshot.memory_usage_bytes),
    )
    _add_field(
        lines,
        "Cache",
        _format_byte_count(resource_stats_snapshot.memory_cache_bytes),
    )
    _add_field(
        lines,
        "Limit",
        _format_byte_count(resource_stats_snapshot.memory_limit_bytes),
    )
    _add_field(
        lines,
        "Available",
        _format_byte_count(resource_stats_snapshot.memory_available_bytes),
    )
    _add_field(
        lines,
        "Percentage",
        _format_percentage(resource_stats_snapshot.memory_usage_percent),
    )
    _add_field(
        lines,
        "Swap",
        _format_byte_count(resource_stats_snapshot.memory_swap_bytes),
    )

    _add_section(lines, "Network I/O")
    _add_field(
        lines,
        "Received",
        _format_byte_count(resource_stats_snapshot.network_received_bytes),
    )
    _add_field(
        lines,
        "Receive rate",
        _format_byte_rate(
            resource_stats_snapshot.network_receive_rate_bytes_per_second
        ),
    )
    _add_field(
        lines,
        "Sent",
        _format_byte_count(resource_stats_snapshot.network_sent_bytes),
    )
    _add_field(
        lines,
        "Send rate",
        _format_byte_rate(resource_stats_snapshot.network_send_rate_bytes_per_second),
    )
    _add_field(
        lines,
        "Received packets",
        _format_integer(resource_stats_snapshot.network_received_packet_count),
    )
    _add_field(
        lines,
        "Sent packets",
        _format_integer(resource_stats_snapshot.network_sent_packet_count),
    )

    _add_section(lines, "Block I/O")
    _add_field(
        lines,
        "Read",
        _format_byte_count(resource_stats_snapshot.block_read_bytes),
    )
    _add_field(
        lines,
        "Read rate",
        _format_byte_rate(resource_stats_snapshot.block_read_rate_bytes_per_second),
    )
    _add_field(
        lines,
        "Written",
        _format_byte_count(resource_stats_snapshot.block_written_bytes),
    )
    _add_field(
        lines,
        "Write rate",
        _format_byte_rate(resource_stats_snapshot.block_write_rate_bytes_per_second),
    )

    _add_section(lines, "Processes")
    _add_field(
        lines,
        "PIDs",
        _format_integer(resource_stats_snapshot.current_process_and_thread_count),
    )
    _add_field(
        lines,
        "PID limit",
        _format_optional_limit(resource_stats_snapshot.process_and_thread_limit),
    )
    return "\n".join(lines)


def _add_section(lines: list[str], title: str) -> None:
    """Add a section heading with a border above and below it."""
    if lines:
        lines.append("")
    heading = f"== {title} =="
    border = "=" * len(heading)
    lines.extend([border, heading, border])


def _add_field(lines: list[str], label: str, value: str) -> None:
    """Add one aligned label and value to the current section."""
    lines.append(f"  {label:<16}: {value}")


def _format_uptime(uptime_seconds: Optional[float]) -> str:
    """Format container uptime using days, hours, minutes, and seconds."""
    if uptime_seconds is None:
        return "N/A"
    remaining_seconds = max(0, int(uptime_seconds))
    days, remaining_seconds = divmod(remaining_seconds, 86_400)
    hours, remaining_seconds = divmod(remaining_seconds, 3_600)
    minutes, seconds = divmod(remaining_seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def _format_byte_count(byte_count: Optional[float]) -> str:
    """Format bytes with binary units such as KiB, MiB, and GiB."""
    if byte_count is None:
        return "N/A"
    value = max(0.0, float(byte_count))
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{value:.0f} {units[unit_index]}"
    if value >= 100:
        return f"{value:.0f} {units[unit_index]}"
    if value >= 10:
        return f"{value:.1f} {units[unit_index]}"
    return f"{value:.2f} {units[unit_index]}"


def _format_byte_rate(bytes_per_second: Optional[float]) -> str:
    """Format a transfer rate using binary byte units per second."""
    if bytes_per_second is None:
        return "N/A"
    return f"{_format_byte_count(bytes_per_second)}/s"


def _format_percentage(value: Optional[float]) -> str:
    """Format a percentage, or show N/A when Docker did not report it."""
    return f"{value:.2f}%" if value is not None else "N/A"


def _format_decimal(value: Optional[float]) -> str:
    """Format a decimal value, or show N/A when Docker did not report it."""
    return f"{value:.2f}" if value is not None else "N/A"


def _format_cpu_limit(cpu_limit_cores: Optional[float]) -> str:
    """Format a CPU limit or report that no limit was configured."""
    if cpu_limit_cores is None:
        return "No limit"
    return f"{cpu_limit_cores:.2f} cores"


def _format_duration_seconds(seconds: Optional[float]) -> str:
    """Format a duration in seconds, or show N/A when it is missing."""
    return f"{seconds:.1f}s" if seconds is not None else "N/A"


def _format_count(value: Optional[int], suffix: str) -> str:
    """Format a count with a short suffix, or show N/A when it is missing."""
    return f"{value:,} {suffix}" if value is not None else "N/A"


def _format_integer(value: Optional[int]) -> str:
    """Format an integer with thousands separators, or show N/A."""
    return f"{value:,}" if value is not None else "N/A"


def _format_optional_limit(value: Optional[int]) -> str:
    """Format an integer limit or report that no limit was configured."""
    return f"{value:,}" if value is not None else "No limit"


__all__ = ["format_container_resource_stats_tab_text"]
