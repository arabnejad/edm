from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import urwid

from easy_docker_manager.app import app as app_module
from easy_docker_manager.app.app import EDMApp, _KeyboardRoutingWidget
from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.app.background_notifier import BackgroundNotifier
from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.app.runtime_factory import EDMRuntimeFactory
from easy_docker_manager.core.docker_connections import (
    DockerConnectionTransport,
    DockerContextDetails,
)
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import DockerContainerClient
from easy_docker_manager.docker.container_shell_launcher import ContainerShellLauncher
from easy_docker_manager.ui.keyboard_controller import (
    KeyboardController,
    KeypressResult,
)
from easy_docker_manager.ui.terminal_controller import TerminalController
from easy_docker_manager.ui.terminal_layout import TerminalLayoutView


@dataclass
class EDMAppTestSetup:
    app: EDMApp
    runtime: SimpleNamespace
    runtime_factory: Mock
    background_notifier: Mock
    container_shell_launcher: Mock
    container_terminal_factory: Mock


@pytest.fixture
def edm_app_setup() -> EDMAppTestSetup:
    terminal_layout_view = Mock(spec=TerminalLayoutView)
    terminal_layout_view.layout = urwid.Text("layout")
    terminal_layout_view.build_urwid_style_palette.return_value = [
        ("test", "white", "black")
    ]
    terminal_controller = Mock(spec=TerminalController)
    terminal_controller.state = TerminalSessionState()
    runtime = SimpleNamespace(
        docker_container_client=Mock(spec=DockerContainerClient),
        background_executor=Mock(spec=BackgroundExecutor),
        terminal_layout_view=terminal_layout_view,
        docker_manager=Mock(spec=DockerManager),
        terminal_controller=terminal_controller,
        keyboard_controller=Mock(spec=KeyboardController),
    )
    runtime_factory = Mock(spec=EDMRuntimeFactory)
    runtime_factory.create_runtime.return_value = runtime
    background_notifier = Mock(spec=BackgroundNotifier)
    container_shell_launcher = Mock(spec=ContainerShellLauncher)
    container_terminal_factory = Mock()
    app = EDMApp(
        runtime_factory=runtime_factory,
        background_notifier=background_notifier,
        container_shell_launcher=container_shell_launcher,
        container_terminal_factory=container_terminal_factory,
    )
    return EDMAppTestSetup(
        app=app,
        runtime=runtime,
        runtime_factory=runtime_factory,
        background_notifier=background_notifier,
        container_shell_launcher=container_shell_launcher,
        container_terminal_factory=container_terminal_factory,
    )


def test_app_connects_runtime_with_worker_notification_callback(edm_app_setup) -> None:
    notify_background_work_ready = (
        edm_app_setup.runtime_factory.create_runtime.call_args.args[0]
    )
    notify_background_work_ready()
    request_container_shell = (
        edm_app_setup.runtime_factory.create_runtime.call_args.args[1]
    )

    assert edm_app_setup.app.layout is edm_app_setup.runtime.terminal_layout_view.layout
    assert (
        request_container_shell
        == edm_app_setup.app._request_interactive_container_shell
    )
    edm_app_setup.background_notifier.notify.assert_called_once_with()


def test_root_widget_forwards_keypress_to_app(edm_app_setup) -> None:
    edm_app_setup.app.handle_keyboard_input = Mock(return_value="unhandled")
    root = _KeyboardRoutingWidget(edm_app_setup.app)

    assert root.selectable()
    assert root.keypress((80, 24), "x") == "unhandled"
    edm_app_setup.app.handle_keyboard_input.assert_called_once_with("x", (80, 24))


def test_keyboard_render_action_redraws_and_checks_background_work(
    edm_app_setup,
) -> None:
    edm_app_setup.runtime.keyboard_controller.handle_keypress.return_value = (
        KeypressResult.REDRAW
    )
    edm_app_setup.app._schedule_next_docker_data_refresh_check = Mock()

    assert edm_app_setup.app.handle_keyboard_input("down", (80, 24)) is None

    edm_app_setup.runtime.terminal_controller.update_terminal_view.assert_called_once_with()
    docker_manager = edm_app_setup.runtime.docker_manager
    docker_manager.refresh_docker_data_if_needed.assert_called_once_with()
    edm_app_setup.app._schedule_next_docker_data_refresh_check.assert_called_once_with()


def test_keyboard_no_action_does_not_redraw(edm_app_setup) -> None:
    edm_app_setup.runtime.keyboard_controller.handle_keypress.return_value = (
        KeypressResult.NONE
    )

    edm_app_setup.app.handle_keyboard_input("unknown")

    edm_app_setup.runtime.terminal_controller.update_terminal_view.assert_not_called()


