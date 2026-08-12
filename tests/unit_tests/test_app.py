from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import urwid

from easy_docker_manager.app import app as app_module
from easy_docker_manager.app.app import EDMApp, _KeyboardRoutingWidget
from easy_docker_manager.app.background_notifier import BackgroundNotifier
from easy_docker_manager.app.background_task_result_handler import (
    BackgroundTaskResultHandler,
)
from easy_docker_manager.app.background_task_runner import BackgroundTaskRunner
from easy_docker_manager.app.runtime_factory import EDMRuntimeFactory
from easy_docker_manager.app.scheduler import BackgroundTaskScheduler
from easy_docker_manager.docker.base import ContainerDataSource
from easy_docker_manager.ui.keyboard_controller import KeyAction, KeyboardController
from easy_docker_manager.ui.terminal_layout import TerminalLayoutView
from easy_docker_manager.ui.ui_controller import UIController


@dataclass
class EDMAppTestSetup:
    app: EDMApp
    runtime: SimpleNamespace
    runtime_factory: Mock
    background_notifier: Mock


@pytest.fixture
def edm_app_setup() -> EDMAppTestSetup:
    terminal_layout_view = Mock(spec=TerminalLayoutView)
    terminal_layout_view.layout = urwid.Text("layout")
    terminal_layout_view.build_palette.return_value = [("test", "white", "black")]
    runtime = SimpleNamespace(
        container_data_source=Mock(spec=ContainerDataSource),
        task_runner=Mock(spec=BackgroundTaskRunner),
        terminal_layout_view=terminal_layout_view,
        scheduler=Mock(spec=BackgroundTaskScheduler),
        ui_controller=Mock(spec=UIController),
        keyboard_controller=Mock(spec=KeyboardController),
        background_task_result_handler=Mock(spec=BackgroundTaskResultHandler),
    )
    runtime_factory = Mock(spec=EDMRuntimeFactory)
    runtime_factory.create_runtime.return_value = runtime
    background_notifier = Mock(spec=BackgroundNotifier)
    app = EDMApp(
        runtime_factory=runtime_factory,
        background_notifier=background_notifier,
    )
    return EDMAppTestSetup(
        app=app,
        runtime=runtime,
        runtime_factory=runtime_factory,
        background_notifier=background_notifier,
    )


def test_app_connects_runtime_with_worker_notification_callback(edm_app_setup) -> None:
    notify_background_work_ready = (
        edm_app_setup.runtime_factory.create_runtime.call_args.args[0]
    )
    notify_background_work_ready()

    assert edm_app_setup.app.layout is edm_app_setup.runtime.terminal_layout_view.layout
    edm_app_setup.background_notifier.notify.assert_called_once_with()


def test_root_widget_forwards_keypress_to_app(edm_app_setup) -> None:
    edm_app_setup.app.handle_keyboard_input = Mock(return_value="unhandled")
    root = _KeyboardRoutingWidget(edm_app_setup.app)

    assert root.keypress((80, 24), "x") == "unhandled"
    edm_app_setup.app.handle_keyboard_input.assert_called_once_with("x", (80, 24))


def test_keyboard_render_action_redraws_and_checks_background_work(
    edm_app_setup,
) -> None:
    edm_app_setup.runtime.keyboard_controller.handle_keypress.return_value = (
        KeyAction.RENDER
    )
    edm_app_setup.app._schedule_next_background_check = Mock()

    assert edm_app_setup.app.handle_keyboard_input("down", (80, 24)) is None

    edm_app_setup.runtime.ui_controller.render_current_state.assert_called_once_with()
    edm_app_setup.runtime.scheduler.schedule_next_tasks.assert_called_once_with()
    edm_app_setup.app._schedule_next_background_check.assert_called_once_with()


def test_keyboard_no_action_does_not_redraw(edm_app_setup) -> None:
    edm_app_setup.runtime.keyboard_controller.handle_keypress.return_value = (
        KeyAction.NONE
    )

    edm_app_setup.app.handle_keyboard_input("unknown")

    edm_app_setup.runtime.ui_controller.render_current_state.assert_not_called()


def test_keyboard_quit_action_exits_main_loop(edm_app_setup) -> None:
    edm_app_setup.runtime.keyboard_controller.handle_keypress.return_value = (
        KeyAction.QUIT
    )

    with pytest.raises(urwid.ExitMainLoop):
        edm_app_setup.app.handle_keyboard_input("q")


def test_background_check_starts_due_work_and_schedules_the_next_check(
    edm_app_setup,
) -> None:
    edm_app_setup.app._background_check_timer_handle = "old"
    edm_app_setup.app._schedule_next_background_check = Mock()

    edm_app_setup.app._schedule_next_background_tasks(Mock())

    assert edm_app_setup.app._background_check_timer_handle is None
    edm_app_setup.runtime.scheduler.schedule_next_tasks.assert_called_once_with()
    edm_app_setup.app._schedule_next_background_check.assert_called_once_with()


