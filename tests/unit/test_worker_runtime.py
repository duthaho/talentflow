import signal

import pytest

from app.shared import worker_runtime
from app.shared.worker_runtime import WorkerLoop


class Probe:
    def __init__(self) -> None:
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True


def test_worker_loop_drains_current_cycle_before_stopping() -> None:
    cycles: list[str] = []
    stopped: list[str] = []
    probe = Probe()
    loop: WorkerLoop

    def cycle() -> int:
        cycles.append("completed")
        loop.request_stop()
        return 0

    loop = WorkerLoop(
        name="test",
        cycle=cycle,
        readiness_check=lambda: None,
        shutdown=lambda: stopped.append("released"),
        probe_server=probe,  # type: ignore[arg-type]
    )
    loop.run()

    assert cycles == ["completed"]
    assert stopped == ["released"]
    assert probe.started and probe.closed


def test_worker_loop_runs_one_bounded_smoke_cycle() -> None:
    cycles: list[str] = []
    loop = WorkerLoop(
        name="test",
        cycle=lambda: cycles.append("completed") or 0,
        readiness_check=lambda: None,
        probe_server=Probe(),  # type: ignore[arg-type]
    )

    loop.run(once=True)

    assert cycles == ["completed"]


def test_sigterm_requests_a_graceful_worker_stop(monkeypatch) -> None:
    handlers = {}
    loop = WorkerLoop(
        name="test",
        cycle=lambda: 0,
        readiness_check=lambda: None,
        probe_server=Probe(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        worker_runtime.signal,
        "signal",
        lambda number, handler: handlers.setdefault(number, handler),
    )
    monkeypatch.setattr(worker_runtime.signal, "setitimer", lambda *_: None)

    loop._install_signal_handlers()
    handlers[signal.SIGTERM](signal.SIGTERM, None)

    assert loop._stop.is_set()


def test_grace_period_force_stop_releases_work() -> None:
    released: list[str] = []
    loop = WorkerLoop(
        name="test",
        cycle=lambda: 0,
        readiness_check=lambda: None,
        shutdown=lambda: released.append("released"),
        probe_server=Probe(),  # type: ignore[arg-type]
    )

    with pytest.raises(SystemExit):
        loop._force_stop(signal.SIGALRM, None)

    assert released == ["released"]
