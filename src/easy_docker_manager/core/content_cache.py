"""Bounded cache for loaded tab content."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from easy_docker_manager.core.tabs import TabName


@dataclass(frozen=True)
class ContainerTabKey:
    """Identify one container and one of its detail tabs.

    This object is used as a key in caches and dictionaries. It is frozen so
    its hash cannot change after an entry has been stored, which keeps later
    lookups and removals reliable.
    """

    container_id: str
    tab_name: TabName


class LRUTabContentCache:
    """Keep recently viewed tab text within count and byte limits.

    Logs and Docker inspection data can be large. When either limit is exceeded,
    the cache removes the least recently used entries. This prevents cached tab
    content from growing without limit while the user visits many containers.
    """

    def __init__(
        self,
        max_entries: int,
        max_total_bytes: int,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        self.max_entries = max_entries
        self.max_total_bytes = max_total_bytes
        self._entries: OrderedDict[ContainerTabKey, str] = OrderedDict()
        self._total_size_bytes = 0

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def __getitem__(self, key: ContainerTabKey) -> str:
        value = self._entries[key]
        self._entries.move_to_end(key)
        return value

    def __setitem__(self, key: ContainerTabKey, value: str) -> None:
        fitted_value = self._fit_value_to_byte_limit(key, value)
        previous_value = self._entries.pop(key, None)
        if previous_value is not None:
            self._total_size_bytes -= self._utf8_size(previous_value)

        self._entries[key] = fitted_value
        self._total_size_bytes += self._utf8_size(fitted_value)
        self._entries.move_to_end(key)
        self._remove_oldest_entries_until_limits_met()

    def get(self, key: ContainerTabKey, default: Optional[str] = None) -> Optional[str]:
        """Return cached text and mark that entry as recently used."""
        if key not in self._entries:
            return default
        return self[key]

    @property
    def total_size_bytes(self) -> int:
        """Return the UTF-8 byte count tracked for all cached text."""
        return self._total_size_bytes

    def remove_stopped_container_entries(
        self,
        running_container_ids: set[str],
    ) -> None:
        """Remove cached tabs for containers that are no longer running."""
        stale_keys = [
            key
            for key in self._entries
            if key.container_id and key.container_id not in running_container_ids
        ]
        for key in stale_keys:
            removed_value = self._entries.pop(key)
            self._total_size_bytes -= self._utf8_size(removed_value)

    def clear(self) -> None:
        """Remove all cached tab data."""
        self._entries.clear()
        self._total_size_bytes = 0

    def __len__(self) -> int:
        return len(self._entries)

    def _remove_oldest_entries_until_limits_met(self) -> None:
        """Remove the oldest entries until both cache limits are met."""
        while (
            len(self._entries) > self.max_entries
            or self._total_size_bytes > self.max_total_bytes
        ):
            _, removed_value = self._entries.popitem(last=False)
            self._total_size_bytes -= self._utf8_size(removed_value)

    def _fit_value_to_byte_limit(self, key: ContainerTabKey, value: str) -> str:
        """Trim one value when it exceeds the cache's total byte limit."""
        encoded = value.encode("utf-8", errors="replace")
        if len(encoded) <= self.max_total_bytes:
            return value

        if key.tab_name == TabName.LOGS:
            encoded = encoded[-self.max_total_bytes :]
        else:
            encoded = encoded[: self.max_total_bytes]
        # The byte slice can cut through a multibyte character. Ignore only
        # that incomplete boundary character so decoding cannot add a larger
        # replacement character and push the value over the byte limit again.
        return encoded.decode("utf-8", errors="ignore")

    @staticmethod
    def _utf8_size(value: str) -> int:
        """Return the UTF-8 byte count for one text value."""
        return len(value.encode("utf-8", errors="replace"))


__all__ = ["ContainerTabKey", "LRUTabContentCache"]
