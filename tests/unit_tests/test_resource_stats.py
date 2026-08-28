from __future__ import annotations

from datetime import datetime, timezone

from easy_docker_manager.docker.container_resource_stats_builder import (
    build_container_resource_stats_snapshot,
)
from easy_docker_manager.tabs.resource_stats_formatter import (
    format_container_resource_stats_tab_text,
)


def test_docker_resource_counters_are_converted_to_one_container_snapshot(
    container_resource_stats_snapshot_factory,
) -> None:
    previous_resource_stats_snapshot = container_resource_stats_snapshot_factory(
        collected_at=datetime(2026, 1, 1, 14, 32, 16, tzinfo=timezone.utc),
        network_received_bytes=600,
        network_sent_bytes=450,
        block_read_bytes=1000,
        block_written_bytes=2000,
    )
    docker_stats_response = {
        "read": "2026-01-01T14:32:18Z",
        "cpu_stats": {
            "cpu_usage": {"total_usage": 1500, "percpu_usage": [1, 1, 1, 1]},
            "system_cpu_usage": 5000,
            "online_cpus": 4,
            "throttling_data": {
                "throttled_periods": 12,
                "throttled_time": 1_400_000_000,
            },
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 1000},
            "system_cpu_usage": 1000,
        },
        "memory_stats": {
            "usage": 288 * 1024**2,
            "limit": 2 * 1024**3,
            "stats": {"inactive_file": 32 * 1024**2, "swap": 0},
        },
        "networks": {
            "eth0": {
                "rx_bytes": 900,
                "tx_bytes": 600,
                "rx_packets": 700,
                "tx_packets": 500,
            },
            "eth1": {
                "rx_bytes": 100,
                "tx_bytes": 50,
                "rx_packets": 42,
                "tx_packets": 10,
            },
        },
        "blkio_stats": {
            "io_service_bytes_recursive": [
                {"op": "Read", "value": 1240},
                {"op": "Write", "value": 2200},
                {"op": "Sync", "value": 9999},
            ]
        },
        "pids_stats": {"current": 24, "limit": 512},
    }
    container_inspection_data = {
        "RestartCount": 2,
        "State": {
            "StartedAt": "2026-01-01T10:14:18Z",
            "Health": {"Status": "healthy"},
        },
        "HostConfig": {"NanoCpus": 2_000_000_000},
    }

    resource_stats_snapshot = build_container_resource_stats_snapshot(
        docker_stats_response,
        container_inspection_data,
        previous_resource_stats_snapshot,
    )

    assert resource_stats_snapshot.collected_at == datetime(
        2026, 1, 1, 14, 32, 18, tzinfo=timezone.utc
    )
    assert resource_stats_snapshot.container_uptime_seconds == 15_480
    assert resource_stats_snapshot.container_health_status == "healthy"
    assert resource_stats_snapshot.container_restart_count == 2
    assert resource_stats_snapshot.cpu_usage_percent == 50.0
    assert resource_stats_snapshot.cpu_cores_used == 0.5
    assert resource_stats_snapshot.cpu_limit_cores == 2.0
    assert resource_stats_snapshot.cpu_limit_usage_percent == 25.0
    assert resource_stats_snapshot.cpu_throttled_period_count == 12
    assert resource_stats_snapshot.cpu_throttled_time_seconds == 1.4
    assert resource_stats_snapshot.memory_usage_bytes == 256 * 1024**2
    assert resource_stats_snapshot.memory_cache_bytes == 32 * 1024**2
    assert resource_stats_snapshot.memory_available_bytes == 1792 * 1024**2
    assert resource_stats_snapshot.memory_usage_percent == 12.5
    assert resource_stats_snapshot.network_received_bytes == 1000
    assert resource_stats_snapshot.network_receive_rate_bytes_per_second == 200
    assert resource_stats_snapshot.network_sent_bytes == 650
    assert resource_stats_snapshot.network_send_rate_bytes_per_second == 100
    assert resource_stats_snapshot.network_received_packet_count == 742
    assert resource_stats_snapshot.network_sent_packet_count == 510
    assert resource_stats_snapshot.block_read_bytes == 1240
    assert resource_stats_snapshot.block_read_rate_bytes_per_second == 120
    assert resource_stats_snapshot.block_written_bytes == 2200
    assert resource_stats_snapshot.block_write_rate_bytes_per_second == 100
    assert resource_stats_snapshot.current_process_and_thread_count == 24
    assert resource_stats_snapshot.process_and_thread_limit == 512


def test_missing_platform_specific_stats_remain_unavailable() -> None:
    resource_stats_snapshot = build_container_resource_stats_snapshot(
        {"read": "2026-01-01T14:32:18Z"},
        {"State": {}, "HostConfig": {}},
    )

    assert resource_stats_snapshot.cpu_usage_percent is None
    assert resource_stats_snapshot.cpu_limit_cores is None
    assert resource_stats_snapshot.memory_usage_bytes is None
    assert resource_stats_snapshot.network_received_bytes is None
    assert resource_stats_snapshot.block_read_bytes is None
    assert resource_stats_snapshot.current_process_and_thread_count is None
    assert resource_stats_snapshot.container_health_status is None
    assert resource_stats_snapshot.container_uptime_seconds is None


