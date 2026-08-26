from __future__ import annotations

import pytest

from easy_docker_manager.core.log_text import (
    apply_character_limit_to_log_line,
    apply_limits_to_log_content,
    count_repeated_lines_between_batches,
)


def test_counting_repeated_lines_between_batches_finds_matching_lines() -> None:
    assert count_repeated_lines_between_batches(["A", "B", "C"], ["B", "C", "D"]) == 2


def test_counting_repeated_lines_handles_full_and_missing_matches() -> None:
    assert count_repeated_lines_between_batches(["A", "B"], ["A", "B"]) == 2
    assert count_repeated_lines_between_batches(["A"], ["B"]) == 0
    assert count_repeated_lines_between_batches([], ["A"]) == 0


def test_applying_log_content_limits_keeps_newest_lines_and_shortens_each_line() -> (
    None
):
    content = f"old\n{'x' * 100}\nnew"

    limited_content = apply_limits_to_log_content(
        content, max_lines=2, max_line_chars=30
    )

    assert limited_content.splitlines()[-1] == "new"
    assert "truncated" in limited_content.splitlines()[0]
    assert all(len(line) <= 30 for line in limited_content.splitlines())


def test_applying_character_limit_leaves_short_log_line_unchanged() -> None:
    assert apply_character_limit_to_log_line("short", max_line_chars=10) == "short"


def test_applying_character_limit_reports_the_actual_omitted_count() -> None:
    unchanged_line = apply_character_limit_to_log_line("abcdefghij", max_line_chars=30)
    assert unchanged_line == "abcdefghij"

    trimmed_line = apply_character_limit_to_log_line("a" * 100, max_line_chars=30)
    assert len(trimmed_line) == 30
    assert trimmed_line.endswith("[truncated 95 chars]")


def test_applying_character_limit_keeps_a_limit_smaller_than_the_message() -> None:
    assert apply_character_limit_to_log_line("abcdefghij", max_line_chars=3) == "abc"


def test_applying_character_limit_rejects_a_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="max_line_chars must be positive"):
        apply_character_limit_to_log_line("text", max_line_chars=0)
