"""Write a prepared container-tab snapshot to a UTF-8 text file."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Optional

from easy_docker_manager.core.tab_export import TabExportRequest


class ExportTargetExistsError(Exception):
    """Report that confirmation is needed before replacing an export file."""

    def __init__(self, target_path: Path) -> None:
        self.target_path = target_path
        super().__init__(f"File already exists: {target_path}")


class TabExportError(Exception):
    """Report why tab text could not be written to the selected path."""

    def __init__(self, target_path: Path, reason: str) -> None:
        self.target_path = target_path
        super().__init__(reason)


class TabContentExporter:
    """Write tab text without replacing an existing file by accident.

    TabExportController sends export_text() to BackgroundExecutor after the
    user confirms an export. A confirmed replacement is written to a temporary
    file first, so the existing file stays unchanged if the write fails.
    """

    def export_text(self, request: TabExportRequest) -> Path:
        """Write one tab snapshot and return the path that was saved.

        Existing files raise ExportTargetExistsError until the user confirms
        replacement. Invalid paths and failed writes raise TabExportError so
        the export menu can show a useful message.
        """
        target_path = request.target_path
        parent_directory = target_path.parent

        if not parent_directory.exists():
            raise TabExportError(
                target_path,
                f"Directory does not exist: {parent_directory}",
            )
        if not parent_directory.is_dir():
            raise TabExportError(
                target_path,
                f"Export parent is not a directory: {parent_directory}",
            )
        if target_path.is_dir():
            raise TabExportError(
                target_path,
                f"Export path is a directory: {target_path}",
            )

        if request.overwrite:
            self._replace_file(target_path, request.content)
        else:
            self._create_new_file(target_path, request.content)
        return target_path

    @staticmethod
    def _create_new_file(target_path: Path, content: str) -> None:
        """Create a new file and fail if the path is already in use."""
        file_was_created = False
        try:
            with target_path.open("x", encoding="utf-8", newline="\n") as export_file:
                file_was_created = True
                export_file.write(content)
        except FileExistsError as exc:
            raise ExportTargetExistsError(target_path) from exc
        except OSError as exc:
            # A write can fail after creating the file. Remove the incomplete
            # file so it cannot be mistaken for a successful export.
            if file_was_created:
                with suppress(OSError):
                    target_path.unlink(missing_ok=True)
            raise TabExportError(target_path, str(exc)) from exc

    @staticmethod
    def _replace_file(target_path: Path, content: str) -> None:
        """Replace a file only after all new content has been written."""
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=target_path.parent,
                prefix=f".{target_path.name}.",
                delete=False,
            ) as temporary_file:
                # Save the temporary path before writing so it can still be
                # removed when writing the content fails.
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
            os.replace(temporary_path, target_path)
        except OSError as exc:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)
            raise TabExportError(target_path, str(exc)) from exc


__all__ = ["ExportTargetExistsError", "TabContentExporter", "TabExportError"]
