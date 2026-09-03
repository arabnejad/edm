"""Store Docker context details used by the terminal interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DockerConnectionTransport(str, Enum):
    """Identify how a Docker context reaches its daemon."""

    LOCAL = "local"
    SSH = "ssh"
    TCP = "tcp"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DockerContextDetails:
    """Describe one Docker context without opening its connection."""

    context_name: str
    docker_host: str
    transport: DockerConnectionTransport
    uses_docker_environment: bool = False

    @property
    def display_name(self) -> str:
        """Return the short name shown in EDM."""
        if (
            self.context_name == "default"
            and self.transport == DockerConnectionTransport.LOCAL
        ):
            return "localhost"
        return self.context_name

    @property
    def transport_label(self) -> str:
        """Return the connection type shown next to the context name."""
        if self.transport == DockerConnectionTransport.LOCAL:
            if self.docker_host.casefold().startswith("npipe://"):
                return "Named pipe"
            return "Local socket"
        if self.transport == DockerConnectionTransport.SSH:
            return "SSH"
        if self.transport == DockerConnectionTransport.TCP:
            return "TCP"
        return "Unsupported"

    @property
    def is_supported(self) -> bool:
        """Return whether this EDM version can open the context."""
        return self.transport in {
            DockerConnectionTransport.LOCAL,
            DockerConnectionTransport.SSH,
        }

    @property
    def unsupported_reason(self) -> str:
        """Explain why EDM cannot open this context yet."""
        if self.transport == DockerConnectionTransport.TCP:
            return "Remote TCP contexts require TLS support from issue #30."
        return "EDM does not support this Docker endpoint type."


@dataclass
class DockerConnectionMenuState:
    """Store the context list and selection while the popup is open."""

    docker_contexts: list[DockerContextDetails]
    active_context_name: str
    selected_context_index: int = 0
    context_name_being_validated: Optional[str] = None
    connection_error_messages: dict[str, str] = field(default_factory=dict)
    context_discovery_error_message: str = ""

    @property
    def selected_docker_context(self) -> Optional[DockerContextDetails]:
        """Return the selected context, or None when Docker returned no contexts."""
        if not self.docker_contexts:
            return None
        return self.docker_contexts[self.selected_context_index]


__all__ = [
    "DockerConnectionMenuState",
    "DockerConnectionTransport",
    "DockerContextDetails",
]
