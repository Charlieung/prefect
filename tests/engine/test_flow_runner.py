import datetime

import pytest

import prefect
from prefect.core import Flow, Task
from prefect.engine import FlowRunner, signals
from prefect.engine.state import (
    Failed,
    Finished,
    Pending,
    Retrying,
    Running,
    Scheduled,
    Skipped,
    State,
    Success,
    TriggerFailed,
)
from prefect.utilities.tests import raise_on_exception, run_flow_runner_test


class SuccessTask(Task):
    def run(self):
        return 1


class AddTask(Task):
    def run(self, x, y):  # pylint: disable=W0221
        return x + y


class ErrorTask(Task):
    def run(self):
        raise ValueError("custom-error-message")


class RaiseFailTask(Task):
    def run(self):
        raise prefect.engine.signals.FAIL("custom-fail-message")
        raise ValueError("custom-error-message")  # pylint: disable=W0101


class RaiseSkipTask(Task):
    def run(self):
        raise prefect.engine.signals.SKIP()
        raise ValueError()  # pylint: disable=W0101


class RaiseSuccessTask(Task):
    def run(self):
        raise prefect.engine.signals.SUCCESS()
        raise ValueError()  # pylint: disable=W0101


class RaiseRetryTask(Task):
    def run(self):
        raise prefect.engine.signals.RETRY()
        raise ValueError()  # pylint: disable=W0101


def test_flow_runner_runs_basic_flow_with_1_task():
    flow = prefect.Flow()
    task = SuccessTask()
    flow.add_task(task)
    flow_runner = FlowRunner(flow=flow)
    state = flow_runner.run(return_tasks=[task])
    assert state == Success(data={task: Success(data=1)})


def test_flow_runner_with_no_return_tasks():
    """
    Make sure FlowRunner accepts return_tasks=None and doesn't raise early error
    """
    flow = prefect.Flow()
    task = SuccessTask()
    flow.add_task(task)
    flow_runner = FlowRunner(flow=flow)
    assert flow_runner.run(return_tasks=None)


def test_flow_runner_with_invalid_return_tasks():
    flow = prefect.Flow()
    task = SuccessTask()
    flow.add_task(task)
    flow_runner = FlowRunner(flow=flow)
    with pytest.raises(ValueError):
        flow_runner.run(return_tasks=[1])


def test_flow_runner_runs_basic_flow_with_2_independent_tasks():
    flow = prefect.Flow()
    task1 = SuccessTask()
    task2 = SuccessTask()

    flow.add_task(task1)
    flow.add_task(task2)

    flow_state = FlowRunner(flow=flow).run(return_tasks=[task1, task2])
    assert isinstance(flow_state, Success)
    assert flow_state.data[task1] == Success(data=1)
    assert flow_state.data[task2] == Success(data=1)


def test_flow_runner_runs_basic_flow_with_2_dependent_tasks():
    flow = prefect.Flow()
    task1 = SuccessTask()
    task2 = SuccessTask()

    flow.add_edge(task1, task2)

    flow_state = FlowRunner(flow=flow).run(return_tasks=[task1, task2])
    assert isinstance(flow_state, Success)
    assert flow_state.data[task1] == Success(data=1)
    assert flow_state.data[task2] == Success(data=1)


def test_flow_runner_runs_basic_flow_with_2_dependent_tasks_and_first_task_fails():
    flow = prefect.Flow()
    task1 = ErrorTask()
    task2 = SuccessTask()

    flow.add_edge(task1, task2)

    flow_state = FlowRunner(flow=flow).run(return_tasks=[task1, task2])
    assert isinstance(flow_state, Failed)
    assert isinstance(flow_state.data[task1], Failed)
    assert isinstance(flow_state.data[task2], TriggerFailed)


def test_flow_runner_runs_flow_with_2_dependent_tasks_and_first_task_fails_and_second_has_trigger():
    flow = prefect.Flow()
    task1 = ErrorTask()
    task2 = SuccessTask(trigger=prefect.triggers.all_failed)

    flow.add_edge(task1, task2)

    flow_state = FlowRunner(flow=flow).run(return_tasks=[task1, task2])
    assert isinstance(
        flow_state, Success
    )  # flow state is determined by terminal states
    assert isinstance(flow_state.data[task1], Failed)
    assert isinstance(flow_state.data[task2], Success)