def test_shell_workspace_forwards_keys_to_its_terminal_layout(edm_app_setup) -> None:
    edm_app_setup.app._active_shell_terminal = Mock(spec=urwid.Terminal)

    assert edm_app_setup.app.handle_keyboard_input("echo hello", (80, 24)) == (
        "echo hello"
    )
    assert edm_app_setup.app.handle_keyboard_input("ctrl d", (80, 24)) == "ctrl d"
    assert edm_app_setup.app.handle_keyboard_input("x") == "x"

    edm_app_setup.runtime.keyboard_controller.handle_keypress.assert_not_called()


def test_keyboard_quit_action_exits_main_loop(edm_app_setup) -> None:
    edm_app_setup.runtime.keyboard_controller.handle_keypress.return_value = (
        KeypressResult.QUIT
    )

    with pytest.raises(urwid.ExitMainLoop):
        edm_app_setup.app.handle_keyboard_input("q")


def test_background_check_starts_scheduled_work_and_schedules_the_next_check(
    edm_app_setup,
) -> None:
    edm_app_setup.app._pending_docker_data_refresh_timer = "old"
    edm_app_setup.app._schedule_next_docker_data_refresh_check = Mock()

    edm_app_setup.app._run_scheduled_docker_data_refresh_check(Mock())

    assert edm_app_setup.app._pending_docker_data_refresh_timer is None
    docker_manager = edm_app_setup.runtime.docker_manager
    docker_manager.refresh_docker_data_if_needed.assert_called_once_with()
    edm_app_setup.app._schedule_next_docker_data_refresh_check.assert_called_once_with()


def test_completion_callbacks_run_and_visible_changes_redraw(
    edm_app_setup,
) -> None:
    first_completion = Mock(return_value=False)
    second_completion = Mock(return_value=True)
    executor = edm_app_setup.runtime.background_executor
    executor.get_and_remove_all_ui_completion_callbacks.return_value = [
        first_completion,
        second_completion,
    ]
    edm_app_setup.app._schedule_next_docker_data_refresh_check = Mock()

    edm_app_setup.app._process_completed_background_tasks(b"x")

    first_completion.assert_called_once_with()
    second_completion.assert_called_once_with()
    docker_manager = edm_app_setup.runtime.docker_manager
    docker_manager.refresh_docker_data_if_needed.assert_called_once_with()
    edm_app_setup.runtime.terminal_controller.update_terminal_view.assert_called_once_with()


def test_completion_callbacks_do_not_redraw_when_nothing_visible_changed(
    edm_app_setup,
) -> None:
    completion = Mock(return_value=False)
    executor = edm_app_setup.runtime.background_executor
    executor.get_and_remove_all_ui_completion_callbacks.return_value = [completion]
    edm_app_setup.app._schedule_next_docker_data_refresh_check = Mock()

    edm_app_setup.app._process_completed_background_tasks(b"")

    edm_app_setup.runtime.terminal_controller.update_terminal_view.assert_not_called()


class FakeUrwidMainLoop:
    def __init__(self, *_args, **_kwargs) -> None:
        self.remove_alarm = Mock()
        self.set_alarm_in = Mock(return_value="timer")
        self.run = Mock()
        self.screen = Mock()


@pytest.fixture
def fake_urwid_main_loop() -> FakeUrwidMainLoop:
    return FakeUrwidMainLoop()


def test_schedule_next_check_replaces_the_existing_scheduled_check(
    edm_app_setup,
    fake_urwid_main_loop: FakeUrwidMainLoop,
) -> None:
    edm_app_setup.app.urwid_main_loop = fake_urwid_main_loop
    edm_app_setup.app._pending_docker_data_refresh_timer = "old"
    docker_manager = edm_app_setup.runtime.docker_manager
    docker_manager.get_next_docker_data_refresh_delay.return_value = 0.75

    edm_app_setup.app._schedule_next_docker_data_refresh_check()

    fake_urwid_main_loop.remove_alarm.assert_called_once_with("old")
    fake_urwid_main_loop.set_alarm_in.assert_called_once_with(
        0.75,
        edm_app_setup.app._run_scheduled_docker_data_refresh_check,
    )
    assert edm_app_setup.app._pending_docker_data_refresh_timer == "timer"


def test_schedule_next_check_uses_explicit_delay_after_ui_loop_starts(
    edm_app_setup,
    fake_urwid_main_loop: FakeUrwidMainLoop,
) -> None:
    edm_app_setup.app._schedule_next_docker_data_refresh_check(delay=0)
    docker_manager = edm_app_setup.runtime.docker_manager
    docker_manager.get_next_docker_data_refresh_delay.assert_not_called()

    edm_app_setup.app.urwid_main_loop = fake_urwid_main_loop
    edm_app_setup.app._schedule_next_docker_data_refresh_check(delay=0)
    fake_urwid_main_loop.set_alarm_in.assert_called_once_with(
        0,
        edm_app_setup.app._run_scheduled_docker_data_refresh_check,
    )


