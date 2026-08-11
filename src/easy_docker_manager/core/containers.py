"""Container data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContainerSummary:
    """Container details needed by the list in the terminal UI."""

    container_id: str
    name: str
    status: str


@dataclass
class ContainerProcessTable:
    """Column names and rows returned by Docker's top command."""

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


__all__ = ["ContainerProcessTable", "ContainerSummary"]
