"""Collect and format information that helps troubleshoot EDM."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from enum import Enum
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Optional

from easy_docker_manager.config.app_config_store import default_config_path
from easy_docker_manager.core.docker_connections import DockerContextDetails
from easy_docker_manager.docker.container_client import DockerDaemonDetails
from easy_docker_manager.logging.app_logging import get_configured_log_file_path

EDM_DISTRIBUTION_NAME = "easy-docker-manager"
DOCKER_SDK_DISTRIBUTION_NAME = "docker"
UNKNOWN_VERSION = "unknown"


class DockerConnectionStatus(str, Enum):
    """Describe the current result of the Docker connection check."""

    CHECKING = "Checking..."
    CONNECTED = "Connected"
    FAILED = "Failed"


@dataclass(frozen=True)
class DiagnosticsReportField:
    """Hold one label and value shown in a diagnostics section."""

    label: str
    value: str


@dataclass(frozen=True)
class DiagnosticsReportSection:
    """Group related diagnostics fields under one title."""

    title: str
    fields: tuple[DiagnosticsReportField, ...]


@dataclass
class DiagnosticsReport:
    """Hold the application, file, and Docker details shown to the user.

    The command-line report and diagnostics popup both use this object. It is
    created with application details first, then updated after Docker answers
    the daemon version request or returns an error.
    """

    edm_version: str
    python_version: str
    docker_sdk_version: str
    config_file_path: Path
    application_log_file_path: Path
    docker_context_name: str = "localhost"
    docker_connection_status: DockerConnectionStatus = DockerConnectionStatus.CHECKING
    docker_daemon_details: Optional[DockerDaemonDetails] = None
    docker_connection_error_message: Optional[str] = None

    def record_successful_docker_connection(
        self,
        docker_daemon_details: DockerDaemonDetails,
    ) -> None:
        """Store daemon details after Docker answers the version request."""
        self.docker_connection_status = DockerConnectionStatus.CONNECTED
        self.docker_daemon_details = docker_daemon_details
        self.docker_connection_error_message = None

    def record_failed_docker_connection(self, error: BaseException) -> None:
        """Store a readable error after Docker cannot answer the request."""
        self.docker_connection_status = DockerConnectionStatus.FAILED
        self.docker_daemon_details = None
        self.docker_connection_error_message = _format_exception_message(error)


def get_installed_edm_version() -> str:
    """Return EDM's installed version, or unknown when metadata is unavailable."""
    return _get_installed_distribution_version(EDM_DISTRIBUTION_NAME)


def build_edm_version_label(edm_version: str) -> str:
    """Return the short version shown with the application logo."""
    if edm_version == UNKNOWN_VERSION:
        return ""
    short_version = edm_version.split("+", 1)[0]
    return f"v{short_version}"


def create_initial_diagnostics_report(
    docker_context: Optional[DockerContextDetails] = None,
) -> DiagnosticsReport:
    """Collect details that do not require a Docker request."""
    return DiagnosticsReport(
        edm_version=get_installed_edm_version(),
        python_version=platform.python_version(),
        docker_sdk_version=_get_installed_distribution_version(
            DOCKER_SDK_DISTRIBUTION_NAME
        ),
        docker_context_name=(
            docker_context.display_name if docker_context is not None else "localhost"
        ),
        config_file_path=default_config_path(),
        application_log_file_path=get_configured_log_file_path(),
    )


def format_diagnostics_report(
    report: DiagnosticsReport,
    *,
    include_heading: bool = True,
) -> str:
    """Build the plain text printed by the diagnostics command."""
    lines = []
    if include_heading:
        lines.extend(["Easy Docker Manager Diagnostics", ""])

    for section_index, section in enumerate(build_diagnostics_report_sections(report)):
        if section_index > 0:
            lines.append("")
        lines.append(section.title)
        lines.extend(
            _format_diagnostics_report_field(field) for field in section.fields
        )
    return "\n".join(lines)


def build_diagnostics_report_sections(
    report: DiagnosticsReport,
) -> tuple[DiagnosticsReportSection, ...]:
    """Return the report as titled sections containing label and value fields."""
    docker_daemon_details = report.docker_daemon_details
    daemon_version = (
        docker_daemon_details.daemon_version
        if docker_daemon_details and docker_daemon_details.daemon_version
        else "N/A"
    )
    api_version = (
        docker_daemon_details.api_version
        if docker_daemon_details and docker_daemon_details.api_version
        else "N/A"
    )
    docker_platform = _format_docker_platform(docker_daemon_details)

    docker_fields = [
        DiagnosticsReportField("Context", report.docker_context_name),
        DiagnosticsReportField(
            "Connection",
            report.docker_connection_status.value,
        ),
        DiagnosticsReportField("Daemon version", daemon_version),
        DiagnosticsReportField("API version", api_version),
        DiagnosticsReportField("Platform", docker_platform),
    ]
    if report.docker_connection_error_message:
        docker_fields.append(
            DiagnosticsReportField(
                "Error",
                report.docker_connection_error_message,
            ),
        )

    return (
        DiagnosticsReportSection(
            "Application",
            (
                DiagnosticsReportField("EDM version", report.edm_version),
                DiagnosticsReportField("Python version", report.python_version),
                DiagnosticsReportField(
                    "Docker SDK version",
                    report.docker_sdk_version,
                ),
            ),
        ),
        DiagnosticsReportSection(
            "Files",
            (
                DiagnosticsReportField(
                    "Config file",
                    _shorten_home_path(report.config_file_path),
                ),
                DiagnosticsReportField(
                    "Application log",
                    _shorten_home_path(report.application_log_file_path),
                ),
            ),
        ),
        DiagnosticsReportSection("Docker", tuple(docker_fields)),
    )


def _get_installed_distribution_version(distribution_name: str) -> str:
    """Read one installed distribution version without failing source runs."""
    try:
        return distribution_version(distribution_name)
    except PackageNotFoundError:
        return UNKNOWN_VERSION


def _format_diagnostics_report_field(field: DiagnosticsReportField) -> str:
    """Align one field label and value in the command-line report."""
    label_with_colon = f"{field.label}:"
    return f"  {label_with_colon:<22}{field.value}"


def _format_docker_platform(
    docker_daemon_details: Optional[DockerDaemonDetails],
) -> str:
    """Join the daemon operating system and architecture when available."""
    if docker_daemon_details is None:
        return "N/A"
    platform_parts = [
        value
        for value in (
            (
                docker_daemon_details.operating_system.capitalize()
                if docker_daemon_details.operating_system
                else None
            ),
            docker_daemon_details.architecture,
        )
        if value
    ]
    return " ".join(platform_parts) if platform_parts else "N/A"


def _shorten_home_path(path: Path) -> str:
    """Replace the current user's home directory with a tilde for display."""
    expanded_path = path.expanduser()
    try:
        path_below_home = expanded_path.relative_to(Path.home())
    except ValueError:
        return str(expanded_path)
    return str(Path("~") / path_below_home)


def _format_exception_message(error: BaseException) -> str:
    """Keep a Docker error on one readable line."""
    message = " ".join(str(error).split())
    return message or error.__class__.__name__


__all__ = [
    "DiagnosticsReport",
    "DiagnosticsReportField",
    "DiagnosticsReportSection",
    "DockerConnectionStatus",
    "build_edm_version_label",
    "build_diagnostics_report_sections",
    "create_initial_diagnostics_report",
    "format_diagnostics_report",
    "get_installed_edm_version",
]