def test_open_shell_checks_for_a_supported_shell_in_a_worker(
    edm_app_setup,
    fake_urwid_main_loop: FakeUrwidMainLoop,
    container_summary_factory,
) -> None:
    edm_app_setup.app.urwid_main_loop = fake_urwid_main_loop
    shell_detection_future: Future[str] = Future()
    edm_app_setup.runtime.background_executor.submit.return_value = (
        shell_detection_future
    )
    container = container_summary_factory()

    error_message = edm_app_setup.app._request_interactive_container_shell(
        container,
    )

    assert error_message is None
    edm_app_setup.runtime.background_executor.submit.assert_called_once()
    submit_call = edm_app_setup.runtime.background_executor.submit.call_args
    assert submit_call.args == (
        edm_app_setup.container_shell_launcher.find_available_shell_executable,
        "container-1",
        edm_app_setup.runtime.terminal_controller.state.active_docker_context,
    )
    assert edm_app_setup.runtime.terminal_controller.state.status_message == (
        'Looking for a shell in container "web"...'
    )


def test_open_shell_rejects_requests_when_it_cannot_start_another_check(
    edm_app_setup,
    fake_urwid_main_loop: FakeUrwidMainLoop,
    container_summary_factory,
) -> None:
    container = container_summary_factory()

    assert edm_app_setup.app._request_interactive_container_shell(container) == (
        "Could not open the container shell before EDM started."
    )

    edm_app_setup.app.urwid_main_loop = fake_urwid_main_loop
    edm_app_setup.app._shell_detection_future = Future()
    assert edm_app_setup.app._request_interactive_container_shell(container) == (
        "EDM is already looking for a container shell."
    )

    edm_app_setup.app._shell_detection_future = None
    edm_app_setup.app._active_shell_terminal = Mock(spec=urwid.Terminal)
    assert edm_app_setup.app._request_interactive_container_shell(container) == (
        "Close the current container shell before opening another one."
    )


def test_detected_shell_opens_a_terminal_workspace(
    edm_app_setup,
    monkeypatch,
    fake_urwid_main_loop: FakeUrwidMainLoop,
    container_summary_factory,
) -> None:
    edm_app_setup.app.urwid_main_loop = fake_urwid_main_loop
    shell_detection_future: Future[str] = Future()
    edm_app_setup.runtime.background_executor.submit.return_value = (
        shell_detection_future
    )
    build_shell_command = (
        edm_app_setup.container_shell_launcher.build_interactive_shell_command
    )
    build_shell_command.return_value = [
        "docker",
        "exec",
        "container-1",
        "/bin/bash",
    ]
    terminal = Mock(spec=urwid.Terminal)
    edm_app_setup.container_terminal_factory.return_value = terminal
    connect_signal = Mock()
    monkeypatch.setattr(app_module.urwid, "connect_signal", connect_signal)
    container = container_summary_factory()
    edm_app_setup.app._request_interactive_container_shell(container)
    completion_callback = (
        edm_app_setup.runtime.background_executor.submit.call_args.kwargs["on_complete"]
    )
    shell_detection_future.set_result("/bin/bash")

    assert completion_callback(shell_detection_future)

    edm_app_setup.container_terminal_factory.assert_called_once_with(
        ["docker", "exec", "container-1", "/bin/bash"],
        main_loop=fake_urwid_main_loop,
        escape_sequence="__edm_shell_escape_disabled__",
    )
    assert terminal.keygrab
    connect_signal.assert_called_once_with(
        terminal,
        "closed",
        edm_app_setup.app._handle_container_shell_closed,
    )
    edm_app_setup.runtime.terminal_layout_view.show_container_shell.assert_called_once_with(
        terminal,
        "web",
        "/bin/bash",
    )


def test_shell_detection_error_is_shown_in_the_container_view(
    edm_app_setup,
    fake_urwid_main_loop: FakeUrwidMainLoop,
    container_summary_factory,
) -> None:
    edm_app_setup.app.urwid_main_loop = fake_urwid_main_loop
    shell_detection_future: Future[str] = Future()
    edm_app_setup.runtime.background_executor.submit.return_value = (
        shell_detection_future
    )
    edm_app_setup.app._request_interactive_container_shell(container_summary_factory())
    completion_callback = (
        edm_app_setup.runtime.background_executor.submit.call_args.kwargs["on_complete"]
    )
    shell_detection_future.set_exception(RuntimeError("no supported shell"))

    assert completion_callback(shell_detection_future)

    assert edm_app_setup.runtime.terminal_controller.state.status_message == (
        'Could not open shell for container "web": no supported shell'
    )


