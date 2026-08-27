from __future__ import annotations

from dataclasses import dataclass

from docker.models.containers import Container


@dataclass
class DockerIntegrationTestContainer:
    """Hold the temporary container and the values configured on it."""

    container: Container
    log_message: str
    environment: dict[str, str]
    labels: dict[str, str]
