from __future__ import annotations

from unittest.mock import Mock

import pytest

from easy_docker_manager.app import background_notifier
from easy_docker_manager.app.background_notifier import (
    PipeBackgroundNotifier,
    PollingBackgroundNotifier,
)


class FakeUrwidLoop:
    def __init__(self) -> None:
        self.watch_pipe = Mock(return_value=42)
        self.remove_watch_pipe = Mock()
        self.set_alarm_in = Mock(side_effect=self._set_alarm)
        self.remove_alarm = Mock()
        self.last_timer_callback = None

    def _set_alarm(self, _delay, callback):
        self.last_timer_callback = callback
        return "timer-handle"


@pytest.fixture
def fake_urwid_loop() -> FakeUrwidLoop:
    return FakeUrwidLoop()


def test_pipe_notifier_registers_writes_and_removes_pipe(
    monkeypatch,
    fake_urwid_loop: FakeUrwidLoop,
) -> None:
    callback = Mock()
    write = Mock()
    close = Mock()
    monkeypatch.setattr(background_notifier.os, "write", write)
    monkeypatch.setattr(background_notifier.os, "close", close)
    notifier = PipeBackgroundNotifier()

    notifier.start(fake_urwid_loop, callback)
    notifier.notify()
    notifier.stop()

    fake_urwid_loop.watch_pipe.assert_called_once_with(callback)
    write.assert_called_once_with(42, b"x")
    fake_urwid_loop.remove_watch_pipe.assert_called_once_with(42)
    close.assert_called_once_with(42)


def test_pipe_notifier_requires_watch_pipe() -> None:
    loop_without_pipe_support = object()
    with pytest.raises(RuntimeError, match="watch_pipe"):
        PipeBackgroundNotifier().start(loop_without_pipe_support, Mock())


def test_pipe_notifier_ignores_notify_before_start() -> None:
    PipeBackgroundNotifier().notify()


def test_pipe_notifier_handles_write_and_cleanup_errors(
    monkeypatch,
    fake_urwid_loop: FakeUrwidLoop,
) -> None:
    fake_urwid_loop.remove_watch_pipe.side_effect = ValueError("gone")
    monkeypatch.setattr(
        background_notifier.os,
        "write",
        Mock(side_effect=OSError("closed")),
    )
    monkeypatch.setattr(
        background_notifier.os,
        "close",
        Mock(side_effect=OSError("closed")),
    )
    notifier = PipeBackgroundNotifier()
    notifier.start(fake_urwid_loop, Mock())

    notifier.notify()
    notifier.stop()


def test_polling_notifier_rejects_invalid_poll_interval() -> None:
    with pytest.raises(ValueError, match="poll_interval must be positive"):
        PollingBackgroundNotifier(poll_interval=0)


def test_polling_notifier_delivers_pending_notification_and_schedules_next_check(
    fake_urwid_loop: FakeUrwidLoop,
) -> None:
    callback = Mock()
    notifier = PollingBackgroundNotifier(poll_interval=0.5)
    notifier.start(fake_urwid_loop, callback)
    first_notification_check = fake_urwid_loop.last_timer_callback

    notifier.notify()
    first_notification_check(fake_urwid_loop)

    callback.assert_called_once_with(b"")
    assert fake_urwid_loop.set_alarm_in.call_count == 2
    fake_urwid_loop.set_alarm_in.assert_called_with(
        0.5,
        notifier._check_for_task_notifications,
    )


def test_polling_notifier_does_not_callback_without_pending_work(
    fake_urwid_loop: FakeUrwidLoop,
) -> None:
    callback = Mock()
    notifier = PollingBackgroundNotifier()
    notifier.start(fake_urwid_loop, callback)

    fake_urwid_loop.last_timer_callback(fake_urwid_loop)

    callback.assert_not_called()


def test_polling_notifier_stop_removes_scheduled_check(
    fake_urwid_loop: FakeUrwidLoop,
) -> None:
    notifier = PollingBackgroundNotifier()
    notifier.start(fake_urwid_loop, Mock())

    notifier.stop()
    notifier.notify()

    fake_urwid_loop.remove_alarm.assert_called_once_with("timer-handle")


def test_notifier_factory_uses_platform_appropriate_implementation(monkeypatch) -> None:
    monkeypatch.setattr(background_notifier.os, "name", "nt")
    assert isinstance(
        background_notifier.create_background_notifier(),
        PollingBackgroundNotifier,
    )

    monkeypatch.setattr(background_notifier.os, "name", "posix")
    assert isinstance(
        background_notifier.create_background_notifier(),
        PipeBackgroundNotifier,
    )
