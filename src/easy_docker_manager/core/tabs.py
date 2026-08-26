"""Names of the detail tabs shown for a container."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TabName(str, Enum):
    """Detail tabs shown for the selected container."""

    LOGS = "Logs"
    ENV = "Env"
    CONFIG = "Config"
    TOP = "Top"


@dataclass(frozen=True)
class ContainerTabKey:
    """Identify one container and one of its detail tabs.

    EDM uses this object as a dictionary key for loaded text, search queries,
    loading errors, and background requests. It is frozen so its hash cannot
    change after storage, which keeps later lookups and removals reliable.
    """

    container_id: str
    tab_name: TabName


__all__ = ["ContainerTabKey", "TabName"]