def test_flow_runner_runs_basic_flow_with_2_dependent_tasks_and_first_task_fails_with_FAIL():
    flow = prefect.Flow()
    task1 = RaiseFailTask()
    task2 = SuccessTask()

    flow.add_edge(task1, task2)

    flow_state = FlowRunner(flow=flow).run(return_tasks=[task1, task2])
    assert isinstance(flow_state, Failed)
    assert isinstance(flow_state.data[task1], Failed)
    assert not isinstance(flow_state.data[task1], TriggerFailed)
    assert isinstance(flow_state.data[task2], TriggerFailed)


def test_flow_runner_runs_basic_flow_with_2_dependent_tasks_and_second_task_fails():
    flow = prefect.Flow()
    task1 = SuccessTask()
    task2 = ErrorTask()

    flow.add_edge(task1, task2)

    flow_state = FlowRunner(flow=flow).run(return_tasks=[task1, task2])
    assert isinstance(flow_state, Failed)
    assert isinstance(flow_state.data[task1], Success)
    assert isinstance(flow_state.data[task2], Failed)


def test_flow_runner_does_not_return_task_states_when_it_doesnt_run():
    flow = prefect.Flow()
    task1 = SuccessTask()
    task2 = ErrorTask()

    flow.add_edge(task1, task2)

    flow_state = FlowRunner(flow=flow).run(
        state=Success(data=5), return_tasks=[task1, task2]
    )
    assert isinstance(flow_state, Success)
    assert flow_state.data == 5


def test_flow_run_method_returns_task_states_even_if_it_doesnt_run():
    # https://github.com/PrefectHQ/prefect/issues/19
    flow = prefect.Flow()
    task1 = SuccessTask()
    task2 = ErrorTask()

    flow.add_edge(task1, task2)

    flow_state = flow.run(state=Success(), return_tasks=[task1, task2])
    assert isinstance(flow_state, Success)
    assert isinstance(flow_state.data[task1], Pending)
    assert isinstance(flow_state.data[task2], Pending)


def test_flow_runner_remains_pending_if_tasks_are_retrying():
    # https://github.com/PrefectHQ/prefect/issues/19
    flow = prefect.Flow()
    task1 = SuccessTask()
    task2 = ErrorTask(max_retries=1)

    flow.add_edge(task1, task2)

    flow_state = FlowRunner(flow=flow).run(return_tasks=[task1, task2])
    assert isinstance(flow_state, Pending)
    assert isinstance(flow_state.data[task1], Success)
    assert isinstance(flow_state.data[task2], Retrying)


def test_flow_runner_doesnt_return_by_default():
    flow = prefect.Flow()
    task1 = SuccessTask()
    task2 = SuccessTask()
    flow.add_edge(task1, task2)
    res = flow.run()
    assert res.data == {}


def test_flow_runner_does_return_tasks_when_requested():
    flow = prefect.Flow()
    task1 = SuccessTask()
    task2 = SuccessTask()
    flow.add_edge(task1, task2)
    flow_state = FlowRunner(flow=flow).run(return_tasks=[task1])
    assert isinstance(flow_state, Success)
    assert isinstance(flow_state.data[task1], Success)


def test_required_parameters_must_be_provided():
    flow = prefect.Flow()
    y = prefect.Parameter("y")
    flow.add_task(y)
    flow_state = FlowRunner(flow=flow).run()
    assert isinstance(flow_state, Failed)
    assert isinstance(flow_state.message, prefect.engine.signals.FAIL)
    assert "required parameter" in str(flow_state.message).lower()


def test_missing_parameter_returns_failed_with_no_data():
    flow = prefect.Flow()
    task = AddTask()
    y = prefect.Parameter("y")
    task.set_dependencies(flow, keyword_tasks=dict(x=1, y=y))
    flow_state = FlowRunner(flow=flow).run(return_tasks=[task])
    assert isinstance(flow_state, Failed)
    assert flow_state.data is None


def test_missing_parameter_returns_failed_with_pending_tasks_if_called_from_flow():
    flow = prefect.Flow()
    task = AddTask()
    y = prefect.Parameter("y")
    task.set_dependencies(flow, keyword_tasks=dict(x=1, y=y))
    flow_state = flow.run(return_tasks=[task])
    assert isinstance(flow_state, Failed)
    assert isinstance(flow_state.data[task], Pending)


def test_missing_parameter_error_is_surfaced():
    flow = prefect.Flow()
    task = AddTask()
    y = prefect.Parameter("y")
    task.set_dependencies(flow, keyword_tasks=dict(x=1, y=y))
    msg = flow.run().message
    assert isinstance(msg, prefect.engine.signals.FAIL)
    assert "required parameter" in str(msg).lower()


