from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from easy_docker_manager.app import scheduler as scheduler_module
from easy_docker_manager.app.background_task_runner import CompletedTask, TaskKind
from easy_docker_manager.app.scheduler import BackgroundTaskScheduler
from easy_docker_manager.core import AppConfig
from easy_docker_manager.core.content_cache import ContainerTabKey
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.ui_session_state import UISessionState


class RecordingTaskRunner:
    def __init__(self) -> None:
        self.calls = []
        self.futures = []

    def submit(self, task_kind, fn, *args, task_context=None):
        future = Future()
        self.calls.append((task_kind, fn, args, task_context))
        self.futures.append(future)
        return future


@dataclass
class SchedulerTestSetup:
    scheduler: BackgroundTaskScheduler
    task_runner: RecordingTaskRunner
    tab_data_loader: Mock
    container_data_source: Mock


@pytest.fixture
def scheduler_factory():
    def create_scheduler(state=None, config=None):
        selected_state = state if state is not None else UISessionState()
        selected_config = config if config is not None else AppConfig()
        task_runner = RecordingTaskRunner()
        tab_data_loader = Mock()
        container_data_source = Mock()
        scheduler = BackgroundTaskScheduler(
            selected_state,
            selected_config,
            task_runner,
            tab_data_loader,
            container_data_source,
        )
        return SchedulerTestSetup(
            scheduler=scheduler,
            task_runner=task_runner,
            tab_data_loader=tab_data_loader,
            container_data_source=container_data_source,
        )

    return create_scheduler


def test_schedule_next_tasks_starts_a_due_container_refresh(
    monkeypatch,
    scheduler_factory,
) -> None:
    state = UISessionState(active_detail_tab_name=TabName.ENV)
    test_setup = scheduler_factory(state)
    scheduler = test_setup.scheduler
    task_runner = test_setup.task_runner
    container_data_source = test_setup.container_data_source
    monkeypatch.setattr(scheduler_module.time, "monotonic", lambda: 10.0)

    scheduler.schedule_next_tasks()

    assert task_runner.calls[0][0] == TaskKind.REFRESH
    assert task_runner.calls[0][1] == container_data_source.list_running_containers
    assert scheduler._next_container_refresh_at == 12.0