def test_stale_shell_detection_result_is_ignored(
    edm_app_setup,
    container_summary_factory,
) -> None:
    stale_future: Future[str] = Future()
    stale_future.set_result("/bin/sh")
    edm_app_setup.app._shell_detection_future = Future()
    docker_context = (
        edm_app_setup.runtime.terminal_controller.state.active_docker_context
    )

    assert not edm_app_setup.app._handle_detected_container_shell(
        container_summary_factory(),
        docker_context,
        stale_future,
    )
    edm_app_setup.container_terminal_factory.assert_not_called()


def test_shell_does_not_open_after_the_docker_context_changes(
    edm_app_setup,
    container_summary_factory,
) -> None:
    previous_context = (
        edm_app_setup.runtime.terminal_controller.state.active_docker_context
    )
    edm_app_setup.runtime.terminal_controller.state.active_docker_context = (
        DockerContextDetails(
            "remote",
            "ssh://docker@example.com",
            DockerConnectionTransport.SSH,
        )
    )
    shell_detection_future: Future[str] = Future()
    shell_detection_future.set_result("/bin/sh")
    edm_app_setup.app._shell_detection_future = shell_detection_future

    assert edm_app_setup.app._handle_detected_container_shell(
        container_summary_factory(),
        previous_context,
        shell_detection_future,
    )
    assert edm_app_setup.runtime.terminal_controller.state.status_message == (
        "The Docker connection changed before the shell could open."
    )


def test_terminal_workspace_creation_error_is_shown(
    edm_app_setup,
    fake_urwid_main_loop: FakeUrwidMainLoop,
    container_summary_factory,
) -> None:
    edm_app_setup.app.urwid_main_loop = fake_urwid_main_loop
    shell_detection_future: Future[str] = Future()
    shell_detection_future.set_result("/bin/bash")
    edm_app_setup.app._shell_detection_future = shell_detection_future
    build_shell_command = (
        edm_app_setup.container_shell_launcher.build_interactive_shell_command
    )
    build_shell_command.side_effect = RuntimeError("cannot build command")
    docker_context = (
        edm_app_setup.runtime.terminal_controller.state.active_docker_context
    )

    assert edm_app_setup.app._handle_detected_container_shell(
        container_summary_factory(),
        docker_context,
        shell_detection_future,
    )
    assert edm_app_setup.runtime.terminal_controller.state.status_message == (
        'Could not open shell for container "web": cannot build command'
    )


def test_windows_shell_temporarily_releases_the_current_terminal(
    edm_app_setup,
    monkeypatch,
    fake_urwid_main_loop: FakeUrwidMainLoop,
    container_summary_factory,
) -> None:
    edm_app_setup.app.urwid_main_loop = fake_urwid_main_loop
    monkeypatch.setattr(app_module.os, "name", "nt")
    shell_detection_future: Future[str] = Future()
    shell_detection_future.set_result("/bin/sh")
    edm_app_setup.app._shell_detection_future = shell_detection_future
    edm_app_setup.container_shell_launcher.open_shell.return_value = 0
    docker_context = (
        edm_app_setup.runtime.terminal_controller.state.active_docker_context
    )

    assert edm_app_setup.app._handle_detected_container_shell(
        container_summary_factory(),
        docker_context,
        shell_detection_future,
    )

    fake_urwid_main_loop.screen.stop.assert_called_once_with()
    fake_urwid_main_loop.screen.start.assert_called_once_with()
    fake_urwid_main_loop.screen.clear.assert_called_once_with()
    assert edm_app_setup.runtime.terminal_controller.state.status_message == (
        'Shell for container "web" closed.'
    )


def test_natural_shell_exit_returns_to_the_container_view(
    edm_app_setup,
    container_summary_factory,
) -> None:
    terminal = Mock(spec=urwid.Terminal)
    edm_app_setup.app._active_shell_terminal = terminal
    edm_app_setup.app._active_shell_container = container_summary_factory()

    edm_app_setup.app._handle_container_shell_closed(terminal)

    terminal.terminate.assert_not_called()
    edm_app_setup.runtime.terminal_layout_view.show_main_workspace.assert_called_once_with()


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
    runtime.docker_manager.start_container_list_refresh.assert_called_once_with(
        force=True
    )
    runtime.terminal_controller.update_terminal_view.assert_called_once_with()
    fake_urwid_main_loop.set_alarm_in.assert_called_once_with(
        0,
        edm_app_setup.app._run_scheduled_docker_data_refresh_check,
    )
    fake_urwid_main_loop.run.assert_called_once_with()
    edm_app_setup.background_notifier.stop.assert_called_once_with()
    runtime.background_executor.shutdown.assert_called_once_with(wait=True)
    runtime.docker_container_client.close.assert_called_once_with()


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
    runtime.background_executor.shutdown.assert_called_once_with(wait=True)
    runtime.docker_container_client.close.assert_called_once_with()