def test_completed_tasks_are_handled_and_visible_changes_redraw(
    edm_app_setup,
) -> None:
    first_completed_task = object()
    second_completed_task = object()
    edm_app_setup.runtime.task_runner.pop_all_completed_tasks.return_value = [
        first_completed_task,
        second_completed_task,
    ]
    result_handler = edm_app_setup.runtime.background_task_result_handler
    result_handler.handle_completed_task.side_effect = [False, True]
    edm_app_setup.app._schedule_next_background_check = Mock()

    edm_app_setup.app._process_completed_background_tasks(b"x")

    assert result_handler.handle_completed_task.call_count == 2
    edm_app_setup.runtime.scheduler.schedule_next_tasks.assert_called_once_with()
    edm_app_setup.runtime.ui_controller.render_current_state.assert_called_once_with()


def test_completed_tasks_do_not_redraw_when_nothing_visible_changed(
    edm_app_setup,
) -> None:
    edm_app_setup.runtime.task_runner.pop_all_completed_tasks.return_value = [object()]
    result_handler = edm_app_setup.runtime.background_task_result_handler
    result_handler.handle_completed_task.return_value = False
    edm_app_setup.app._schedule_next_background_check = Mock()

    edm_app_setup.app._process_completed_background_tasks(b"")

    edm_app_setup.runtime.ui_controller.render_current_state.assert_not_called()


class FakeUrwidMainLoop:
    def __init__(self, *_args, **_kwargs) -> None:
        self.remove_alarm = Mock()
        self.set_alarm_in = Mock(return_value="timer")
        self.run = Mock()


@pytest.fixture
def fake_urwid_main_loop() -> FakeUrwidMainLoop:
    return FakeUrwidMainLoop()


def test_schedule_next_check_replaces_the_existing_scheduled_check(
    edm_app_setup,
    fake_urwid_main_loop: FakeUrwidMainLoop,
) -> None:
    edm_app_setup.app.ui_event_loop = fake_urwid_main_loop
    edm_app_setup.app._background_check_timer_handle = "old"
    scheduler = edm_app_setup.runtime.scheduler
    scheduler.seconds_until_next_task_check.return_value = 0.75

    edm_app_setup.app._schedule_next_background_check()

    fake_urwid_main_loop.remove_alarm.assert_called_once_with("old")
    fake_urwid_main_loop.set_alarm_in.assert_called_once_with(
        0.75,
        edm_app_setup.app._schedule_next_background_tasks,
    )
    assert edm_app_setup.app._background_check_timer_handle == "timer"


def test_schedule_next_check_uses_explicit_delay_after_ui_loop_starts(
    edm_app_setup,
    fake_urwid_main_loop: FakeUrwidMainLoop,
) -> None:
    edm_app_setup.app._schedule_next_background_check(delay=0)
    scheduler = edm_app_setup.runtime.scheduler
    scheduler.seconds_until_next_task_check.assert_not_called()

    edm_app_setup.app.ui_event_loop = fake_urwid_main_loop
    edm_app_setup.app._schedule_next_background_check(delay=0)
    fake_urwid_main_loop.set_alarm_in.assert_called_once_with(
        0,
        edm_app_setup.app._schedule_next_background_tasks,
    )


def test_run_starts_ui_and_closes_resources(
    edm_app_setup,
    monkeypatch,
    fake_urwid_main_loop: FakeUrwidMainLoop,
) -> None:
    monkeypatch.setattr(
        app_module.urwid,
        "MainLoop",
        Mock(return_value=fake_urwid_main_loop),
    )

    edm_app_setup.app.run()

    edm_app_setup.background_notifier.start.assert_called_once_with(
        fake_urwid_main_loop,
        edm_app_setup.app._process_completed_background_tasks,
    )
    runtime = edm_app_setup.runtime
    runtime.scheduler.schedule_container_refresh.assert_called_once_with(force=True)
    runtime.ui_controller.render_current_state.assert_called_once_with()
    fake_urwid_main_loop.set_alarm_in.assert_called_once_with(
        0,
        edm_app_setup.app._schedule_next_background_tasks,
    )
    fake_urwid_main_loop.run.assert_called_once_with()
    edm_app_setup.background_notifier.stop.assert_called_once_with()
    runtime.task_runner.shutdown.assert_called_once_with(wait=True)
    runtime.container_data_source.close.assert_called_once_with()


def test_run_still_cleans_up_when_main_loop_fails(
    edm_app_setup,
    monkeypatch,
    fake_urwid_main_loop: FakeUrwidMainLoop,
) -> None:
    fake_urwid_main_loop.run.side_effect = RuntimeError("screen failed")
    monkeypatch.setattr(
        app_module.urwid,
        "MainLoop",
        Mock(return_value=fake_urwid_main_loop),
    )

    with pytest.raises(RuntimeError, match="screen failed"):
        edm_app_setup.app.run()

    runtime = edm_app_setup.runtime
    edm_app_setup.background_notifier.stop.assert_called_once_with()
    runtime.task_runner.shutdown.assert_called_once_with(wait=True)
    runtime.container_data_source.close.assert_called_once_with()
