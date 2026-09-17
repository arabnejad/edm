from __future__ import annotations

from datetime import timedelta, timezone

import pytest

from easy_docker_manager.core.log_text import (
    DOCKER_UTC_LOG_TIMESTAMP_MODE,
    HIDDEN_LOG_TIMESTAMP_MODE,
    LOCAL_LOG_TIMESTAMP_MODE,
    apply_character_limit_to_log_line,
    apply_limits_to_log_content,
    apply_log_timestamp_mode,
    count_repeated_lines_between_batches,
    prepare_container_log_batch,
)


def test_counting_repeated_lines_between_batches_finds_matching_lines() -> None:
    assert count_repeated_lines_between_batches(["A", "B", "C"], ["B", "C", "D"]) == 2


def test_counting_repeated_lines_handles_full_and_missing_matches() -> None:
    assert count_repeated_lines_between_batches(["A", "B"], ["A", "B"]) == 2
    assert count_repeated_lines_between_batches(["A"], ["B"]) == 0
    assert count_repeated_lines_between_batches([], ["A"]) == 0


def test_docker_utc_timestamp_mode_keeps_log_text_unchanged() -> None:
    content = "2026-01-01T12:00:00.123456789Z server started"

    assert apply_log_timestamp_mode(content, DOCKER_UTC_LOG_TIMESTAMP_MODE) == content


def test_unknown_timestamp_mode_keeps_log_text_unchanged() -> None:
    content = "2026-01-01T12:00:00.123456789Z server started"

    assert apply_log_timestamp_mode(content, "Unknown") == content


def test_hidden_timestamp_mode_removes_only_the_docker_prefix() -> None:
    content = "2026-01-01T12:00:00.123456789Z " "application time 2026-01-01T11:59:59Z"

    assert apply_log_timestamp_mode(content, HIDDEN_LOG_TIMESTAMP_MODE) == (
        "application time 2026-01-01T11:59:59Z"
    )


def test_local_timestamp_mode_converts_time_and_keeps_nanoseconds() -> None:
    content = "2026-01-01T12:00:00.123456789Z server started"

    formatted_content = apply_log_timestamp_mode(
        content,
        LOCAL_LOG_TIMESTAMP_MODE,
        timezone(timedelta(hours=-5, minutes=-30)),
    )

    assert formatted_content == ("2026-01-01T06:30:00.123456789-05:30 server started")


def test_prepared_hidden_log_lines_keep_different_source_fingerprints() -> None:
    prepared_batch = prepare_container_log_batch(
        "2026-01-01T12:00:00Z ready\n2026-01-01T12:00:01Z ready",
        HIDDEN_LOG_TIMESTAMP_MODE,
        max_lines=10,
        max_line_chars=100,
    )

    assert prepared_batch.display_text == "ready\nready"
    assert len(set(prepared_batch.source_line_fingerprints)) == 2


@pytest.mark.parametrize(
    "timestamp_mode",
    [HIDDEN_LOG_TIMESTAMP_MODE, LOCAL_LOG_TIMESTAMP_MODE],
)
def test_timestamp_mode_leaves_invalid_and_unprefixed_lines_unchanged(
    timestamp_mode: str,
) -> None:
    content = (
        "2026-02-30T12:00:00Z invalid date\n"
        "2026-01-01T12:00:00.1234567890Z too precise\n"
        "plain log line"
    )

    assert apply_log_timestamp_mode(content, timestamp_mode) == content


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
