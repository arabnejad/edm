from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from easy_docker_manager.tab_export.definitions import TabExportRequest
from easy_docker_manager.tab_export.writer import (
    ExportFileAlreadyExistsError,
    TabExportFileError,
    TabExportWriter,
)


def test_export_creates_a_utf8_text_file(tmp_path: Path) -> None:
    target_path = tmp_path / "environment.txt"

    saved_path = TabExportWriter().export_text(
        TabExportRequest(target_path, "NAME=caf\u00e9")
    )

    assert saved_path == target_path
    assert target_path.read_text(encoding="utf-8") == "NAME=caf\u00e9"


def test_export_requires_confirmation_before_replacing_a_file(
    tmp_path: Path,
) -> None:
    writer = TabExportWriter()
    target_path = tmp_path / "logs.log"
    target_path.write_text("old", encoding="utf-8")

    with pytest.raises(ExportFileAlreadyExistsError):
        writer.export_text(TabExportRequest(target_path, "new"))

    assert target_path.read_text(encoding="utf-8") == "old"

    writer.export_text(TabExportRequest(target_path, "new", allow_overwrite=True))
    assert target_path.read_text(encoding="utf-8") == "new"


@pytest.mark.parametrize("target_name", ["missing/output.txt", "folder"])
def test_export_reports_invalid_destination_paths(
    tmp_path: Path,
    target_name: str,
) -> None:
    target_path = tmp_path / target_name
    if target_name == "folder":
        target_path.mkdir()

    with pytest.raises(TabExportFileError):
        TabExportWriter().export_text(TabExportRequest(target_path, "text"))


def test_export_rejects_a_parent_path_that_is_not_a_directory(
    tmp_path: Path,
) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("text", encoding="utf-8")

    with pytest.raises(TabExportFileError, match="not a directory"):
        TabExportWriter().export_text(
            TabExportRequest(parent_file / "output.txt", "text")
        )


def test_open_failure_does_not_remove_a_file_the_export_did_not_create(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target_path = tmp_path / "output.txt"
    target_path.write_text("partial", encoding="utf-8")
    monkeypatch.setattr(Path, "open", Mock(side_effect=PermissionError("denied")))

    with pytest.raises(TabExportFileError, match="denied"):
        TabExportWriter._create_new_file(target_path, "text")

    assert target_path.exists()
    assert target_path.stat().st_size == len("partial")


def test_write_failure_removes_the_incomplete_new_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target_path = tmp_path / "output.txt"
    failing_file = MagicMock()

    def create_file_before_writing():
        target_path.touch()
        return failing_file

    failing_file.__enter__.side_effect = create_file_before_writing
    failing_file.write.side_effect = OSError("disk full")
    monkeypatch.setattr(Path, "open", Mock(return_value=failing_file))

    with pytest.raises(TabExportFileError, match="disk full"):
        TabExportWriter._create_new_file(target_path, "text")

    assert not target_path.exists()


def test_failed_confirmed_replacement_keeps_the_old_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target_path = tmp_path / "output.txt"
    target_path.write_text("old", encoding="utf-8")
    monkeypatch.setattr(
        "easy_docker_manager.tab_export.writer.os.replace",
        Mock(side_effect=PermissionError("denied")),
    )

    with pytest.raises(TabExportFileError, match="denied"):
        TabExportWriter._write_replacement_file(target_path, "new")

    assert target_path.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [target_path]


def test_failed_replacement_write_removes_its_temporary_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target_path = tmp_path / "output.txt"
    target_path.write_text("old", encoding="utf-8")
    temporary_path = tmp_path / ".output.txt.incomplete"
    failing_file = MagicMock()
    failing_file.name = str(temporary_path)

    def create_temporary_file_before_writing():
        temporary_path.touch()
        return failing_file

    failing_file.__enter__.side_effect = create_temporary_file_before_writing
    failing_file.write.side_effect = OSError("disk full")
    monkeypatch.setattr(
        "easy_docker_manager.tab_export.writer.tempfile.NamedTemporaryFile",
        Mock(return_value=failing_file),
    )

    with pytest.raises(TabExportFileError, match="disk full"):
        TabExportWriter._write_replacement_file(target_path, "new")

    assert target_path.read_text(encoding="utf-8") == "old"
    assert not temporary_path.exists()
