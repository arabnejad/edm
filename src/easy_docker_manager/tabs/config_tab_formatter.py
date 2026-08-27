"""Turn Docker inspection data into the Config tab text."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def format_container_config(config_data: dict[str, Any]) -> str:
    """Build the grouped Config tab summary from Docker inspection data."""
    if not config_data:
        return ""

    container = _as_dict(config_data.get("container") or config_data)
    image = _as_dict(config_data.get("image"))
    config = _as_dict(container.get("Config"))
    host_config = _as_dict(container.get("HostConfig"))
    state = _as_dict(container.get("State"))
    network_settings = _as_dict(container.get("NetworkSettings"))
    image_config = _as_dict(image.get("Config"))
    image_rootfs = _as_dict(image.get("RootFS"))
    labels = _as_dict(config.get("Labels"))

    lines: list[str] = []
    _add_identity_section(lines, container, image, config)
    _add_state_section(lines, container, state)
    _add_image_section(lines, container, image, image_rootfs)
    _add_runtime_section(lines, container, config, image_config)
    _add_network_section(lines, config, host_config, network_settings)
    _add_storage_section(lines, container, host_config)
    _add_resources_section(lines, host_config)
    _add_logging_section(lines, container, host_config)
    _add_labels_sections(lines, labels)
    return "\n".join(lines)


def _add_identity_section(
    lines: list[str],
    container: dict[str, Any],
    image: dict[str, Any],
    config: dict[str, Any],
) -> None:
    """Add container and image identity fields."""

    _add_section(lines, "Identity")
    _add_field(lines, "Name", str(container.get("Name", "")).lstrip("/"))
    _add_field(lines, "Container ID", _short_id(container.get("Id")))
    _add_field(lines, "Full ID", container.get("Id"))
    _add_field(lines, "Image", config.get("Image"))
    _add_field(lines, "Image ID", _short_image_id(container.get("Image")))
    _add_field(lines, "Image Tags", image.get("RepoTags"))
    _add_field(lines, "Image Digests", image.get("RepoDigests"))


def _add_state_section(
    lines: list[str],
    container: dict[str, Any],
    state: dict[str, Any],
) -> None:
    """Add current status, start time, finish time, and exit fields."""
    _add_section(lines, "State")
    _add_field(lines, "Status", state.get("Status"))
    _add_field(lines, "Running", state.get("Running"))
    _add_field(lines, "Health", _as_dict(state.get("Health")).get("Status"))
    _add_field(lines, "Started At", _format_timestamp(state.get("StartedAt")))
    _add_field(lines, "Finished At", _format_timestamp(state.get("FinishedAt")))
    _add_field(lines, "Restart Count", container.get("RestartCount"))
    _add_field(lines, "PID", state.get("Pid"))
    _add_field(lines, "Exit Code", state.get("ExitCode"))


def _add_image_section(
    lines: list[str],
    container: dict[str, Any],
    image: dict[str, Any],
    image_rootfs: dict[str, Any],
) -> None:
    """Add image build and size fields."""
    _add_section(lines, "Image Build")
    _add_field(
        lines,
        "Created",
        _format_timestamp(image.get("Created") or container.get("Created")),
    )
    _add_field(lines, "Docker Ver", image.get("DockerVersion"))
    _add_field(lines, "Author", image.get("Author"))
    _add_field(lines, "OS", image.get("Os") or image.get("OS"))
    _add_field(lines, "Architecture", image.get("Architecture"))
    _add_field(lines, "Image Size", _format_bytes(image.get("Size")))
    _add_field(lines, "Virtual Size", _format_bytes(image.get("VirtualSize")))
    _add_field(lines, "Layers", len(image_rootfs.get("Layers") or []))


def _add_runtime_section(
    lines: list[str],
    container: dict[str, Any],
    config: dict[str, Any],
    image_config: dict[str, Any],
) -> None:
    """Add command, user, terminal, port, and volume fields."""
    _add_section(lines, "Runtime")
    _add_field(lines, "Path", container.get("Path"))
    _add_field(lines, "Args", container.get("Args"))
    _add_field(lines, "Entrypoint", config.get("Entrypoint"))
    _add_field(lines, "CMD", config.get("Cmd"))
    _add_field(lines, "Image CMD", image_config.get("Cmd"))
    _add_field(lines, "Shell", image_config.get("Shell"))
    _add_field(
        lines, "WorkDir", config.get("WorkingDir") or image_config.get("WorkingDir")
    )
    _add_field(lines, "User", config.get("User") or image_config.get("User"))
    _add_field(lines, "TTY", config.get("Tty"))
    _add_field(lines, "Open Stdin", config.get("OpenStdin"))
    _add_field(lines, "Exposed Ports", _format_keys(config.get("ExposedPorts")))
    _add_field(
        lines,
        "Volumes",
        _format_keys(config.get("Volumes") or image_config.get("Volumes")),
    )


def _add_network_section(
    lines: list[str],
    config: dict[str, Any],
    host_config: dict[str, Any],
    network_settings: dict[str, Any],
) -> None:
    """Add hostname, port, and network attachment fields."""
    _add_section(lines, "Network")
    _add_field(lines, "Hostname", config.get("Hostname"))
    _add_field(lines, "Domain", config.get("Domainname"))
    _add_field(lines, "Network Mode", host_config.get("NetworkMode"))
    _add_field(lines, "Ports", _format_ports(network_settings.get("Ports")))
    for network_line in _format_networks(network_settings.get("Networks")):
        _add_field(lines, "Network", network_line)


def _add_storage_section(
    lines: list[str],
    container: dict[str, Any],
    host_config: dict[str, Any],
) -> None:
    """Add storage driver, mount, bind, and tmpfs fields."""
    _add_section(lines, "Mounts and Storage")
    _add_field(lines, "Driver", container.get("Driver"))
    _add_field(lines, "Storage", _format_storage(container.get("Storage")))
    _add_field(lines, "Mounts", _format_mounts(container.get("Mounts")))
    _add_field(lines, "Binds", host_config.get("Binds"))
    _add_field(lines, "Tmpfs", host_config.get("Tmpfs"))


def _add_resources_section(
    lines: list[str],
    host_config: dict[str, Any],
) -> None:
    """Add resource limits and security settings."""
    _add_section(lines, "Resources and Security")
    _add_field(lines, "Privileged", host_config.get("Privileged"))
    _add_field(lines, "Readonly FS", host_config.get("ReadonlyRootfs"))
    _add_field(lines, "Userns Mode", host_config.get("UsernsMode"))
    _add_field(lines, "PID Mode", host_config.get("PidMode"))
    _add_field(lines, "IPC Mode", host_config.get("IpcMode"))
    _add_field(lines, "Runtime", host_config.get("Runtime"))
    _add_field(lines, "Cap Add", host_config.get("CapAdd"))
    _add_field(lines, "Cap Drop", host_config.get("CapDrop"))
    _add_field(lines, "Security Opt", host_config.get("SecurityOpt"))
    _add_field(lines, "Memory", _format_bytes(host_config.get("Memory")))
    _add_field(lines, "Memory Swap", _format_bytes(host_config.get("MemorySwap")))
    _add_field(lines, "Nano CPUs", host_config.get("NanoCpus"))
    _add_field(lines, "CPU Shares", host_config.get("CpuShares"))
    _add_field(lines, "CPU Quota", host_config.get("CpuQuota"))
    _add_field(lines, "CPU Set", host_config.get("CpusetCpus"))
    _add_field(lines, "PIDs Limit", host_config.get("PidsLimit"))


def _add_logging_section(
    lines: list[str],
    container: dict[str, Any],
    host_config: dict[str, Any],
) -> None:
    """Add Docker logging driver and path fields."""
    _add_section(lines, "Logging")
    log_config = _as_dict(host_config.get("LogConfig"))
    _add_field(lines, "Driver", log_config.get("Type"))
    _add_field(lines, "Options", log_config.get("Config"))
    _add_field(lines, "Log Path", container.get("LogPath"))


def _add_labels_sections(lines: list[str], labels: dict[str, Any]) -> None:
    """Add Docker Compose and other container labels."""
    _add_section(lines, "Docker Compose")
    compose_labels = {
        key.removeprefix("com.docker.compose."): value
        for key, value in labels.items()
        if key.startswith("com.docker.compose.")
    }
    if compose_labels:
        for key in sorted(compose_labels):
            _add_field(lines, key.replace("_", " ").title(), compose_labels[key])
    else:
        _add_field(lines, "Compose", None)

    other_labels = {
        key: value
        for key, value in labels.items()
        if not key.startswith("com.docker.compose.")
    }
    if other_labels:
        _add_section(lines, "Other Labels")
        for key in sorted(other_labels):
            _add_field(lines, key, other_labels[key])


def _add_section(lines: list[str], title: str) -> None:
    """Append a readable section header."""
    if lines:
        lines.append("")
    heading = f"== {title} =="
    border = "=" * len(heading)
    lines.extend([border, heading, border])


def _add_field(lines: list[str], label: str, value: Any) -> None:
    """Append one label/value row."""
    lines.append(f"  {label:<14}: {_format_value(value)}")


def _as_dict(value: Any) -> dict[str, Any]:
    """Return value when it is a dictionary, otherwise return an empty one."""
    return value if isinstance(value, dict) else {}


def _format_value(value: Any) -> str:
    """Return a compact display string for config values."""
    if value is None or value == "" or value == [] or value == {}:
        return "<none>"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(", ", ": "))
    return str(value)


def _short_id(value: Any) -> str:
    """Return the first 12 characters of an identifier."""
    text = str(value or "")
    return text[:12] if text else "<none>"


def _short_image_id(value: Any) -> str:
    """Return a shortened image id without the sha256 prefix."""
    text = str(value or "")
    if text.startswith("sha256:"):
        text = text.removeprefix("sha256:")
    return text[:12] if text else "<none>"


def _format_timestamp(value: Any) -> str:
    """Convert a Docker timestamp to local time when it can be parsed."""
    text = str(value or "")
    if not text or text.startswith("0001-01-01"):
        return "<none>"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return text


def _format_bytes(value: Any) -> str:
    """Return bytes as a compact human-readable size."""
    if value in (None, "", 0):
        return "<none>" if value in (None, "") else "0B"
    try:
        size = float(value)
    except (TypeError, ValueError):
        return str(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)}{units[unit_index]}"
    return f"{size:.1f}{units[unit_index]}"


def _format_keys(value: Any) -> str:
    """Return sorted dictionary keys as a comma-separated string."""
    if not isinstance(value, dict) or not value:
        return "<none>"
    return ", ".join(sorted(value))


def _format_ports(value: Any) -> str:
    """Return Docker port mappings as compact text."""
    if not isinstance(value, dict) or not value:
        return "<none>"
    mappings: list[str] = []
    for container_port, host_bindings in sorted(value.items()):
        if not host_bindings:
            mappings.append(f"{container_port} -> <not published>")
            continue
        targets = []
        for binding in host_bindings:
            # Docker reports all-interface published ports as 0.0.0.0.
            host_ip = binding.get("HostIp") or "0.0.0.0"  # noqa: S104  # nosec B104
            host_port = binding.get("HostPort") or ""
            targets.append(f"{host_ip}:{host_port}" if host_port else host_ip)
        mappings.append(f"{container_port} -> {', '.join(targets)}")
    return "; ".join(mappings)


def _format_networks(value: Any) -> list[str]:
    """Return one display row per Docker network attachment."""
    if not isinstance(value, dict) or not value:
        return ["<none>"]
    rows: list[str] = []
    for name, data in sorted(value.items()):
        details = _as_dict(data)
        parts = [name]
        if details.get("IPAddress"):
            parts.append(str(details["IPAddress"]))
        if details.get("GlobalIPv6Address"):
            parts.append(str(details["GlobalIPv6Address"]))
        aliases = details.get("Aliases") or []
        if aliases:
            parts.append(f"aliases={', '.join(str(alias) for alias in aliases)}")
        rows.append(" | ".join(parts))
    return rows


def _format_storage(value: Any) -> str:
    """Return a compact storage summary."""
    storage = _as_dict(value)
    rootfs = _as_dict(storage.get("RootFS"))
    snapshot = _as_dict(rootfs.get("Snapshot"))
    return snapshot.get("Name") or _format_value(storage)


def _format_mounts(value: Any) -> str:
    """Return a compact mount summary without raw inspect noise."""
    if not isinstance(value, list) or not value:
        return "<none>"
    mounts = []
    for mount in value:
        data = _as_dict(mount)
        source = data.get("Source") or "<anonymous>"
        destination = data.get("Destination") or "<unknown>"
        mode = data.get("Mode") or data.get("RW")
        mounts.append(f"{source} -> {destination} ({mode})")
    return "; ".join(mounts)


__all__ = ["format_container_config"]
