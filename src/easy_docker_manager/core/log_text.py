"""Limit and merge Docker log text before it reaches the UI."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from hashlib import sha256
from typing import Optional

MIN_LOG_LINE_CHARS = 32
DOCKER_UTC_LOG_TIMESTAMP_MODE = "Docker UTC"
LOCAL_LOG_TIMESTAMP_MODE = "Local time"
HIDDEN_LOG_TIMESTAMP_MODE = "Hidden"
LOG_TIMESTAMP_MODE_NAMES = (
    DOCKER_UTC_LOG_TIMESTAMP_MODE,
    LOCAL_LOG_TIMESTAMP_MODE,
    HIDDEN_LOG_TIMESTAMP_MODE,
)

DOCKER_TIMESTAMPED_LOG_LINE = re.compile(
    r"^(?P<seconds>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?P<fraction>\.\d{1,9})?Z (?P<message>.*)$"
)


@dataclass(frozen=True)
class PreparedContainerLogBatch:
    """Keep display lines matched to the Docker lines they came from."""

    display_lines: tuple[str, ...]
    source_line_fingerprints: tuple[bytes, ...]

    @property
    def display_text(self) -> str:
        """Join the prepared lines for the tab cache."""
        return "\n".join(self.display_lines)


def prepare_container_log_batch(
    log_text: str,
    timestamp_mode: str,
    *,
    max_lines: int,
    max_line_chars: int,
    local_timezone: Optional[tzinfo] = None,
) -> PreparedContainerLogBatch:
    """Prepare bounded display lines while keeping their original identities."""
    source_lines = log_text.splitlines()
    if len(source_lines) > max_lines:
        source_lines = source_lines[-max_lines:]

    display_lines = tuple(
        apply_character_limit_to_log_line(
            apply_log_timestamp_mode(source_line, timestamp_mode, local_timezone),
            max_line_chars=max_line_chars,
        )
        for source_line in source_lines
    )
    return PreparedContainerLogBatch(
        display_lines=display_lines,
        source_line_fingerprints=tuple(
            sha256(source_line.encode("utf-8")).digest() for source_line in source_lines
        ),
    )


def apply_log_timestamp_mode(
    log_text: str,
    timestamp_mode: str,
    local_timezone: Optional[tzinfo] = None,
) -> str:
    """Keep, convert, or hide the Docker timestamp at the start of each line."""
    if timestamp_mode not in {HIDDEN_LOG_TIMESTAMP_MODE, LOCAL_LOG_TIMESTAMP_MODE}:
        return log_text
    return "\n".join(
        _apply_log_timestamp_mode_to_line(line, timestamp_mode, local_timezone)
        for line in log_text.splitlines()
    )


def _apply_log_timestamp_mode_to_line(
    line: str,
    timestamp_mode: str,
    local_timezone: Optional[tzinfo],
) -> str:
    """Change one valid Docker timestamp prefix and leave other lines alone."""
    log_line_match = DOCKER_TIMESTAMPED_LOG_LINE.match(line)
    if log_line_match is None:
        return line

    try:
        utc_timestamp = datetime.strptime(
            log_line_match.group("seconds"),
            "%Y-%m-%dT%H:%M:%S",
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return line

    if timestamp_mode == HIDDEN_LOG_TIMESTAMP_MODE:
        return log_line_match.group("message")

    local_timestamp = utc_timestamp.astimezone(local_timezone)
    utc_offset = local_timestamp.strftime("%z")
    utc_offset_with_colon = f"{utc_offset[:3]}:{utc_offset[3:]}"
    fraction = log_line_match.group("fraction") or ""
    return (
        f"{local_timestamp:%Y-%m-%dT%H:%M:%S}{fraction}"
        f"{utc_offset_with_colon} {log_line_match.group('message')}"
    )


def count_repeated_lines_between_batches(
    existing_lines: Sequence[object],
    incoming_lines: Sequence[object],
) -> int:
    """Return the number of duplicate lines where two log batches meet.

    Docker can return some of the same lines in two consecutive requests. This
    function compares the end of existing_lines with the start of incoming_lines.

    For example:

        existing_lines = ["A", "B", "C"]
        incoming_lines = ["B", "C", "D"]

    The function returns 2 because "B" and "C" appear at the end of the existing
    logs and again at the start of the incoming logs. The caller can then append
    incoming_lines[2:], which adds only "D".

    Every possible overlap is checked in one pass, without repeatedly slicing
    and comparing the two lists.
    """
    if not existing_lines or not incoming_lines:
        return 0

    separator = object()
    lines: list[object] = [
        *incoming_lines,
        separator,
        *existing_lines[-len(incoming_lines) :],
    ]
    prefix_lengths = [0] * len(lines)

    for index in range(1, len(lines)):
        matched = prefix_lengths[index - 1]
        while matched and lines[index] != lines[matched]:
            matched = prefix_lengths[matched - 1]
        if lines[index] == lines[matched]:
            matched += 1
        prefix_lengths[index] = matched

    return prefix_lengths[-1]


def apply_limits_to_log_content(
    content: str, *, max_lines: int, max_line_chars: int
) -> str:
    """Apply line count and line length limits to log content.

    A small response can still contain a very long JSON or stack-trace line.
    ContainerTabTextLoader limits the first Logs response in a worker thread.
    ContainerLogUpdater limits later batches in a worker and limits the full
    cached history again after merging.

    For example:

        apply_limits_to_log_content("old\nnew", max_lines=1, max_line_chars=100)

    returns "new" because only the newest line is kept.
    """
    lines = content.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(
        apply_character_limit_to_log_line(line, max_line_chars=max_line_chars)
        for line in lines
    )


def apply_character_limit_to_log_line(line: str, *, max_line_chars: int) -> str:
    """Shorten one log line and show how many characters were removed."""
    if max_line_chars <= 0:
        raise ValueError("max_line_chars must be positive")
    if len(line) <= max_line_chars:
        return line

    omitted_chars = len(line) - max_line_chars
    while True:
        marker = f" ... [truncated {omitted_chars} chars]"
        visible_chars = max(0, max_line_chars - len(marker))
        actual_omitted_chars = len(line) - visible_chars
        if actual_omitted_chars == omitted_chars:
            break
        omitted_chars = actual_omitted_chars

    # If the truncation message does not fit, return only the start of the line.
    if len(marker) >= max_line_chars:
        return line[:max_line_chars]
    return f"{line[:visible_chars]}{marker}"


__all__ = [
    "DOCKER_UTC_LOG_TIMESTAMP_MODE",
    "HIDDEN_LOG_TIMESTAMP_MODE",
    "LOCAL_LOG_TIMESTAMP_MODE",
    "LOG_TIMESTAMP_MODE_NAMES",
    "MIN_LOG_LINE_CHARS",
    "PreparedContainerLogBatch",
    "apply_log_timestamp_mode",
    "apply_character_limit_to_log_line",
    "apply_limits_to_log_content",
    "count_repeated_lines_between_batches",
    "prepare_container_log_batch",
]
