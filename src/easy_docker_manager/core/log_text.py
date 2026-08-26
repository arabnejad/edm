"""Limit and merge Docker log text before it reaches the UI."""

from __future__ import annotations

from collections.abc import Sequence

MIN_LOG_LINE_CHARS = 32


def count_repeated_lines_between_batches(
    existing_lines: Sequence[str],
    incoming_lines: Sequence[str],
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

    The function checks every possible overlap in one pass instead of repeatedly
    slicing and comparing the two lists.
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

    Even a response containing only a few recent log lines can include a very
    long JSON or stack-trace line. The tab loader and DockerManager call
    this before caching logs, which keeps the newest lines visible without
    making the terminal UI handle very large rows.

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

    # Direct callers may supply a limit smaller than the explanatory marker.
    # In that case, return a plain prefix so the requested limit is still kept.
    if len(marker) >= max_line_chars:
        return line[:max_line_chars]
    return f"{line[:visible_chars]}{marker}"


__all__ = [
    "MIN_LOG_LINE_CHARS",
    "apply_character_limit_to_log_line",
    "apply_limits_to_log_content",
    "count_repeated_lines_between_batches",
]