def test_cpu_quota_and_cpuset_limits_are_supported() -> None:
    docker_stats_response = {
        "read": "2026-01-01T14:32:18Z",
        "cpu_stats": {
            "cpu_usage": {"total_usage": 200, "percpu_usage": [1, 1]},
            "system_cpu_usage": 1000,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 100},
            "system_cpu_usage": 500,
        },
    }

    quota_snapshot = build_container_resource_stats_snapshot(
        docker_stats_response,
        {"HostConfig": {"CpuQuota": 50_000, "CpuPeriod": 100_000}},
    )
    cpuset_snapshot = build_container_resource_stats_snapshot(
        {"read": "2026-01-01T14:32:18Z"},
        {"HostConfig": {"CpusetCpus": "0-2,4"}},
    )

    assert quota_snapshot.cpu_usage_percent == 40.0
    assert quota_snapshot.cpu_limit_cores == 0.5
    assert quota_snapshot.cpu_limit_usage_percent == 80.0
    assert cpuset_snapshot.cpu_limit_cores == 4.0


def test_counter_rates_are_unavailable_after_a_counter_reset(
    container_resource_stats_snapshot_factory,
) -> None:
    previous_resource_stats_snapshot = container_resource_stats_snapshot_factory(
        collected_at=datetime(2026, 1, 1, 14, 32, 20, tzinfo=timezone.utc),
        network_received_bytes=1000,
        network_sent_bytes=1000,
        block_read_bytes=1000,
        block_written_bytes=1000,
    )
    resource_stats_snapshot = build_container_resource_stats_snapshot(
        {
            "read": "2026-01-01T14:32:18Z",
            "networks": {
                "eth0": {
                    "rx_bytes": 100,
                    "tx_bytes": 100,
                    "rx_packets": 1,
                    "tx_packets": 1,
                }
            },
            "blkio_stats": {
                "io_service_bytes_recursive": [
                    {"op": "read", "value": 100},
                    {"op": "write", "value": 100},
                ]
            },
        },
        {},
        previous_resource_stats_snapshot,
    )

    assert resource_stats_snapshot.network_receive_rate_bytes_per_second is None
    assert resource_stats_snapshot.network_send_rate_bytes_per_second is None
    assert resource_stats_snapshot.block_read_rate_bytes_per_second is None
    assert resource_stats_snapshot.block_write_rate_bytes_per_second is None


def test_stats_formatter_builds_all_sections_without_packet_error_counters(
    container_resource_stats_snapshot_factory,
) -> None:
    stats_tab_text = format_container_resource_stats_tab_text(
        container_resource_stats_snapshot_factory(),
        refresh_interval_seconds=2.0,
    )
    expected_local_time = (
        datetime(2026, 1, 1, 14, 32, 18, tzinfo=timezone.utc)
        .astimezone()
        .strftime("%H:%M:%S")
    )

    for section in [
        "Sample",
        "Runtime",
        "CPU",
        "Memory",
        "Network I/O",
        "Block I/O",
        "Processes",
    ]:
        heading = f"== {section} =="
        assert (
            f"{'=' * len(heading)}\n{heading}\n{'=' * len(heading)}" in stats_tab_text
        )

    assert f"Updated         : {expected_local_time}" in stats_tab_text
    assert "Uptime          : 2d 4h 18m 0s" in stats_tab_text
    assert "Usage           : 12.45%" in stats_tab_text
    assert "Memory" in stats_tab_text
    assert "Limit           : 2.00 GiB" in stats_tab_text
    assert "Receive rate    : 2.40 MiB/s" in stats_tab_text
    assert "Received packets: 742,183" in stats_tab_text
    assert "PIDs            : 24" in stats_tab_text
    assert "PID limit       : 512" in stats_tab_text
    assert "Dropped" not in stats_tab_text
    assert "Errors" not in stats_tab_text


def test_stats_formatter_shows_clear_fallbacks_for_unavailable_values(
    container_resource_stats_snapshot_factory,
) -> None:
    resource_stats_without_optional_values = container_resource_stats_snapshot_factory(
        container_uptime_seconds=None,
        container_health_status=None,
        container_restart_count=None,
        cpu_usage_percent=None,
        cpu_cores_used=None,
        cpu_limit_cores=None,
        cpu_limit_usage_percent=None,
        cpu_throttled_period_count=None,
        cpu_throttled_time_seconds=None,
        memory_usage_bytes=None,
        memory_cache_bytes=None,
        memory_limit_bytes=None,
        memory_available_bytes=None,
        memory_usage_percent=None,
        memory_swap_bytes=None,
        network_received_bytes=None,
        network_receive_rate_bytes_per_second=None,
        network_sent_bytes=None,
        network_send_rate_bytes_per_second=None,
        network_received_packet_count=None,
        network_sent_packet_count=None,
        block_read_bytes=None,
        block_read_rate_bytes_per_second=None,
        block_written_bytes=None,
        block_write_rate_bytes_per_second=None,
        current_process_and_thread_count=None,
        process_and_thread_limit=None,
    )

    stats_tab_text = format_container_resource_stats_tab_text(
        resource_stats_without_optional_values,
        refresh_interval_seconds=0.5,
    )

    assert "Refresh interval: 0.5 seconds" in stats_tab_text
    assert "Health          : not configured" in stats_tab_text
    assert "CPU limit       : No limit" in stats_tab_text
    assert "PID limit       : No limit" in stats_tab_text
    assert "Receive rate    : N/A" in stats_tab_text
