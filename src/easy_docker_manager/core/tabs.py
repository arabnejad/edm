"""Names of the detail tabs shown for a container."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

CONTAINER_NOT_RUNNING_MESSAGE = "Container is not running."


class TabName(str, Enum):
    """Detail tabs shown for the selected container."""

    LOGS = "Logs"
    ENV = "Env"
    CONFIG = "Config"
    STATS = "Stats"
    TOP = "Top"

    @property
    def requires_running_container(self) -> bool:
        """Return whether this tab needs a running container."""
        return self in (TabName.STATS, TabName.TOP)


@dataclass(frozen=True)
class ContainerTabKey:
    """Identify one container and one of its detail tabs.

    EDM uses this object as a dictionary key for loaded text, search queries,
    loading errors, and background requests. It is frozen so its hash cannot
    change after storage, which keeps later lookups and removals reliable.
    """

    container_id: str
    tab_name: TabName


__all__ = ["CONTAINER_NOT_RUNNING_MESSAGE", "ContainerTabKey", "TabName"]