class TestFlowRunner_get_pre_run_state:
    def test_runs_as_expected(self):
        flow = prefect.Flow()
        task1 = SuccessTask()
        task2 = SuccessTask()
        flow.add_edge(task1, task2)

        state = FlowRunner(flow=flow).get_pre_run_state(state=Pending())
        assert isinstance(state, Running)

    def test_raises_fail_if_required_parameters_missing(self):
        flow = prefect.Flow()
        y = prefect.Parameter("y")
        flow.add_task(y)
        flow_state = FlowRunner(flow=flow).get_pre_run_state(state=Pending())
        assert isinstance(flow_state, Failed)
        assert isinstance(flow_state.message, prefect.engine.signals.FAIL)
        assert "required parameter" in str(flow_state.message).lower()

    @pytest.mark.parametrize("state", [Success(), Failed()])
    def test_raise_dontrun_if_state_is_finished(self, state):
        flow = prefect.Flow()
        task1 = SuccessTask()
        task2 = SuccessTask()
        flow.add_edge(task1, task2)

        with pytest.raises(signals.DONTRUN) as exc:
            FlowRunner(flow=flow).get_pre_run_state(state=state)
        assert "already finished" in str(exc.value).lower()

    def test_raise_dontrun_for_unknown_state(self):
        class MyState(State):
            pass

        flow = prefect.Flow()
        task1 = SuccessTask()
        task2 = SuccessTask()
        flow.add_edge(task1, task2)

        with pytest.raises(signals.DONTRUN) as exc:
            FlowRunner(flow=flow).get_pre_run_state(state=MyState())
        assert "not ready to run" in str(exc.value).lower()


class TestFlowRunner_get_run_state:
    @pytest.mark.parametrize("state", [Pending(), Failed(), Success()])
    def test_raises_dontrun_if_not_running(self, state):
        flow = prefect.Flow()
        task1 = SuccessTask()
        task2 = SuccessTask()
        flow.add_edge(task1, task2)

        with pytest.raises(signals.DONTRUN) as exc:
            FlowRunner(flow=flow).get_run_state(state=state)
        assert "not in a running state" in str(exc.value).lower()


class TestStartTasks:
    def test_start_tasks_doesnt_have_access_to_previous_states(self):
        f = Flow()
        t1, t2 = Task("1"), Task("2")
        f.add_edge(t1, t2)
        FlowRunner(flow=f).run()
        with raise_on_exception():
            with pytest.raises(KeyError):
                FlowRunner(flow=f).run(start_tasks=[t2])

    def test_start_tasks_ignores_triggers(self):
        f = Flow()
        t1, t2 = SuccessTask(), SuccessTask()
        f.add_edge(t1, t2)
        with raise_on_exception():
            state = FlowRunner(flow=f).run(task_states={t1: Failed()}, start_tasks=[t2])
        assert isinstance(state, Success)


@pytest.fixture
def count_task():
    class CountTask(Task):
        call_count = 0
        def run(self):
            self.call_count += 1
            return self.call_count
    return CountTask


@pytest.fixture
def return_task():
    class ReturnTask(Task):
        called = False
        def run(self, x):
            if called is False:
                raise ValueError("Must call twice.")
            return x
    return ReturnTask


class TestInputCacheing:
    def test_retries_use_cached_inputs(self, count_task, return_task):
        with Flow() as f:
            a = count_task()
            b = return_task(max_retries=1)
            result = b(a())

        first_state = FlowRunner(flow=f).run(return_tasks=[result])
        assert isinstance(first_state, Pending)
        with raise_on_exception(): # without cacheing we'd expect a KeyError
            second_state = FlowRunner(flow=f).run(return_tasks=[b], start_tasks=[b],
                                                  task_states={b: first_state.data[result]})
        assert isinstance(second_state, Success)
        assert second_state.data[b].data == 1

    def test_retries_only_uses_cache_data(self, return_task):
        with Flow() as f:
            t1 = Task()
            t2 = return_task()
            result = t2(t1())

        state = FlowRunner(flow=f).run(task_states={t2: Retrying(data={'input_cache': {'x': 5}})},
                                       start_tasks=[t2], return_tasks=[t2])
        assert isinstance(state, Success)
        assert state.data[t2].data == 5

    def test_retries_caches_parameters_as_well(self, return_task):
        with Flow() as f:
            x = Parameter("x")
            a = return_task()
            result = a(x)

        first_state = FlowRunner(flow=f).run(parameters=dict(x=1), return_tasks=[a])
        assert isinstance(first_state, Failed)
        second_state = FlowRunner(flow=f).run(parameters=dict(x=2), return_tasks=[a],
                                              start_tasks=[a], task_states=dict(a=first_state.data[a]))
        assert isinstance(second_state, Success)
        assert second_state.data[a].data == 1
