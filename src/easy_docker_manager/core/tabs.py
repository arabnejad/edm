"""Names of the detail tabs shown for a container."""

from __future__ import annotations

from enum import Enum


class TabName(str, Enum):
    """Detail tabs shown for the selected container."""

    LOGS = "Logs"
    ENV = "Env"
    CONFIG = "Config"
    TOP = "Top"


__all__ = ["TabName"]