def test_schedule_next_tasks_polls_only_a_loaded_readable_logs_tab(
    monkeypatch,
    scheduler_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "initial"
    test_setup = scheduler_factory(state)
    scheduler = test_setup.scheduler
    task_runner = test_setup.task_runner
    scheduler._next_container_refresh_at = 100.0
    monkeypatch.setattr(scheduler_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(scheduler_module.time, "time", lambda: 50.0)

    scheduler.schedule_next_tasks()

    assert task_runner.calls[0][0] == TaskKind.FETCH_LOG_UPDATES
    assert scheduler._next_log_poll_at == 11.0


def test_schedule_next_tasks_reloads_the_visible_non_log_tab(
    monkeypatch,
    scheduler_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "OLD=value"
    test_setup = scheduler_factory(
        state,
        AppConfig(tab_refresh_interval=3.0),
    )
    scheduler = test_setup.scheduler
    task_runner = test_setup.task_runner
    tab_data_loader = test_setup.tab_data_loader
    scheduler._next_container_refresh_at = 100.0
    monkeypatch.setattr(scheduler_module.time, "monotonic", lambda: 10.0)

    scheduler.schedule_next_tasks()

    task_kind, function, args, task_context = task_runner.calls[0]
    assert task_kind == TaskKind.FETCH_TAB_CONTENT
    assert function == tab_data_loader.load_tab_text
    assert args == ("container-1", TabName.ENV)
    assert task_context.container_tab_key == container_tab_key
    assert scheduler._next_visible_tab_refresh_at == 13.0


def test_next_task_check_includes_the_visible_tab_reload(
    monkeypatch,
    scheduler_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.TOP)
    scheduler = scheduler_factory(state).scheduler
    scheduler._next_container_refresh_at = 100.0
    scheduler._next_visible_tab_refresh_at = 8.5
    monkeypatch.setattr(scheduler_module.time, "monotonic", lambda: 5.0)

    assert scheduler.seconds_until_next_task_check() == 3.5


def test_next_task_check_includes_the_log_poll(
    monkeypatch,
    scheduler_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "initial"
    scheduler = scheduler_factory(state).scheduler
    scheduler._next_container_refresh_at = 100.0
    scheduler._next_log_poll_at = 8.5
    monkeypatch.setattr(scheduler_module.time, "monotonic", lambda: 5.0)

    # The log poll is due at 8.5 and the current time is 5.0, leaving 3.5 seconds.
    assert scheduler.seconds_until_next_task_check() == 3.5


def test_schedule_next_tasks_skips_unreadable_logs(
    monkeypatch,
    scheduler_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    state.unreadable_log_container_ids.add("container-1")
    test_setup = scheduler_factory(state)
    scheduler = test_setup.scheduler
    task_runner = test_setup.task_runner
    scheduler._next_container_refresh_at = 100.0
    monkeypatch.setattr(scheduler_module.time, "monotonic", lambda: 10.0)

    scheduler.schedule_next_tasks()

    assert task_runner.calls == []


def test_seconds_until_next_work_uses_minimum_and_idle_delays(
    monkeypatch,
    scheduler_factory,
) -> None:
    scheduler = scheduler_factory().scheduler
    monkeypatch.setattr(scheduler_module.time, "monotonic", lambda: 5.0)
    scheduler._next_container_refresh_at = 4.0
    assert scheduler.seconds_until_next_task_check() == 0.05

    scheduler._container_refresh_future = Future()
    assert scheduler.seconds_until_next_task_check() == 1.0


def test_container_refresh_honors_deadline_and_prevents_duplicates(
    monkeypatch,
    scheduler_factory,
) -> None:
    test_setup = scheduler_factory()
    scheduler = test_setup.scheduler
    task_runner = test_setup.task_runner
    scheduler._next_container_refresh_at = 20.0
    monkeypatch.setattr(scheduler_module.time, "monotonic", lambda: 10.0)

    scheduler.schedule_container_refresh()
    assert task_runner.calls == []

    scheduler.schedule_container_refresh(force=True)
    scheduler.schedule_container_refresh(force=True)
    assert len(task_runner.calls) == 1


def test_tab_load_requires_selection_and_reuses_cache(
    scheduler_factory,
    session_state_factory,
) -> None:
    test_setup = scheduler_factory()
    scheduler = test_setup.scheduler
    task_runner = test_setup.task_runner
    assert not scheduler.schedule_selected_tab_load()

    state = session_state_factory(tab=TabName.ENV)
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "A=1"
    test_setup = scheduler_factory(state)
    scheduler = test_setup.scheduler
    task_runner = test_setup.task_runner
    assert not scheduler.schedule_selected_tab_load()
    assert task_runner.calls == []


def test_selected_tab_load_submits_its_cache_key_and_log_start_time(
    monkeypatch,
    scheduler_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_load_errors[container_tab_key] = "old"
    test_setup = scheduler_factory(state)
    scheduler = test_setup.scheduler
    task_runner = test_setup.task_runner
    tab_data_loader = test_setup.tab_data_loader
    monkeypatch.setattr(scheduler_module.time, "time", lambda: 123.9)

    assert scheduler.schedule_selected_tab_load()

    task_kind, function, args, task_context = task_runner.calls[0]
    assert task_kind == TaskKind.FETCH_TAB_CONTENT
    assert function == tab_data_loader.load_tab_text
    assert args == ("container-1", TabName.LOGS)
    assert task_context.container_tab_key == container_tab_key
    assert task_context.initial_log_request_started_at == 123
    assert container_tab_key not in state.tab_load_errors
    assert state.status_message == "Loading Logs..."


def test_tab_load_waits_for_uncancellable_running_request(
    scheduler_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    test_setup = scheduler_factory(state)
    scheduler = test_setup.scheduler
    task_runner = test_setup.task_runner
    running_tab_load = Future()
    running_tab_load.set_running_or_notify_cancel()
    scheduler._tab_load_future = running_tab_load

    assert scheduler.schedule_selected_tab_load()
    assert task_runner.calls == []


def test_tab_load_replaces_a_queued_request_that_can_be_cancelled(
    scheduler_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    test_setup = scheduler_factory(state)
    scheduler = test_setup.scheduler
    task_runner = test_setup.task_runner
    queued_tab_load = Future()
    scheduler._tab_load_future = queued_tab_load

    assert scheduler.schedule_selected_tab_load()

    assert queued_tab_load.cancelled()
    assert len(task_runner.calls) == 1


def test_log_poll_uses_initial_tail_then_saved_log_cursor(
    monkeypatch,
    scheduler_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = scheduler_factory(
        state,
        AppConfig(log_tail=25),
    )
    scheduler = test_setup.scheduler
    task_runner = test_setup.task_runner
    container_data_source = test_setup.container_data_source
    monkeypatch.setattr(scheduler_module.time, "time", lambda: 200.0)

    scheduler.schedule_log_poll()
    task_kind, function, args, task_context = task_runner.calls[-1]
    assert task_kind == TaskKind.FETCH_LOG_UPDATES
    assert args == ("container-1", 25, None)
    assert task_context.replace_existing
    assert task_context.request_started_at == 200

    scheduler.record_log_poll_success("container-1", 150)
    scheduler._log_poll_future = None
    scheduler.schedule_log_poll()
    _, _, args, task_context = task_runner.calls[-1]
    assert args == ("container-1", "all", 150)
    assert not task_context.replace_existing
    container_data_source.get_logs.return_value = "text"
    assert function("container-1", 25, None) == "text"


@pytest.mark.parametrize(
    ("task_kind", "future_attribute"),
    [
        (TaskKind.REFRESH, "_container_refresh_future"),
        (TaskKind.FETCH_TAB_CONTENT, "_tab_load_future"),
        (TaskKind.FETCH_LOG_UPDATES, "_log_poll_future"),
    ],
)
def test_claim_completed_task_accepts_only_the_tracked_future(
    task_kind: TaskKind,
    future_attribute: str,
    scheduler_factory,
) -> None:
    scheduler = scheduler_factory().scheduler
    tracked_future = Future()
    setattr(scheduler, future_attribute, tracked_future)

    assert scheduler.claim_completed_task(CompletedTask(task_kind, tracked_future))
    assert getattr(scheduler, future_attribute) is None
    assert not scheduler.claim_completed_task(CompletedTask(task_kind, Future()))


def test_log_tracking_can_be_reset_and_stopped_containers_removed(
    scheduler_factory,
) -> None:
    scheduler = scheduler_factory().scheduler
    scheduler.record_initial_log_load_success("one", 10)
    scheduler.record_log_poll_success("two", 20)
    assert scheduler._next_log_poll_at == 0.0

    pending_log_poll = Future()
    scheduler._log_poll_future = pending_log_poll
    scheduler._next_log_poll_at = 20.0
    scheduler.reset_log_poll_schedule()
    assert pending_log_poll.cancelled()
    assert scheduler._log_poll_future is None
    assert scheduler._next_log_poll_at == 0.0

    scheduler.remove_stopped_container_log_tracking({"two"})
    assert scheduler._log_cursor_by_container_id == {"two": 20}


def test_fetch_log_update_trims_data_in_worker_path(
    scheduler_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = scheduler_factory(
        state,
        AppConfig(max_log_lines=2, max_log_line_chars=32),
    )
    scheduler = test_setup.scheduler
    container_data_source = test_setup.container_data_source
    container_data_source.get_logs.return_value = f"old\n{'x' * 100}\nnew"

    trimmed_logs = scheduler._fetch_log_update("container-1", "all", 10)

    container_data_source.get_logs.assert_called_once_with(
        "container-1",
        "all",
        10,
    )
    assert trimmed_logs.splitlines()[-1] == "new"
    assert "old" not in trimmed_logs


def test_initial_log_snapshot_is_pending_only_during_first_tab_load(
    scheduler_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    scheduler = scheduler_factory(state).scheduler
    scheduler._tab_load_future = Future()

    assert scheduler._initial_log_snapshot_pending("container-1")

    state.tab_content_cache[ContainerTabKey("container-1", TabName.LOGS)] = "logs"
    assert not scheduler._initial_log_snapshot_pending("container-1")
