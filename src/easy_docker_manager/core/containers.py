"""Container data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContainerSummary:
    """Container details displayed and sorted in the terminal UI.

    Docker supplies the id, name, status, image name, and creation time for
    every listed container, so all five fields are required. The sorting code
    still handles an explicitly empty image name or creation time by placing
    that container at the end in container-id order.
    """

    container_id: str
    name: str
    status: str
    image_name: str
    created_at: str


@dataclass
class ContainerProcessTable:
    """Column names and rows returned by Docker's top command."""

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


__all__ = ["ContainerProcessTable", "ContainerSummary"]
