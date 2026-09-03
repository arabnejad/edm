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
    """Describe one Docker context without opening its connection.

    For TCP contexts, the TLS fields record whether Docker loaded the three
    certificate files and whether it will verify the remote server.
    """

    context_name: str
    docker_host: str
    transport: DockerConnectionTransport
    uses_docker_environment: bool = False
    has_required_tls_certificate_files: bool = False
    verifies_tls_server_certificate: bool = False

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
            return "TCP + TLS" if self.has_required_tls_certificate_files else "TCP"
        return "Unsupported"

    @property
    def uses_verified_tls(self) -> bool:
        """Return whether certificates exist and server verification is enabled."""
        return (
            self.has_required_tls_certificate_files
            and self.verifies_tls_server_certificate
        )

    @property
    def is_supported(self) -> bool:
        """Return whether this EDM version can open the context."""
        return self.transport in {
            DockerConnectionTransport.LOCAL,
            DockerConnectionTransport.SSH,
        } or (
            self.transport == DockerConnectionTransport.TCP and self.uses_verified_tls
        )

    @property
    def unsupported_reason(self) -> str:
        """Explain why EDM cannot open this context yet."""
        if self.transport == DockerConnectionTransport.TCP:
            if not self.has_required_tls_certificate_files:
                return (
                    "TCP contexts need a CA certificate, client certificate, "
                    "and private key."
                )
            if not self.verifies_tls_server_certificate:
                return "TCP contexts must verify the Docker server certificate."
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
