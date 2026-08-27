"""Tell EDMApp when background work is ready to process.

Background threads cannot update the terminal UI directly. On Unix-like
systems, a pipe wakes the UI as soon as a task finishes. On Windows, a timer
checks for finished tasks every 0.2 seconds. Both methods run the callback on
the UI thread, where it is safe to update the screen.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from threading import Lock
from typing import Any, Optional

import urwid

logger = logging.getLogger(__name__)

BackgroundTaskReadyCallback = Callable[[bytes], None]


class BackgroundNotifier(ABC):
    """Arrange for EDMApp to process finished work on the UI thread."""

    @abstractmethod
    def start(
        self,
        loop: urwid.MainLoop,
        callback: BackgroundTaskReadyCallback,
    ) -> None:
        """Connect the notifier to Urwid's running event loop.

        MainLoop handles keyboard input, timers, and screen updates. Registering
        callback here ensures that finished work is also handled on that thread.
        """

    @abstractmethod
    def notify(self) -> None:
        """Tell EDMApp that one or more worker results are ready."""

    @abstractmethod
    def stop(self) -> None:
        """Stop notifications and remove the pipe or timer from Urwid."""


class PipeBackgroundNotifier(BackgroundNotifier):
    """Notify EDMApp through a pipe on Unix-like operating systems.

    Linux and macOS support Urwid's watch_pipe feature. When background work
    finishes, notify() writes one byte to the pipe. Urwid detects the byte and
    immediately runs EDMApp's callback on the UI thread. No timer is needed;
    the pipe itself tells Urwid that work is ready.
    """

    def __init__(self) -> None:
        self._loop: Optional[urwid.MainLoop] = None
        self._pipe_write: Optional[int] = None
        self._lock = Lock()

    def start(
        self,
        loop: urwid.MainLoop,
        callback: BackgroundTaskReadyCallback,
    ) -> None:
        """Register a pipe that runs callback on the Urwid UI thread."""
        watch_pipe = getattr(loop, "watch_pipe", None)
        if not callable(watch_pipe):
            raise RuntimeError("Urwid watch_pipe is not available on this platform")
        with self._lock:
            self._loop = loop
            self._pipe_write = watch_pipe(callback)

    def notify(self) -> None:
        """Write one byte to wake the Urwid pipe watcher."""
        with self._lock:
            if self._pipe_write is None:
                return
            try:
                os.write(self._pipe_write, b"x")
            except OSError:
                logger.debug("Unable to notify the terminal UI event loop")

    def stop(self) -> None:
        """Remove the pipe watcher and close its write descriptor."""
        with self._lock:
            loop = self._loop
            pipe_write = self._pipe_write
            self._loop = None
            self._pipe_write = None
        if loop is None or pipe_write is None:
            return
        try:
            loop.remove_watch_pipe(pipe_write)
        except (OSError, ValueError):
            logger.debug("Unable to remove Urwid pipe watch")
        try:
            os.close(pipe_write)
        except OSError:
            logger.debug("Unable to close Urwid pipe")


class PollingBackgroundNotifier(BackgroundNotifier):
    """Notify EDMApp through a repeating timer on Windows.

    Urwid's watch_pipe feature is unavailable on Windows. Instead, notify()
    records that background work is ready. A timer checks this flag every 0.2
    seconds and runs EDMApp's callback on the UI thread when work is waiting.
    """

    def __init__(self, poll_interval: float = 0.2) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.poll_interval = poll_interval
        self._loop: Optional[urwid.MainLoop] = None
        self._callback: Optional[BackgroundTaskReadyCallback] = None
        self._timer_handle: Optional[Any] = None
        self._notification_pending = False
        self._lock = Lock()

    def start(
        self,
        loop: urwid.MainLoop,
        callback: BackgroundTaskReadyCallback,
    ) -> None:
        """Start a repeating timer that checks for worker notifications."""
        with self._lock:
            self._loop = loop
            self._callback = callback
            self._notification_pending = False
        self._schedule_next_notification_check()

    def notify(self) -> None:
        """Mark worker results as ready for the next timer check."""
        with self._lock:
            if self._loop is not None:
                self._notification_pending = True

    def stop(self) -> None:
        """Stop the polling timer and clear the callback."""
        with self._lock:
            loop = self._loop
            timer_handle = self._timer_handle
            self._loop = None
            self._callback = None
            self._timer_handle = None
            self._notification_pending = False
        if loop is not None and timer_handle is not None:
            try:
                loop.remove_alarm(timer_handle)
            except ValueError:
                logger.debug("Unable to remove Urwid polling timer")

    # Urwid passes its event loop and optional user data to timer callbacks.
    # EDM does not need either value here, but this method must accept them to
    # match Urwid's callback signature. The underscores mark them as unused.
    def _check_for_task_notifications(
        self,
        _loop: urwid.MainLoop,
        _data: Any = None,
    ) -> None:
        """Run the EDMApp callback when a worker notification is pending."""
        callback: Optional[BackgroundTaskReadyCallback] = None
        with self._lock:
            self._timer_handle = None
            if self._loop is None:
                return
            if self._notification_pending and self._callback is not None:
                self._notification_pending = False
                callback = self._callback
        if callback is not None:
            callback(b"")
        self._schedule_next_notification_check()

    def _schedule_next_notification_check(self) -> None:
        """Schedule the next timer check while the notifier is running."""
        with self._lock:
            if self._loop is None:
                return
            self._timer_handle = self._loop.set_alarm_in(
                self.poll_interval,
                self._check_for_task_notifications,
            )


def create_background_notifier() -> BackgroundNotifier:
    """Create the notifier supported by the current operating system."""
    # os.name is "nt" on Windows, where Urwid's watch_pipe is unavailable.
    # A short polling timer provides a Windows-compatible alternative.
    if os.name == "nt":
        return PollingBackgroundNotifier()

    # Linux and macOS normally report "posix", where a pipe can wake the UI
    # immediately after background work finishes.
    return PipeBackgroundNotifier()


__all__ = [
    "BackgroundNotifier",
    "PipeBackgroundNotifier",
    "PollingBackgroundNotifier",
    "create_background_notifier",
]
