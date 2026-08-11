from __future__ import annotations

import pytest

from easy_docker_manager.tabs.config_tab_formatter import format_container_config


@pytest.fixture
def complete_inspection_data() -> dict:
    return {
        "container": {
            "Name": "/web",
            "Id": "1234567890abcdef",
            "Image": "sha256:abcdef1234567890",
            "Created": "2026-01-02T03:04:05Z",
            "RestartCount": 2,
            "Path": "python",
            "Args": ["-m", "app"],
            "Driver": "overlay2",
            "LogPath": "/var/log/container.log",
            "State": {
                "Status": "running",
                "Running": True,
                "Health": {"Status": "healthy"},
                "StartedAt": "2026-01-02T03:04:05Z",
                "FinishedAt": "0001-01-01T00:00:00Z",
                "Pid": 42,
                "ExitCode": 0,
            },
            "Config": {
                "Image": "web:latest",
                "Entrypoint": ["python"],
                "Cmd": ["-m", "app"],
                "WorkingDir": "/app",
                "User": "1000",
                "Tty": False,
                "OpenStdin": True,
                "Hostname": "web-host",
                "Domainname": "example.test",
                "ExposedPorts": {"8080/tcp": {}},
                "Volumes": {"/data": {}},
                "Labels": {
                    "com.docker.compose.project": "demo",
                    "owner": "team",
                },
            },
            "HostConfig": {
                "NetworkMode": "bridge",
                "Binds": ["/host:/data"],
                "Tmpfs": {"/tmp": "rw"},
                "Privileged": False,
                "ReadonlyRootfs": True,
                "Memory": 1_048_576,
                "MemorySwap": 2_097_152,
                "NanoCpus": 1_000_000_000,
                "CpuShares": 512,
                "CpuQuota": 100000,
                "CpusetCpus": "0-1",
                "PidsLimit": 100,
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "5m"}},
            },
            "NetworkSettings": {
                "Ports": {
                    "8080/tcp": [{"HostIp": "", "HostPort": "8080"}],
                    "9000/tcp": None,
                },
                "Networks": {
                    "bridge": {
                        "IPAddress": "172.17.0.2",
                        "Aliases": ["web"],
                    }
                },
            },
            "Storage": {"RootFS": {"Snapshot": {"Name": "snapshot-1"}}},
            "Mounts": [
                {
                    "Source": "/host",
                    "Destination": "/data",
                    "Mode": "rw",
                }
            ],
        },
        "image": {
            "RepoTags": ["web:latest"],
            "RepoDigests": ["web@sha256:123"],
            "Created": "2026-01-01T00:00:00Z",
            "DockerVersion": "27.0",
            "Author": "developer",
            "Os": "linux",
            "Architecture": "amd64",
            "Size": 1_048_576,
            "VirtualSize": 2_097_152,
            "RootFS": {"Layers": ["one", "two"]},
            "Config": {"Cmd": ["python"], "Shell": ["/bin/sh", "-c"]},
        },
    }


def test_empty_config_produces_empty_text() -> None:
    assert format_container_config({}) == ""


def test_formatted_config_contains_all_sections_and_readable_values(
    complete_inspection_data: dict,
) -> None:
    formatted_config = format_container_config(complete_inspection_data)

    for section in [
        "Identity",
        "State",
        "Image Build",
        "Runtime",
        "Network",
        "Mounts and Storage",
        "Resources and Security",
        "Logging",
        "Docker Compose",
        "Other Labels",
    ]:
        heading = f"== {section} =="
        assert (
            f"{'=' * len(heading)}\n{heading}\n{'=' * len(heading)}" in formatted_config
        )

    assert "1234567890ab" in formatted_config
    assert "abcdef123456" in formatted_config
    assert "1.0MB" in formatted_config
    assert "8080/tcp -> 0.0.0.0:8080" in formatted_config
    assert "9000/tcp -> <not published>" in formatted_config
    assert "bridge | 172.17.0.2 | aliases=web" in formatted_config
    assert "/host -> /data (rw)" in formatted_config
    assert "Project       : demo" in formatted_config
    assert "owner         : team" in formatted_config


def test_formatter_accepts_raw_container_inspection_data() -> None:
    formatted_config = format_container_config({"Name": "/worker", "Id": "abc"})

    assert "worker" in formatted_config
    assert "Container ID  : abc" in formatted_config
    assert "<none>" in formatted_config
