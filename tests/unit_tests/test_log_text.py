from __future__ import annotations

import pytest

from easy_docker_manager.core.log_text import (
    count_line_overlap,
    trim_log_line,
    trim_log_text,
)


def test_count_line_overlap_finds_repeated_batch_boundary() -> None:
    assert count_line_overlap(["A", "B", "C"], ["B", "C", "D"]) == 2


def test_count_line_overlap_handles_full_and_missing_overlap() -> None:
    assert count_line_overlap(["A", "B"], ["A", "B"]) == 2
    assert count_line_overlap(["A"], ["B"]) == 0
    assert count_line_overlap([], ["A"]) == 0


def test_trim_log_text_keeps_newest_lines_and_shortens_each_line() -> None:
    content = f"old\n{'x' * 100}\nnew"

    trimmed_text = trim_log_text(content, max_lines=2, max_line_chars=30)

    assert trimmed_text.splitlines()[-1] == "new"
    assert "truncated" in trimmed_text.splitlines()[0]
    assert all(len(line) <= 30 for line in trimmed_text.splitlines())


def test_trim_log_line_leaves_short_text_unchanged() -> None:
    assert trim_log_line("short", max_line_chars=10) == "short"


def test_trim_log_line_reports_the_actual_omitted_count() -> None:
    unchanged_line = trim_log_line("abcdefghij", max_line_chars=30)
    assert unchanged_line == "abcdefghij"

    trimmed_line = trim_log_line("a" * 100, max_line_chars=30)
    assert len(trimmed_line) == 30
    assert trimmed_line.endswith("[truncated 95 chars]")


def test_trim_log_line_keeps_a_limit_smaller_than_the_truncation_message() -> None:
    assert trim_log_line("abcdefghij", max_line_chars=3) == "abc"


def test_trim_log_line_rejects_a_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="max_line_chars must be positive"):
        trim_log_line("text", max_line_chars=0)
